"""Fit a probe's first-order step response in one specific medium.
Only valid for a well mixed, approximately constant-temperature bath/air flow.
Not a temperature offset/gain calibration and not a whole-roaster model.
"""
import math
from thermal_model import line

def fit_step(rows):
    fail=lambda reason:{'valid':False,'reason':reason}
    if len(rows)<100:return fail('Need at least 10 seconds of data')
    data=rows[::max(1,len(rows)//1500)]
    if data[-1]['t']-data[0]['t']<10:return fail('Need at least 10 seconds of data')
    if any(b['t']-a['t']>1 for a,b in zip(data,data[1:])):return fail('Data gap: repeat the calibration')
    base=sum(r['raw'] for r in data[:3])/3
    total=data[-1]['raw']-base
    if abs(total)<5:return fail('Need a step of at least 5 °C')
    direction=1 if total>0 else -1
    threshold=max(.15,abs(total)*.015)
    index=next((i for i,r in enumerate(data) if direction*(r['raw']-base)>threshold),None)
    if index is None:return fail('No temperature step detected')
    # Include one sample before movement; free amplitude absorbs modest click/transfer delay.
    data=data[max(0,index-1):];t0=data[0]['t'];xs=[r['t']-t0 for r in data];ys=[r['raw'] for r in data]
    if xs[-1]<8:return fail('Keep collecting after the temperature step')
    models=[]
    for i in range(601):
        tau=.15*math.exp(i/600*math.log(600/.15));ex=[math.exp(-x/tau) for x in xs];a,b=line(ex,ys)
        if not -40<a<200 or b*direction>=0:continue
        mse=sum((a+b*z-y)**2 for z,y in zip(ex,ys))/len(xs)
        models.append((mse,tau,a,b))
    if not models:return fail('No physical first-order response found')
    mse,tau,a,b=min(models);rmse=math.sqrt(mse);swing=abs(ys[-1]-ys[0])
    if xs[-1]<3*tau:return fail('Not settled: collect for at least 3× the fitted time constant')
    if tau<=.3:return fail('Response too fast to identify reliably at 10 Hz')
    if rmse>max(.12,swing*.015):return fail('Response is not a clean step: keep the bath well mixed and stable')
    near=[m for m in models if m[0]<=mse+max(.0004,mse*.15)]
    lo,hi=min(m[1] for m in near),max(m[1] for m in near)
    if hi/lo>1.8:return fail('Time constant is uncertain: repeat with a larger temperature step')
    return {'valid':True,'tau_s':round(tau,3),'tau_range_s':[round(lo,3),round(hi,3)],'rmse_c':round(rmse,4),'equilibrium_c':round(a,3),'duration_s':round(xs[-1],1),'step_c':round(swing,2),'reason':'Effective response in this medium; constant bath assumed'}
