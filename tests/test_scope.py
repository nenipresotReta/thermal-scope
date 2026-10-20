import csv,io,json,math,socket,struct,sys,tempfile,threading,time,unittest,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Store,Scope,Server,Handler,receive
from thermal_model import predict

class ModelTest(unittest.TestCase):
 def rows(self,f):return [dict(t=1000+i/10,raw=f(i/10)+.015*math.sin(i*3),temperature=f(i/10)) for i in range(900)]
 def test_known_heating_and_cooling(self):
  for f,tau in [(lambda t:23+50*math.exp(-t/60),60),(lambda t:200-180*math.exp(-t/90),90)]:
   p=predict(self.rows(f),horizon=30);self.assertTrue(p['valid'],p)
   self.assertLess(abs(p['tau_s']-tau),1)
   self.assertLess(abs(p['points'][-1]['temperature']-f(119.9)),.08)
   self.assertEqual(p['target'],'smoothed_probe_reading');self.assertIsNone(p['probe_tau_s'])
 def test_equilibrium_and_unresolved_linear_heating(self):
  flat=predict(self.rows(lambda t:25));self.assertTrue(flat['valid']);self.assertFalse(flat['identifiable']);self.assertEqual(flat['points'][-1]['temperature'],25)
  ramp=predict(self.rows(lambda t:20+.2*t));self.assertTrue(ramp['valid']);self.assertFalse(ramp['identifiable']);self.assertGreater(ramp['points'][-1]['temperature'],ramp['points'][0]['temperature'])
  self.assertFalse(predict(self.rows(lambda t:30+math.exp(-t/60)),now=2000)['valid'])
 def test_warming_after_cooling_cannot_reverse(self):
  def temperature(t):return 40-.3*t if t<70 else 19+15*(1-math.exp(-(t-70)/15))
  p=predict(self.rows(temperature));self.assertTrue(p['valid'])
  values=[r['temperature'] for r in p['points']]
  self.assertTrue(all(b>=a for a,b in zip(values,values[1:])))
  self.assertGreater(p['equilibrium_c'],values[0])
 def test_forward_energy_balance_and_monotonicity(self):
  # Independently integrate C*dT/dt=P-G*(T-Ta) using RK4.
  for heat in (True,False):
   C,G,Ta=120.,2.,23.;P=100. if heat else 0.;T=25. if heat else 80.
   data=[];dt=.1
   def rate(y):return (P-G*(y-Ta))/C
   for i in range(1201):
    if i<901:data.append(dict(t=1000+i*dt,temperature=T,raw=T,d1=rate(T),d2=-G/C*rate(T)))
    if i==900:pred=predict(data,horizon=30)
    if i==1200:expected=T
    a=rate(T);b=rate(T+dt*a/2);c=rate(T+dt*b/2);d=rate(T+dt*c);T+=dt*(a+2*b+2*c+d)/6
   self.assertLess(abs(pred['points'][-1]['temperature']-expected),.1)
   values=[r['temperature'] for r in pred['points']];sgn=1 if heat else -1
   self.assertTrue(all(sgn*(b-a)>=0 for a,b in zip(values,values[1:])))
   self.assertGreater(pred['tau_s'],0)
   self.assertTrue(all(min(values[0],pred['equilibrium_c'])-1e-9<=v<=max(values[0],pred['equilibrium_c'])+1e-9 for v in values))
 def test_history_gap_uses_only_new_segment(self):
  rows=self.rows(lambda t:23+50*math.exp(-t/60));rows=[p for p in rows if not 1060<p['t']<1064]
  p=predict(rows);self.assertTrue(p['valid']);self.assertLess(p.get('fit_window_s',0),30)

class ServiceTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'scope.db');self.scope=Scope(self.store,'127.0.0.1',.1)
  self.server=Server(('127.0.0.1',0),Handler);self.server.scope=self.scope
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.server.server_port)
 def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
 def get(self,path):return urllib.request.urlopen(self.url+path,timeout=5)
 def action(self,action,**kw):
  req=urllib.request.Request(self.url+'/api/action',data=json.dumps(dict(action=action,**kw)).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=5) as r:return json.load(r)
 def test_record_events_export_and_restart(self):
  r=self.action('start',name='Integration test');rid=r['runs'][0]['id'];start=r['runs'][0]['start']
  self.action('event',label='CHARGE');self.action('event',label='FC START');self.action('undo')
  with self.store.connect() as db:
   db.execute('INSERT INTO samples(t,raw,temperature,d1,d2) VALUES(?,?,?,?,?)',(time.time(),25,25,.1,.01))
  r=self.action('event',label='DROP');self.assertIsNotNone(r['runs'][0]['end']);self.assertEqual([e['label'] for e in r['events']],['CHARGE','DROP'])
  with self.get('/api/export?run='+str(rid)) as response:rows=list(csv.reader(io.StringIO(response.read().decode())))
  self.assertEqual(len(rows[0]),7);self.assertIn('d1_c_per_s',rows[0]);self.assertIn('DROP',str(rows))
  restored=Store(self.store.path);self.assertEqual(restored.runs()[0]['name'],'Integration test')
  with self.get('/api/history?start='+str(start-1)) as r:self.assertEqual(len(json.load(r)['samples']),1)
 def test_recording_script_and_weight_api(self):
  with self.get('/recording.js') as r:self.assertIn(b'function recordingWindow',r.read())
  run=self.action('start',name='Coffee weights',mode='coffee')['runs'][0]
  self.action('event',label='FC START')
  self.action('stop')
  saved=self.action('weights',run_id=run['id'],green_weight_g=200,roasted_weight_g=170)['runs'][0]
  self.assertEqual(saved['weight_loss_pct'],15)
  self.assertGreaterEqual(saved['development_s'],0)
  restored=Store(self.store.path).runs()[0];self.assertEqual(restored['green_weight_g'],200)
  with self.assertRaises(urllib.error.HTTPError):self.action('weights',run_id=run['id'],green_weight_g=200,roasted_weight_g=201)
 def test_invalid_write_and_history(self):
  with self.assertRaises(urllib.error.HTTPError):self.action('event',label='CHARGE')
  req=urllib.request.Request(self.url+'/api/action',data=b'{"action":"start"}',headers={'Content-Type':'application/json','Origin':'http://other.invalid'})
  with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(req)
  self.assertEqual(error.exception.code,403)
  with self.assertRaises(urllib.error.HTTPError):self.get('/api/history?start=nan')
 def test_sse_snapshot(self):
  with self.get('/api/stream') as r:
   self.assertEqual(r.readline(),b'event: status\n');self.assertIn(b'connected',r.readline())

class CollectorTest(unittest.TestCase):
 def test_fragmented_modbus_and_reconnect(self):
  listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(.5);port=listener.getsockname()[1];stop=threading.Event();requests=[]
  def fake():
   count=0
   while not stop.is_set():
    try:s,_=listener.accept()
    except socket.timeout:continue
    with s:
     s.settimeout(2)
     while not stop.is_set():
      try:
       q=receive(s,12);count+=1
       if count==5:break
       tid=struct.unpack('>H',q[:2])[0];reply=struct.pack('>HHHBBBffff',tid,0,19,1,3,16,25.,25.,.1,.01)
       s.sendall(reply[:4]);s.sendall(reply[4:]);requests.append(time.monotonic())
      except OSError:break
  thread=threading.Thread(target=fake,daemon=True);thread.start()
  # Test the same collector while routing only the Modbus port to a local fixture.
  import server
  original=server.socket.create_connection
  def connect(address,timeout):return original((address[0],port),timeout)
  with tempfile.TemporaryDirectory() as directory:
   scope=Scope(Store(Path(directory)/'scope.db'),'127.0.0.1',.1);server.socket.create_connection=connect
   worker=threading.Thread(target=scope.collect);worker.start()
   try:
    deadline=time.monotonic()+5
    while len(requests)<14 and time.monotonic()<deadline:time.sleep(.05)
    self.assertGreaterEqual(len(requests),14);self.assertTrue(scope.status()['connected']);self.assertAlmostEqual(scope.latest['temperature'],25)
   finally:
    scope.stop.set();worker.join(3);server.socket.create_connection=original;stop.set();thread.join(3);listener.close()
   with scope.store.connect() as db:self.assertGreaterEqual(db.execute('SELECT count(*) FROM samples').fetchone()[0],14)


