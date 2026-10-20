import json, math, sqlite3, tempfile, time, unittest
from pathlib import Path
from roast import DropMonitor, detect_drop, metrics, weights
from server import Store, Scope


class RoastTest(unittest.TestCase):
    def test_metrics_live_final_and_weights(self):
        run={'start':1000,'end':None,'mode':'coffee','fc_start':1600,'drop_t':None,'green_weight_g':200,'roasted_weight_g':170}
        self.assertEqual(metrics(run,1800)['development_pct'],25)
        self.assertEqual(metrics(run,1800)['weight_loss_pct'],15)
        self.assertEqual(metrics({**run,'end':1900,'drop_t':1750},9999)['development_pct'],20)
        self.assertIsNone(metrics({**run,'mode':'general'},1800)['development_s'])
        for green,roasted in [(0,1),(10,11),(float('nan'),1),(200,None),(True,1),('200',170)]:
            with self.assertRaises(ValueError):weights(green,roasted)
        self.assertEqual(weights(None,None),(None,None))

    def stream(self,mode='coffee',transient=False,gap=False):
        monitor=DropMonitor();run={'id':1,'start':0,'mode':mode,'auto_drop':1};rows=[];seen=[]
        for i in range(7000,8400):
            t=i/10
            if gap and 781<t<784:continue
            if t<780:v=202+.08*(t-780)
            elif transient and t>=790:v=202+.05*(t-790)
            else:v=25+177*math.exp(-(t-780)/60)
            row={'t':t,'raw':v+.02*math.sin(i*2),'temperature':v,'d1':0,'d2':0}
            rows.append(row)
            if i%5==0:
                event=monitor.update(rows[-250:],run)
                if event:seen.append(event)
        return seen

    def test_sustained_drop_is_confirmed_then_backdated(self):
        found=self.stream();self.assertEqual(len(found),1)
        event=found[0]
        self.assertLess(abs(event['t']-780),1)
        self.assertGreaterEqual(event['detected_at']-event['t'],20)
        self.assertLess(event['detected_at']-event['t'],26)

    def test_transient_and_general_and_gap_do_not_end_recording(self):
        self.assertEqual(self.stream(transient=True),[])
        self.assertEqual(self.stream(mode='general'),[])
        self.assertEqual(self.stream(gap=True),[])
        rows=[{'t':700+i/10,'raw':190+.03*math.sin(i),'temperature':190} for i in range(150)]
        self.assertIsNone(detect_drop(rows,0))
        hot=[{'t':i/10,'raw':200-i*.3,'temperature':200-i*.3} for i in range(100)]
        self.assertIsNone(detect_drop(hot,0))

    def test_legacy_database_migrates_without_losing_records(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'scope.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE runs(id INTEGER PRIMARY KEY,name TEXT NOT NULL,start REAL NOT NULL,end REAL)')
                db.execute("INSERT INTO runs VALUES(1,'Original roast',1000,1800)")
            store=Store(path);run=store.runs()[0]
            self.assertEqual(run['name'],'Original roast');self.assertEqual(run['mode'],'coffee')
            self.assertIsNone(run['weight_loss_pct'])
            Store(path)

    def test_recording_modes_weights_and_auto_undo(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'scope.sqlite3');scope=Scope(store,'',.1)
            scope.action({'action':'start','mode':'general','auto_drop':True})
            self.assertEqual(store.runs()[0]['auto_drop'],0)
            scope.action({'action':'event','label':'DROP'})
            self.assertIsNone(store.runs()[0]['end'])
            scope.action({'action':'stop'})
            with self.assertRaises(ValueError):scope.action({'action':'weights','run_id':1,'green_weight_g':200,'roasted_weight_g':170})
            scope.action({'action':'start','mode':'coffee'})
            scope.action({'action':'stop'})
            scope.action({'action':'weights','run_id':2,'green_weight_g':200,'roasted_weight_g':170})
            self.assertEqual(store.runs()[0]['weight_loss_pct'],15)
            scope.action({'action':'weights','run_id':2,'green_weight_g':None,'roasted_weight_g':None})
            self.assertIsNone(store.runs()[0]['weight_loss_pct'])
            with store.connect() as db:
                db.execute("INSERT INTO events(run_id,t,label,temperature,source,detected_at) VALUES(2,?,'DROP',202,'auto',?)",(time.time()-10,time.time()))
            scope.action({'action':'undo_drop','run_id':2})
            run=store.runs()[0];self.assertIsNone(run['end']);self.assertEqual(run['auto_drop'],0)
            self.assertFalse(any(e['label']=='DROP' for e in store.events() if e['run_id']==2))

    def test_collector_auto_end_is_atomic_and_single(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(Path(d)/'scope.sqlite3');scope=Scope(store,'',.1)
            scope.action({'action':'start','mode':'coffee'})
            with store.connect() as db:
                db.execute('UPDATE runs SET start=0')
                for i in range(7700,8100):
                    t=i/10;v=202 if t<780 else 25+177*math.exp(-(t-780)/60)
                    row={'t':t,'raw':v,'temperature':v};scope.recent.append(row);scope.check_auto_drop(db,row)
            run=store.runs()[0]
            self.assertIsNotNone(run['end']);self.assertEqual(run['drop_source'],'auto')
            self.assertEqual(len([e for e in store.events() if e['label']=='DROP']),1)
