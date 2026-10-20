"""Thermal parameter identification and frozen out-of-time forecast scoring.
The old unconstrained lag-regression implementation is archived, not loaded.
"""
import json,math
from thermal_model import predict,HORIZONS,VERSION

def forecast(models,rows):return predict(rows)

class Ledger:
    def __init__(self,source=''):
        self.source=source
        self.last_created=0;self.previous=None;self.last_forecast=predict([])
    def tick(self,db,row,recent,models=None):
        previous=self.previous;self.previous=row
        if previous and 0<row['t']-previous['t']<=.5:
            due=db.execute('SELECT id,target FROM forecasts WHERE actual IS NULL AND source=? AND target BETWEEN ? AND ?',(self.source,previous['t'],row['t'])).fetchall()
            for pending in due:
                alpha=(pending['target']-previous['t'])/(row['t']-previous['t'])
                actual=previous['temperature']*(1-alpha)+row['temperature']*alpha
                db.execute('UPDATE forecasts SET actual=? WHERE id=?',(actual,pending['id']))
        elapsed=row['t']-self.last_created
        short=[r for r in recent if r['t']>=row['t']-1.5]
        movement=short[-1]['temperature']-short[0]['temperature'] if len(short)>2 else 0
        reversal=movement*self.last_forecast.get('v0_c_per_s',0)<0 and abs(movement)>.03
        # Re-identify promptly after an observed direction change. Old frozen
        # forecasts remain scored; they are never silently rewritten.
        if elapsed<5 and not (elapsed>=1 and reversal):return False
        self.last_created=row['t'];model=predict(recent);self.last_forecast=model
        if not model['valid']:return True
        snapshot={k:v for k,v in model.items() if k!='points'}
        for h in HORIZONS:
            value=next(p['temperature'] for p in model['points'] if abs(p['t']-row['t']-h)<.001)
            db.execute('INSERT INTO forecasts(created,target,horizon,features,baseline,linear,predicted,version,model_snapshot,trainable,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
              (row['t'],row['t']+h,h,json.dumps({'T0':row['temperature'],'v0':model.get('v0_c_per_s')}),row['temperature'],row['temperature']+h*row['d1'],value,VERSION,json.dumps(snapshot),0,self.source))
        return True
