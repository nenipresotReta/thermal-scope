"""Local constrained identification of an effective thermal balance.

C*dT/dt = P - G*(T-Ta); C,G>0; P,G,Ta constant over the forecast.
T(s)=T0+v0*tau*(1-exp(-s/tau)), tau=C/G, Teq=T0+v0*tau.
This identifies effective probe/filter dynamics, NOT actual bean temperature,
ambient temperature, power or material heat capacity separately. Probe response
is not deconvolved without an independently identified probe model.
"""
import math

VERSION='thermal-balance-v2'
HORIZONS=(5,10,20,30,60,180,300)

def line(xs,ys):
    n=len(xs);mx=sum(xs)/n;my=sum(ys)/n
    variance=sum((x-mx)**2 for x in xs)
    if variance<1e-14:return my,0.
    b=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/variance
    return my-b*mx,b

def reduce(samples,now):
    groups={}
    for r in samples:
        if now-60<=r['t']<=now and math.isfinite(r['temperature']):groups.setdefault(int(r['t']*2),[]).append(r)
    return [(sum(r['t'] for r in g)/len(g),sum(r['temperature'] for r in g)/len(g)) for _,g in sorted(groups.items())]

def predict(samples,now=None,horizon=300):
    offsets=sorted(set(range(0,horizon+1,10 if horizon>60 else 1)) | {horizon} | {h for h in HORIZONS if h<=horizon})
    result={'valid':False,'version':VERSION,'reason':'WAITING FOR DATA','points':[],
            'model':'LOCAL THERMAL BALANCE','target':'smoothed_probe_reading','probe_tau_s':None,
            'assumption':'P, G and ambient temperature constant over the forecast',
            'equation':'C dT/dt = P - G(T - Ta)','tau_s':None,'equilibrium_c':None,
            'identifiable':False,'horizon_s':horizon,'point_step_s':10 if horizon>60 else 1}
    if not samples:return result
    latest=samples[-1];at=latest['t'];now=at if now is None else now
    if now-at>2:return {**result,'reason':'STALE INPUT'}
    data=reduce(samples,at);anchor=latest['temperature']
    if any(b[0]-a[0]>1 for a,b in zip(data,data[1:])):
        # Use only the contiguous segment after the last gap.
        gap=max(i for i in range(1,len(data)) if data[i][0]-data[i-1][0]>1);data=data[gap:]
    recent=[(t-at,y) for t,y in data if t>=at-4]
    duration=data[-1][0]-data[0][0] if data else 0
    if len(recent)<6 or duration<3:
        points=[{'t':at+s,'temperature':anchor,'low':anchor,'high':anchor} for s in offsets]
        return {**result,'valid':True,'reason':'INITIAL STATE · NET HEAT UNKNOWN','points':points,'v0_c_per_s':0.}
    xs,ys=zip(*recent);intercept,v0=line(xs,ys)
    noise=max(.005,math.sqrt(sum((intercept+v0*x-y)**2 for x,y in recent)/len(recent)))
    short=[(t,y) for t,y in recent if t>=-1.5]
    _,short_v=line(*zip(*short)) if len(short)>=3 else (0,v0)
    turning=v0*short_v<0 and abs(short_v)>max(.004,noise/2)
    if turning:v0=short_v
    if abs(v0)<=max(.002,noise/4):
        points=[{'t':at+s,'temperature':anchor,'low':anchor-noise,'high':anchor+noise} for s in offsets]
        return {**result,'valid':True,'reason':'NEAR EQUILIBRIUM · PARAMETERS UNIDENTIFIED','points':points,'v0_c_per_s':0.,'fit_rmse_c':noise}
    sign=1 if v0>0 else -1
    # Cut history at the latest sustained opposite movement. A previous cooling
    # episode must not determine the equilibrium for a new warming episode.
    start=0
    for i in range(len(data)-1,3,-1):
        if at-data[i][0]<3:continue
        if sign*(data[i][1]-data[i-4][1]) < -max(.03,noise*3):
            start=i;break
    data=data[start:];fit_duration=data[-1][0]-data[0][0]
    xs=[t-at for t,y in data];ys=[y-anchor for t,y in data]
    models=[]
    # Profile tau over a positive range. No arbitrary stock-cycle regression,
    # no independent horizon predictions, and no future reversal is possible.
    for i in range(261):
        tau=2*math.exp(i/260*math.log(3600/2))
        basis=[-tau*math.expm1(-x/tau) for x in xs]
        weights=[math.exp(x/20) for x in xs]
        denominator=sum(w*f*f for w,f in zip(weights,basis))
        if denominator<1e-12:continue
        v=sum(w*f*y for w,f,y in zip(weights,basis,ys))/denominator
        # Anchor the inferred net heat to the current observed slope direction.
        if v*sign<=0 or not .5*abs(v0)<=abs(v)<=2*abs(v0):continue
        equilibrium=anchor+v*tau
        if not -100<=equilibrium<=850:continue
        mse=sum(w*(v*f-y)**2 for w,f,y in zip(weights,basis,ys))/sum(weights)
        models.append((mse,tau,v,equilibrium))
    if not models:
        if anchor+v0*horizon < -273.15:
            return {**result,'reason':'TRANSIENT · NO PHYSICAL LONG-HORIZON FIT'}
        # G/C→0 is the constant-net-heat limit of the same balance equation.
        points=[{'t':at+s,'temperature':anchor+v0*s,'low':anchor+v0*s-noise*(1+s/4),'high':anchor+v0*s+noise*(1+s/4)} for s in offsets]
        return {**result,'valid':True,'reason':'NET-HEAT LIMIT · TIME CONSTANT UNRESOLVED','points':points,'v0_c_per_s':v0,'fit_rmse_c':noise}
    mse,tau,v,equilibrium=min(models);rmse=math.sqrt(mse)
    near=[m for m in models if m[0]<=mse+max(noise**2,.0001,mse*.15)]
    lo=min(m[1] for m in near);hi=max(m[1] for m in near)
    acceleration=v0*latest.get('d2',0)>max(.00001,abs(v0)*.002)
    identifiable=fit_duration>=10 and hi/lo<3 and 2.01<tau<3599 and rmse<max(.05,abs(v0)*fit_duration*.05) and not acceleration and not turning
    points=[]
    for s in offsets:
        value=anchor-v*tau*math.expm1(-s/tau)
        ensemble=[anchor-vv*tt*math.expm1(-s/tt) for _,tt,vv,_ in near]
        error=max(noise,rmse)*(1+s/max(4,fit_duration))
        points.append({'t':at+s,'temperature':value,'low':min(ensemble)-error,'high':max(ensemble)+error})
    reason='PARAMETERS IDENTIFIED' if identifiable else 'TRANSIENT · SINGLE-NODE MISMATCH' if acceleration or turning else 'PARAMETERS UNCERTAIN'
    return {**result,'valid':True,'reason':reason,'identifiable':identifiable,'points':points,
            'tau_s':tau,'tau_range_s':[lo,hi],'equilibrium_c':equilibrium,'v0_c_per_s':v,
            'fit_rmse_c':rmse,'fit_window_s':fit_duration,
            'parameter_note':'Effective response includes unseparated probe and filter lag'}