class CalibrationTest(unittest.TestCase):
 def test_clean_step_and_bad_data(self):
  from calibration import fit_step
  rows=[{'t':1000+i*.1,'raw':70-45*math.exp(-i*.1/3)+.01*math.sin(i)} for i in range(400)]
  fit=fit_step(rows);self.assertTrue(fit['valid'],fit);self.assertLess(abs(fit['tau_s']-3),.15)
  self.assertFalse(fit_step(rows[:20])['valid'])
  self.assertFalse(fit_step([{'t':r['t'],'raw':25} for r in rows])['valid'])

class LearningTest(unittest.TestCase):
 def test_ledger_scores_only_later_actuals(self):
  from learning import Ledger
  with tempfile.TemporaryDirectory() as tmp:
   store=Store(Path(tmp)/'db');ledger=Ledger();now=time.time();recent=[{'t':now-40+i*.1,'temperature':25+i*.01,'raw':25+i*.01,'d1':.1,'d2':0} for i in range(401)]
   with store.connect() as db:
    ledger.tick(db,recent[-1],recent,{})
    row=db.execute('SELECT * FROM forecasts WHERE horizon=5').fetchone();self.assertIsNone(row['actual']);self.assertGreater(row['predicted'],row['baseline']);baseline=row['baseline'];frozen=row['predicted']
    before={**recent[-1],'t':now+4.95,'temperature':30};after={**before,'t':now+5.05,'temperature':32}
    ledger.previous=before;ledger.tick(db,after,recent+[before,after],{})
    scored=db.execute('SELECT * FROM forecasts WHERE id=?',(row['id'],)).fetchone();self.assertAlmostEqual(scored['actual'],31,places=3);self.assertEqual(scored['baseline'],baseline);self.assertEqual(scored['predicted'],frozen);self.assertEqual(scored['version'],'thermal-balance-v2')


class ContinuousForecastTest(unittest.TestCase):
 def test_cold_start_has_prediction_without_regime_label(self):
  from learning import forecast
  row={'t':time.time(),'temperature':25,'raw':25,'d1':0,'d2':0}
  p=forecast({},[row]);self.assertTrue(p['valid']);self.assertEqual(p['reason'],'INITIAL STATE · NET HEAT UNKNOWN');self.assertEqual(p['horizon_s'],300);self.assertLess(len(p['points']),40)
  self.assertEqual(p['points'][-1]['temperature'],25)

if __name__=='__main__':unittest.main()

class LongHorizonTest(unittest.TestCase):
 def test_five_minutes_are_coarse_and_same_physical_trajectory(self):
  rows=[dict(t=1000+i/10,raw=80-50*math.exp(-i/10/60),temperature=80-50*math.exp(-i/10/60),d1=0,d2=0) for i in range(900)]
  p=predict(rows);self.assertEqual(p['horizon_s'],300);self.assertLess(len(p['points']),40)
  self.assertAlmostEqual(p['points'][-1]['t']-p['points'][0]['t'],300)
  for h in (30,60,180,300):self.assertTrue(any(abs(q['t']-rows[-1]['t']-h)<.001 for q in p['points']))
  values=[q['temperature'] for q in p['points']];self.assertTrue(all(b>=a for a,b in zip(values,values[1:])))
  self.assertLess(abs(values[-1]-(80-50*math.exp(-389.9/60))),.1)
