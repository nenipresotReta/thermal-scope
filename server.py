#!/usr/bin/env python3
"""One shared Modbus collector, SQLite history, bounded SSE fan-out. Stdlib only."""
import argparse, csv, io, json, math, os, queue, signal, socket, sqlite3, struct, threading, time
from collections import deque
from thermal_model import predict
from calibration import fit_step
from learning import Ledger,forecast,HORIZONS
from thermal_model import VERSION
from roast import DropMonitor, metrics, weights
from devices import Discovery,probe_device,validate_host,suggested_networks
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

ROOT = Path(__file__).parent
EVENTS = ('CHARGE', 'DRY END', 'FC START', 'FC END', 'SC START', 'DROP', 'EVENT')

def receive(sock, count):
    result = bytearray()
    while len(result) < count:
        chunk = sock.recv(count-len(result))
        if not chunk: raise ConnectionError('Device closed connection')
        result.extend(chunk)
    return bytes(result)

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:return super().__exit__(exc_type, exc_value, traceback)
        finally:self.close()

class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY, t REAL NOT NULL, raw REAL, temperature REAL, d1 REAL, d2 REAL);
            CREATE INDEX IF NOT EXISTS samples_time ON samples(t);
            CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, name TEXT NOT NULL, start REAL NOT NULL, end REAL);
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs((1)) WHERE end IS NULL;
            CREATE TABLE IF NOT EXISTS forecasts(id INTEGER PRIMARY KEY, created REAL NOT NULL, target REAL NOT NULL, horizon INTEGER NOT NULL, features TEXT NOT NULL, baseline REAL NOT NULL, linear REAL NOT NULL, predicted REAL, actual REAL, version TEXT NOT NULL, model_snapshot TEXT, trainable INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS forecast_pending ON forecasts(target) WHERE actual IS NULL;
            CREATE INDEX IF NOT EXISTS forecast_training ON forecasts(horizon,created);
            CREATE TABLE IF NOT EXISTS model_state(id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calibrations(id INTEGER PRIMARY KEY, medium TEXT NOT NULL, start REAL NOT NULL, end REAL, result TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_calibration ON calibrations((1)) WHERE end IS NULL;
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES runs(id), t REAL NOT NULL, label TEXT NOT NULL, temperature REAL);
            ''')
            for table, definitions in {
                'runs': {'mode': "TEXT NOT NULL DEFAULT 'coffee'", 'auto_drop': 'INTEGER NOT NULL DEFAULT 1', 'green_weight_g': 'REAL', 'roasted_weight_g': 'REAL'},
                'events': {'source': "TEXT NOT NULL DEFAULT 'manual'", 'detected_at': 'REAL'},
            }.items():
                present={r[1] for r in db.execute('PRAGMA table_info('+table+')')}
                for name, definition in definitions.items():
                    if name not in present:db.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+definition)
            db.execute('CREATE INDEX IF NOT EXISTS events_run ON events(run_id,t)')
            columns={r[1] for r in db.execute('PRAGMA table_info(forecasts)')}
            if 'model_snapshot' not in columns:db.execute('ALTER TABLE forecasts ADD COLUMN model_snapshot TEXT')
            if 'trainable' not in columns:db.execute('ALTER TABLE forecasts ADD COLUMN trainable INTEGER NOT NULL DEFAULT 1')
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db
    def runs(self):
        with self.connect() as db:
            rows=[dict(r) for r in db.execute('''SELECT r.*,
                (SELECT min(t) FROM events WHERE run_id=r.id AND label='FC START') fc_start,
                (SELECT min(t) FROM events WHERE run_id=r.id AND label='DROP' AND r.mode='coffee') drop_t,
                (SELECT source FROM events WHERE run_id=r.id AND label='DROP' ORDER BY t LIMIT 1) drop_source
                FROM runs r ORDER BY start DESC LIMIT 100''')]
            return [{**r, **metrics(r,time.time())} for r in rows]
    def calibrations(self):
        with self.connect() as db:
            return [{**dict(r),'result':json.loads(r['result']) if r['result'] else None} for r in db.execute('SELECT * FROM calibrations ORDER BY start DESC LIMIT 50')]
    def events(self, start=0, end=1e20):
        with self.connect() as db: return [dict(r) for r in db.execute('SELECT * FROM events WHERE t BETWEEN ? AND ? ORDER BY t', (start,end))]
    def history(self, start, end):
        with self.connect() as db:
            # Bound transfer for long intervals, preserve each bucket's extremes.
            width = max((end-start)/9000, .00001)
            rows = db.execute('''SELECT min(t) t, avg(raw) raw, avg(temperature) temperature,
                avg(d1) d1, avg(d2) d2, min(temperature) low, max(temperature) high
                FROM samples WHERE t BETWEEN ? AND ? GROUP BY CAST((t-?)/? AS INTEGER) ORDER BY t''', (start,end,start,width))
            return [dict(r) for r in rows]

class Scope:
    def __init__(self, store, host, interval):
        self.store, self.host, self.interval = store, host, interval
        self.source_revision=0
        self.auto_check_at=0
        self.drop_monitor=DropMonitor()
        self.config_lock=threading.Lock()
        self.discovery=Discovery()
        self.lock = threading.Lock()
        self.subscribers = set()
        self.latest = None
        self.recent = deque(maxlen=1200)
        self.prediction = forecast({},[])
        self.model_at = 0
        self.ledger=Ledger()
        self.models={}  # Never load old unconstrained regression weights.
        self.state = {'connected':False, 'message':'Connecting' if host else 'Select a device', 'host':host, 'interval':interval,'timestamp_source':'server_receipt'}
        self.stop = threading.Event()
    def device_status(self):
        with self.lock:host=self.host;connected=self.state['connected']
        return {'host':host,'connected':connected,'networks':suggested_networks(host)}
    def configure_device(self,data):
        action=data.get('action')
        if action=='discover':return self.discovery.start(data.get('network',''))
        if action not in ('test','connect'):raise ValueError('Unknown device action')
        host=validate_host(data.get('host',''));result=probe_device(host)
        if action=='test':return result
        with self.config_lock:
            with self.lock:changing=host!=self.host
            if changing:
                with self.store.connect() as db:
                    if db.execute('SELECT 1 FROM runs WHERE end IS NULL').fetchone() or db.execute('SELECT 1 FROM calibrations WHERE end IS NULL').fetchone():
                        raise ValueError('Finish the current recording or calibration before changing devices')
            target=Path(self.store.path).parent/'device.json';temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps({'host':host})+'\n');temporary.replace(target)
            with self.lock:
                if self.host!=host:
                    self.host=host;self.source_revision+=1;self.latest=None;self.prediction=forecast({},[])
                    self.state.update(host=host,connected=False,message='Connecting to selected device')
        self.publish('status',self.status())
        return {**result,'saved':True}
    def publish(self, kind, payload):
        message = 'event: '+kind+'\ndata: '+json.dumps(payload, allow_nan=False,separators=(',',':'))+'\n\n'
        with self.lock:
            for q in list(self.subscribers):
                try: q.put_nowait(message)
                except queue.Full:
                    # Disconnect slow viewers; on reconnect they backfill from SQLite.
                    self.subscribers.discard(q)
                    while not q.empty(): q.get_nowait()
                    q.put_nowait(None)
    def status(self):
        with self.lock:
            return {**self.state, 'latest':self.latest, 'viewers':len(self.subscribers), 'now':time.time(), 'prediction':self.prediction,'learning':self.learning_status()}
    def learning_status(self):
        p=self.prediction
        return {str(h):{'valid':p.get('identifiable',False),'reason':p.get('reason','WAITING FOR DATA'),
            'tau_s':p.get('tau_s'),'equilibrium_c':p.get('equilibrium_c'),'fit_rmse_c':p.get('fit_rmse_c'),
            'version':VERSION} for h in HORIZONS}
    def collect(self):
        sock = None; connection_revision=-1; tid = 0; next_tick = time.monotonic(); committed = time.monotonic()
        db = self.store.connect()
        while not self.stop.is_set():
            try:
                with self.lock:host=self.host;revision=self.source_revision
                if revision!=connection_revision:
                    if sock:sock.close();sock=None
                    db.commit();self.recent.clear();self.ledger=Ledger();connection_revision=revision
                if not host:
                    self.stop.wait(.5);continue
                if sock is None:
                    sock = socket.create_connection((host,502),2)
                    sock.settimeout(.8); sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                tid = tid%65535+1
                begin=time.monotonic()
                sock.sendall(struct.pack('>HHHBBHH',tid,0,6,1,3,0,8))
                h=receive(sock,7); transaction,protocol,n,unit=struct.unpack('>HHHB',h)
                if transaction!=tid or protocol!=0 or unit!=1 or not 2<=n<=254: raise ValueError('Invalid Modbus header')
                body=receive(sock,n-1)
                if body[0]&128: raise ValueError('Sensor unavailable / warming up (Modbus %d)'%body[1])
                if body[:2]!=b'\x03\x10' or len(body)!=18: raise ValueError('Invalid Modbus response')
                values=struct.unpack('>ffff',body[2:])
                if not all(math.isfinite(x) for x in values): raise ValueError('Invalid sensor values')
                with self.lock:changed=revision!=self.source_revision
                if changed:continue
                row=dict(zip(('raw','temperature','d1','d2'),values));row['t']=time.time()
                db.execute('INSERT INTO samples(t,raw,temperature,d1,d2) VALUES(:t,:raw,:temperature,:d1,:d2)',row)
                if time.monotonic()-committed>=1:
                    db.commit();committed=time.monotonic()
                with self.lock:
                    self.latest=row; self.state.update(connected=True,message='Live',latency_ms=round((time.monotonic()-begin)*1000,1))
                self.publish('sample',row)
                self.recent.append(row)
                self.check_auto_drop(db,row)
                models=self.models
                issued=self.ledger.tick(db,row,list(self.recent),models)
                if issued:
                    model=self.ledger.last_forecast
                    with self.lock:self.prediction=model
                    self.publish('prediction',model);self.publish('learning',self.learning_status());self.model_at=time.monotonic()
                next_tick += self.interval
                # Never burst old polls after a delay.
                next_tick=max(next_tick,time.monotonic())
                self.stop.wait(max(0,next_tick-time.monotonic()))
            except (OSError,ValueError,ConnectionError) as e:
                if sock:
                    sock.close();sock=None
                db.commit()
                with self.lock:
                    self.state.update(connected=False,message=str(e))
                    self.prediction={'valid':False,'reason':'STALE INPUT','points':[]}
                self.publish('status',self.status())
                self.stop.wait(1);next_tick=time.monotonic()
        db.commit();db.close()
        if sock: sock.close()
    def check_auto_drop(self, db, row):
        if row['t']-self.auto_check_at < .5:return
        self.auto_check_at=row['t']
        run=db.execute("SELECT * FROM runs WHERE end IS NULL AND mode='coffee' AND auto_drop=1").fetchone()
        event=self.drop_monitor.update(list(self.recent),run)
        with self.lock:self.state['drop_detection']=self.drop_monitor.status(row['t'])
        self.publish('drop_detection',self.state['drop_detection'])
        if event is None:return
        changed=db.execute('UPDATE runs SET end=? WHERE id=? AND end IS NULL',(event['t'],run['id'])).rowcount
        if not changed:return
        db.execute("INSERT INTO events(run_id,t,label,temperature,source,detected_at) VALUES(?,?,'DROP',?,'auto',?)",
                   (run['id'],event['t'],event['temperature'],event['detected_at']))
        db.commit()
        with self.lock:self.state['drop_detection']=None
        self.publish('records',{'runs':self.store.runs(),'events':self.store.events(row['t']-86400)})

    def calibrate(self, data):
        action=data.get('action');now=time.time()
        with self.store.connect() as db:
            current=db.execute('SELECT * FROM calibrations WHERE end IS NULL').fetchone()
            if action=='start':
                if current:raise ValueError('A calibration is already running')
                if not self.status()['connected']:raise ValueError('Connect the sensor first')
                medium=data.get('medium')
                if medium not in ('WATER','AIR'):raise ValueError('Choose WATER or AIR')
                db.execute('INSERT INTO calibrations(medium,start) VALUES(?,?)',(medium,now))
            elif action in ('finish','cancel'):
                if not current:raise ValueError('No calibration is active')
                if action=='finish':
                    rows=[dict(r) for r in db.execute('SELECT t,raw FROM samples WHERE t BETWEEN ? AND ? ORDER BY t',(current['start'],now))]
                    result=fit_step(rows)
                    if not result['valid']:raise ValueError(result['reason'])
                else:result={'valid':False,'reason':'Cancelled'}
                db.execute('UPDATE calibrations SET end=?,result=? WHERE id=?',(now,json.dumps(result),current['id']))
            else:raise ValueError('Unknown calibration action')
        result=self.store.calibrations();self.publish('calibration',result);return result
    def action(self, data):
        kind=data.get('action'); now=time.time()
        # Snapshot outside the write transaction; collector doesn't hold lock during I/O.
        with self.lock: latest = dict(self.latest) if self.latest else None
        temperature=latest['temperature'] if latest and now-latest['t']<2 else None
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active=db.execute('SELECT * FROM runs WHERE end IS NULL').fetchone()
            if kind=='start':
                if active: raise ValueError('A recording is already active')
                name=str(data.get('name') or datetime.now().strftime('Roast %Y-%m-%d %H:%M'))[:100]
                mode=data.get('mode','coffee')
                if mode not in ('coffee','general'):raise ValueError('Choose coffee or general mode')
                auto=data.get('auto_drop',True)
                if not isinstance(auto,bool):raise ValueError('auto_drop must be true or false')
                db.execute('INSERT INTO runs(name,start,mode,auto_drop) VALUES(?,?,?,?)',(name,now,mode,int(auto and mode=='coffee')))
            elif kind=='stop':
                if not active: raise ValueError('No recording is active')
                db.execute('UPDATE runs SET end=? WHERE id=?',(now,active['id']))
            elif kind=='event':
                label=str(data.get('label','')).strip()
                if not active: raise ValueError('Start a recording before adding events')
                if not label or len(label)>100: raise ValueError('Event label must be 1–100 characters')
                db.execute('INSERT INTO events(run_id,t,label,temperature) VALUES(?,?,?,?)',(active['id'],now,label,temperature))
                if active['mode']=='coffee' and label=='DROP': db.execute('UPDATE runs SET end=? WHERE id=?',(now,active['id']))
            elif kind=='auto_drop':
                if not active or active['mode']!='coffee':raise ValueError('Auto DROP is available during coffee recordings only')
                enabled=data.get('enabled')
                if not isinstance(enabled,bool):raise ValueError('enabled must be true or false')
                db.execute('UPDATE runs SET auto_drop=? WHERE id=?',(int(enabled),active['id']))
            elif kind=='weights':
                run_id=data.get('run_id')
                if isinstance(run_id,bool) or not isinstance(run_id,int):raise ValueError('Invalid recording ID')
                run=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
                if run is None or run['end'] is None or run['mode']!='coffee':raise ValueError('Weights are available for completed coffee recordings only')
                green,roasted=weights(data.get('green_weight_g'),data.get('roasted_weight_g'))
                db.execute('UPDATE runs SET green_weight_g=?,roasted_weight_g=? WHERE id=?',(green,roasted,run_id))
            elif kind=='undo_drop':
                if active:raise ValueError('Finish the active recording before reopening another')
                run_id=data.get('run_id')
                if isinstance(run_id,bool) or not isinstance(run_id,int):raise ValueError('Invalid recording ID')
                latest_id=db.execute('SELECT id FROM runs ORDER BY start DESC LIMIT 1').fetchone()
                if latest_id is None or latest_id[0]!=run_id:raise ValueError('Only the latest recording can be reopened')
                event=db.execute("SELECT * FROM events WHERE run_id=? AND label='DROP' AND source='auto' ORDER BY t DESC LIMIT 1",(run_id,)).fetchone()
                if event is None:raise ValueError('No automatic DROP to undo')
                db.execute('DELETE FROM events WHERE id=?',(event['id'],))
                db.execute('UPDATE runs SET end=NULL,auto_drop=0 WHERE id=?',(run_id,))
            elif kind=='undo':
                if not active: raise ValueError('No recording is active')
                db.execute('DELETE FROM events WHERE id=(SELECT id FROM events WHERE run_id=? ORDER BY id DESC LIMIT 1)',(active['id'],))
            else: raise ValueError('Unknown action')
        if kind=='auto_drop':
            self.drop_monitor=DropMonitor()
            with self.lock:self.state['drop_detection']=None
        result={'runs':self.store.runs(),'events':self.store.events(now-86400)}
        self.publish('records',result)
        return result

class Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def handle(self):
        try:super().handle()
        except (BrokenPipeError,ConnectionResetError):pass
    def log_message(self, *args): pass
    @property
    def scope(self): return self.server.scope
    def reply(self, data, status=200, mime='application/json'):
        if not isinstance(data,bytes): data=json.dumps(data,allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        parts=urlsplit(self.path); q=parse_qs(parts.query);path=parts.path
        try:
            if path=='/api/device':return self.reply(self.scope.device_status())
            if path=='/api/discovery':return self.reply(self.scope.discovery.status())
            if path=='/api/status': return self.reply(self.scope.status())
            if path=='/api/learning':
                with self.scope.store.connect() as db:
                    metrics=[dict(r) for r in db.execute('SELECT horizon,count(*) n,avg(predicted-actual) bias_c,avg(abs(predicted-actual)) mae_c,avg((predicted-actual)*(predicted-actual)) mse_c FROM forecasts WHERE predicted IS NOT NULL AND actual IS NOT NULL AND version=? GROUP BY horizon',(VERSION,))]
                return self.reply({'models':self.scope.learning_status(),'live_scores':metrics})
            if path=='/api/calibrations': return self.reply(self.scope.store.calibrations())
            if path=='/api/runs': return self.reply(self.scope.store.runs())
            if path=='/api/history':
                end=float(q.get('end',[time.time()])[0]);start=float(q.get('start',[end-3600])[0])
                if not math.isfinite(start+end) or not 0<end-start<=86400*7: raise ValueError('Select a window up to 7 days')
                return self.reply({'samples':self.scope.store.history(start,end),'events':self.scope.store.events(start,end)})
            if path=='/api/events': return self.reply(self.scope.store.events(time.time()-86400))
            if path=='/api/forecast-export':
                with self.scope.store.connect() as db:
                    text=io.StringIO();w=csv.writer(text);w.writerow(('created_epoch_s','target_epoch_s','horizon_s','model_version','prediction_c','actual_c','hold_baseline_c','linear_baseline_c','model_snapshot_json'))
                    for row in db.execute('SELECT created,target,horizon,version,predicted,actual,baseline,linear,model_snapshot FROM forecasts ORDER BY created,horizon'):w.writerow(tuple(row))
                return self.reply(text.getvalue().encode(),mime='text/csv; charset=utf-8')
            if path=='/api/export':
                run_id=int(q.get('run',['0'])[0])
                with self.scope.store.connect() as db:
                    run=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
                    if not run: return self.reply({'error':'Recording not found'},404)
                    rows=db.execute('SELECT t,raw,temperature,d1,d2 FROM samples WHERE t BETWEEN ? AND ? ORDER BY t',(run['start'],run['end'] or time.time()))
                    text=io.StringIO();w=csv.writer(text);w.writerow(('timestamp_utc','elapsed_s','raw_c','temperature_c','d1_c_per_s','d2_c_per_s2','events'))
                    events=[e for e in self.scope.store.events(run['start'],run['end'] or time.time()) if e['run_id']==run_id];ei=0
                    for r in rows:
                        labels=[]
                        while ei<len(events) and events[ei]['t']<=r['t']: labels.append(events[ei]['label']);ei+=1
                        w.writerow((datetime.fromtimestamp(r['t'],timezone.utc).isoformat(),round(r['t']-run['start'],3),*list(r)[1:],' | '.join(labels)))
                    # Preserve events after the last sample, including DROP during a disconnect.
                    for e in events[ei:]:w.writerow((datetime.fromtimestamp(e['t'],timezone.utc).isoformat(),round(e['t']-run['start'],3),'','','','',e['label']))
                return self.reply(text.getvalue().encode(),mime='text/csv; charset=utf-8')
            if path=='/api/stream':
                sub=queue.Queue(maxsize=64)
                with self.scope.lock:self.scope.subscribers.add(sub)
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Cache-Control','no-cache');self.send_header('Connection','keep-alive');self.send_header('X-Accel-Buffering','no');self.end_headers()
                try:
                    self.wfile.write(('event: status\ndata: '+json.dumps(self.scope.status())+'\n\n').encode());self.wfile.flush()
                    while True:
                        try:message=sub.get(timeout=5)
                        except queue.Empty:message=': heartbeat\n\n'
                        if message is None:break
                        self.wfile.write(message.encode());self.wfile.flush()
                finally:
                    with self.scope.lock:self.scope.subscribers.discard(sub)
                self.close_connection=True
                return
            assets={'/recording.js':('recording.js','text/javascript; charset=utf-8'),'/':('index.html','text/html; charset=utf-8'),'/plot-scale.js':('plot-scale.js','text/javascript; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            if path in assets:
                name,mime=assets[path];return self.reply((ROOT/'static'/name).read_bytes(),mime=mime)
            self.reply({'error':'Not found'},404)
        except (ValueError,KeyError) as e:self.reply({'error':str(e)},400)
        except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
    def do_POST(self):
        if self.path not in ('/api/action','/api/calibration','/api/device'):return self.reply({'error':'Not found'},404)
        origin=self.headers.get('Origin')
        if origin and urlsplit(origin).netloc!=self.headers.get('Host'):return self.reply({'error':'Origin rejected'},403)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=4096:raise ValueError('Invalid body length')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Expected JSON')
            data=json.loads(self.rfile.read(n))
            if not isinstance(data,dict):raise ValueError('Expected an object')
            self.reply(self.scope.configure_device(data) if self.path=='/api/device' else self.scope.calibrate(data) if self.path=='/api/calibration' else self.scope.action(data))
        except (ValueError,sqlite3.IntegrityError) as e:self.reply({'error':str(e)},400)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bind',default=os.getenv('BIND','127.0.0.1'));parser.add_argument('--port',type=int,default=int(os.getenv('PORT','8080')));parser.add_argument('--device',default=None);parser.add_argument('--interval',type=float,default=float(os.getenv('POLL_INTERVAL','0.1')));parser.add_argument('--data',default=os.getenv('DATA_DIR',str(ROOT/'data')))
    args=parser.parse_args()
    if not .1<=args.interval<=60:parser.error('interval must be 0.1–60 seconds')
    store=Store(Path(args.data)/'scope.sqlite3')
    saved=Path(args.data)/'device.json';host=args.device
    if host is None and saved.exists():
        try:host=json.loads(saved.read_text()).get('host','')
        except (OSError,ValueError):host=''
    if not host:host=os.getenv('DEVICE_HOST','').strip()
    if host:host=validate_host(host)
    scope=Scope(store,host or '',args.interval)
    server=Server((args.bind,args.port),Handler);server.scope=scope
    thread=threading.Thread(target=scope.collect,daemon=True);thread.start()
    print(f"Thermal Scope: http://{args.bind}:{args.port} • device {host or 'not configured'} • {1/args.interval:g} Hz",flush=True)
    def terminate(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,terminate)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:scope.stop.set();thread.join(4);server.server_close()
if __name__=='__main__':main()
