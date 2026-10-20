'use strict';
const $=id=>document.getElementById(id), canvas=$('plot'), ctx=canvas.getContext('2d');
let points=[], events=[], runs=[], active=null, viewed=null, latest=null, status={}, live=true, end=Date.now()/1000, span=600, hover=null, drag=null, historyToken=0, reconnect=false, receivedAt=0, total=0, rateStart=Date.now(), measuredRate=0, lastRecordRefresh=0, prediction={valid:false,reason:"LEARNING"}, minuteUnits=localStorage.getItem("derivativeUnits")==="min", calibrations=[], plotRange={min:0,max:250};
const nice=v=>v===0?'0':Math.abs(v)<1?v.toFixed(2):Math.abs(v)<10?v.toFixed(1):v.toFixed(0);
const clock=s=>{s=Math.max(0,Math.floor(s));return (s>=3600?Math.floor(s/3600)+':':'')+String(Math.floor(s/60)%60).padStart(2,'0')+':'+String(s%60).padStart(2,'0');};
const futureSpace=()=>Math.min(prediction.horizon_s||300,span*.5);
const num=(v,n)=>Number.isFinite(v)?v.toFixed(n):'—';
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').hidden=true,4500);}
async function api(path,options){const response=await fetch(path,options);const data=await response.json();if(!response.ok)throw Error(data.error||'Request failed');return data;}
async function action(action,extra={}){try{const result=await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,...extra})});records(result);return true;}catch(e){toast(e.message);return false;}}
function fitRecording(run){const range=recordingWindow(run,Date.now()/1000);span=range.span;end=range.end;}
function syncLiveWindow(){if(active&&live&&!viewed)fitRecording(active);else if(live&&!viewed)end=(latest?.t||Date.now()/1000)+futureSpace();}
function records(data){
 const previous=active;runs=data.runs;events=data.events;active=runs.find(r=>r.end===null)||null;
 if(viewed)viewed=runs.find(r=>r.id===viewed.id)||viewed;
 if(previous&&!active){viewed=runs.find(r=>r.id===previous.id)||previous;live=false;fitRecording(viewed);history();if(viewed.drop_source==='auto')toast('DROP confirmed · marked retrospectively. Undo is available in Archive.');}
 else if(active&&previous?.id!==active.id){viewed=null;live=true;fitRecording(active);history();}
 updateRecords();
}
function updateRecords(){
 $('start').disabled=!!active;$('stop').disabled=!active;$('recLight').textContent=active?'● REC':'○ IDLE';$('recLight').classList.toggle('active',!!active);
 const run=viewed||active;const mode=run?.mode||$('recordingMode').value;
 if(active&&!viewed)$('recordingMode').value=active.mode;
 $('recordingMode').disabled=!!active;
 document.querySelectorAll('[data-event],#customEvent,#undo').forEach(b=>b.disabled=!active||!!viewed);
 document.querySelectorAll('[data-event]').forEach(b=>b.hidden=mode!=='coffee');
 $('autoDropControl').hidden=mode!=='coffee';$('developmentBlock').hidden=mode!=='coffee';document.querySelector('.weight-readout').hidden=mode!=='coffee';
 if(run)$('autoDrop').checked=!!run.auto_drop;
 $('autoDrop').disabled=!!viewed;
 const pending=active?.auto_drop&&status.drop_detection&&!viewed?status.drop_detection:null;
 $('autoDropNote').textContent=mode!=='coffee'?'Manual events only · no automatic detection':pending?'DROP CANDIDATE · verifying '+Math.max(0,Math.ceil(pending.confirm_at-Date.now()/1000))+' s':run&&!run.auto_drop?'AUTO DROP OFF':run?.drop_source==='auto'?'DROP CONFIRMED · RETROSPECTIVE':run?.end?'RECORDING COMPLETE':'Sustained cooling · 20 s confirmation';
 $('dismissDrop').hidden=!pending;
 const list=run?events.filter(e=>e.run_id===run.id):[];
 $('events').replaceChildren();
 if(!list.length){const node=document.createElement('span');node.className='muted';node.textContent=run?'No events marked.':'Start a recording to mark events.';$('events').append(node);}
 list.forEach(e=>{const node=document.createElement('span');node.className='event-chip';const t=document.createElement('b');t.textContent=clock(e.t-run.start);node.append(t,document.createTextNode(e.label+(e.source==='auto'?' · AUTO':'')+' / '+num(e.temperature,1)+'°'));$('events').append(node);});
 const development=developmentMetrics(run,Date.now()/1000);
 $('development').textContent=development?clock(development.seconds):'—';
 $('developmentRatio').textContent=development?development.percent.toFixed(1)+'%'+(development.live?' · LIVE':' · FINAL'):'WAITING FOR FC START';
 $('weightLoss').textContent=run?.weight_loss_pct!==null&&run?.weight_loss_pct!==undefined?run.weight_loss_pct.toFixed(2)+'%':'—';
 $('weightButton').hidden=!(run?.end&&mode==='coffee');$('weightButton').textContent=run?.green_weight_g?'EDIT WEIGHTS':'ADD WEIGHTS';
 $('modeNote').textContent=mode==='coffee'?'Coffee · development ratio uses recording start':'General · manual events only';
 $('timer').textContent=run?clock((run.end||Date.now()/1000)-run.start):'00:00';
 $('source').textContent=viewed?'ARCHIVED INPUT':'LIVE INPUT';
 syncLiveWindow();$('timeDiv').disabled=!!active&&live&&!viewed;
}
async function history(targetEnd=end){
 const token=++historyToken;
 try{const start=targetEnd-Math.max(span*2,600);const result=await api('/api/history?start='+start+'&end='+(targetEnd+.1));if(token!==historyToken)return;
  // SSE may arrive during the request: retain newer samples without duplicating timestamps.
  const lastSaved=result.samples.at(-1)?.t||start;const tail=points.filter(p=>p.t>lastSaved&&p.t>=start);points=[...result.samples,...tail];
  const ids=new Set(result.events.map(e=>e.id));events=[...result.events,...events.filter(e=>!ids.has(e.id)&&e.t>targetEnd+.1)];updateRecords();
 }catch(e){toast('History: '+e.message);}
}
function refreshReading(){
 const stale=!latest||!status.connected||Date.now()/1000-latest.t>2;
 document.body.classList.toggle('stale',stale&&!viewed);
 const reading=viewed?(points.filter(p=>p.t>=viewed.start&&p.t<=viewed.end).at(-1)||null):latest;
 $('temp').textContent=num(reading?.temperature,1);$('raw').textContent='RAW '+num(reading?.raw,2)+' °C';$('d1').textContent=num(reading?.d1*(minuteUnits?60:1),minuteUnits?2:3);$('d2').textContent=num(reading?.d2*(minuteUnits?3600:1),minuteUnits?2:4);
 $('d1Unit').textContent=minuteUnits?'°C/min':'°C/s';$('d2Unit').textContent=minuteUnits?'°C/min²':'°C/s²';$('derivativeUnits').textContent=minuteUnits?'/min ⇄ /s':'/s ⇄ /min';
 $('direction').textContent=!reading?'WAITING FOR SENSOR':Math.abs(reading.d1)<.003?'→ STEADY':reading.d1>0?'↗ RISING':'↘ FALLING';
 $('connection').textContent=stale?'STALE / OFFLINE':'CONNECTED';$('connection').className='connection '+(stale?'bad':'ok');
 $('latency').textContent=num(status.latency_ms,0)+' ms';$('rate').textContent=measuredRate?measuredRate.toFixed(1)+' Hz RECEIVED':'10 Hz TARGET';
 $('statusNote').textContent=stale?(status.message==='Live'?'Input is stale':status.message||'Reconnecting'):'Continuous acquisition · Persistent history';
 $('modelState').textContent='THERMAL · '+(prediction.reason||'WAITING');$('modelParams').textContent=prediction.identifiable?'τ '+num(prediction.tau_s,1)+' s · Teq '+num(prediction.equilibrium_c,1)+' °C · 5 min / CONSTANT P / G / Ta':'τ / Teq UNRESOLVED · 5 min / CONSTANT P / G / Ta';
 $('viewLabel').textContent=viewed?'ARCHIVE':live?'LIVE':'HOLD';$('hold').classList.toggle('selected',!live&&!viewed);$('live').classList.toggle('selected',live&&!viewed);$('hold').textContent=live?'Ⅱ HOLD':'▶ RUN';
 const div=span/10;let custom=$('timeDiv').querySelector('[data-custom]');if(!Array.from($('timeDiv').options).some(o=>!o.dataset.custom&&Math.abs(Number(o.value)-div)<.001)){if(!custom){custom=document.createElement('option');custom.dataset.custom='1';$('timeDiv').append(custom);}custom.value=String(div);custom.textContent=div<60?div.toFixed(1)+' s':(div/60).toFixed(1)+' min';$('timeDiv').value=custom.value;}else $('timeDiv').value=String(div);
 $('windowLabel').textContent=(span>=60?(span/60).toFixed(span%60?1:0)+' min':nice(span)+' s')+' WINDOW';
}
function startStream(){
 const stream=new EventSource('/api/stream');
 stream.addEventListener('status',e=>{const oldHost=status.host;status=JSON.parse(e.data);if(oldHost&&oldHost!==status.host){latest=null;points=[];measuredRate=0;}prediction=status.prediction||prediction;if(status.latest&&!latest)latest=status.latest;refreshReading();});
 stream.addEventListener('sample',e=>{const p=JSON.parse(e.data);if(latest&&p.t<latest.t)return;latest=p;status.connected=true;status.message='Live';points.push(p);total++;receivedAt=Date.now();
  if(points.length>220000)points.splice(0,points.length-216000);
  if(Date.now()-rateStart>=5000){measuredRate=total/((Date.now()-rateStart)/1000);total=0;rateStart=Date.now();}
  syncLiveWindow();
  if(reconnect){reconnect=false;history();}
 });
 stream.addEventListener('learning',e=>showLearning(JSON.parse(e.data)));
 stream.addEventListener('prediction',e=>{prediction=JSON.parse(e.data);});
 stream.addEventListener('calibration',e=>{calibrations=JSON.parse(e.data);showCalibration();});
 stream.addEventListener('records',e=>records(JSON.parse(e.data)));
 stream.addEventListener('drop_detection',e=>{status.drop_detection=JSON.parse(e.data);updateRecords();});
 stream.onerror=()=>{status.connected=false;status.message='Server connection lost';reconnect=true;refreshReading();};
}
function ask(title,initial){return new Promise(resolve=>{const dialog=$('inputDialog');$('inputTitle').textContent=title;$('inputText').value=initial;dialog.returnValue='';dialog.onclose=()=>resolve(dialog.returnValue==='ok'?$('inputText').value.trim():null);dialog.showModal();$('inputText').focus();$('inputText').select();});}
$('derivativeUnits').onclick=()=>{minuteUnits=!minuteUnits;localStorage.setItem('derivativeUnits',minuteUnits?'min':'s');refreshReading();};
$('start').onclick=async()=>{const mode=$('recordingMode').value;const name=await ask(mode==='coffee'?'New coffee recording':'New general recording',(mode==='coffee'?'Roast ':'Session ')+new Date().toLocaleString('en-GB',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}));if(name)await action('start',{name,mode,auto_drop:$('autoDrop').checked});};
$('recordingMode').onchange=updateRecords;
$('autoDrop').onchange=()=>{if(active)action('auto_drop',{enabled:$('autoDrop').checked});};
$('dismissDrop').onclick=()=>action('auto_drop',{enabled:false});
$('stop').onclick=()=>action('stop');document.querySelectorAll('[data-event]').forEach(b=>b.onclick=()=>action('event',{label:b.dataset.event}));
$('customEvent').onclick=async()=>{const label=await ask('Mark an event','');if(label)await action('event',{label});};$('undo').onclick=()=>action('undo');
$('hold').onclick=()=>{if(viewed){viewed=null;live=true;history(Date.now()/1000);}else live=!live;refreshReading();};
function goLive(){viewed=null;live=true;syncLiveWindow();history();updateRecords();refreshReading();}
$('live').onclick=goLive;$('backLive').onclick=()=>{$('archive').close();goLive();};
$('timeDiv').onchange=()=>{span=Number($('timeDiv').value)*10;if(live)end=(latest?.t||Date.now()/1000)+futureSpace();history();refreshReading();};
$('tempDiv').onchange=()=>{$('offset').disabled=true;};$('offset').disabled=true;
async function showArchive(){
 try{
  runs=await api('/api/runs');$('runList').replaceChildren();
  if(!runs.length)$('runList').textContent='No recordings yet. Live history is still being saved.';
  runs.forEach(run=>{
   const row=document.createElement('div');row.className='run';const text=document.createElement('div'),name=document.createElement('strong'),info=document.createElement('small');
   name.textContent=run.name;
   let description=new Date(run.start*1000).toLocaleString('en-GB')+' · '+(run.mode==='general'?'GENERAL':'COFFEE')+' · '+clock((run.end||Date.now()/1000)-run.start)+(run.end?'':' · REC');
   const dev=developmentMetrics(run,Date.now()/1000);if(dev)description+=' · DEV '+clock(dev.seconds)+' / '+dev.percent.toFixed(1)+'%';
   if(run.weight_loss_pct!==null)description+=' · LOSS '+run.weight_loss_pct.toFixed(2)+'%';
   if(run.drop_source==='auto')description+=' · AUTO DROP';
   info.textContent=description;text.append(name,info);
   const actions=document.createElement('div');actions.className='run-actions';const button=document.createElement('button'),link=document.createElement('a');
   button.textContent='VIEW';button.onclick=()=>{viewed=run;live=false;fitRecording(run);history(end);$('archive').close();updateRecords();refreshReading();};
   link.textContent='CSV ↓';link.href='/api/export?run='+run.id;link.download='thermal-scope-'+run.id+'.csv';actions.append(button,link);
   if(run.mode==='coffee'&&run.end){const weight=document.createElement('button');weight.textContent=run.green_weight_g?'EDIT WEIGHTS':'ADD WEIGHTS';weight.onclick=()=>openWeights(run);actions.append(weight);}
   if(run.drop_source==='auto'&&run.end&&!active&&run.id===runs[0]?.id){const undo=document.createElement('button');undo.textContent='UNDO AUTO DROP';undo.onclick=async()=>{if(await action('undo_drop',{run_id:run.id})){viewed=null;live=true;syncLiveWindow();history();$('archive').close();toast('Recording reopened; automatic DROP disabled for this run.');}};actions.append(undo);}
   row.append(text,actions);$('runList').append(row);
  });if(!$('archive').open)$('archive').showModal();
 }catch(e){toast(e.message);}
}
$('historyButton').onclick=showArchive;
let weightRun=null;
function openWeights(run){weightRun=run;$('weightRunName').textContent=run.name;$('greenWeight').value=run.green_weight_g??'';$('roastedWeight').value=run.roasted_weight_g??'';$('weightError').textContent='';previewWeights();$('weightDialog').showModal();}
function previewWeights(){const before=Number($('greenWeight').value),after=Number($('roastedWeight').value);$('weightPreview').textContent=before>0&&after>0&&after<=before?((before-after)/before*100).toFixed(2)+'% / '+(before-after).toFixed(2)+' g LOST':'(Before − After) / Before × 100%';}
async function saveWeights(clear=false){
 try{const data=await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'weights',run_id:weightRun.id,green_weight_g:clear?null:Number($('greenWeight').value),roasted_weight_g:clear?null:Number($('roastedWeight').value)})});records(data);$('weightDialog').close();if($('archive').open)showArchive();toast(clear?'Weights cleared.':'Weights saved.');}catch(e){$('weightError').textContent=e.message;}
}
$('weightButton').onclick=()=>openWeights(viewed||active);
$('closeWeights').onclick=()=>$('weightDialog').close();$('weightForm').onsubmit=e=>{e.preventDefault();saveWeights();};$('clearWeights').onclick=()=>saveWeights(true);$('greenWeight').oninput=previewWeights;$('roastedWeight').oninput=previewWeights;
$('closeArchive').onclick=()=>$('archive').close();
function render(){
 const rect=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1,w=rect.width,h=rect.height;
 if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}
 ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
 const left=58,right=22,top=25,bottom=35,pw=w-left-right,ph=h-top-bottom,start=end-span;
 const shownRun=viewed||active;
 const visible=points.filter(p=>p.t>=Math.max(start,shownRun?.start??start)&&p.t<=Math.min(end,shownRun?.end??end));
 $('plotEmpty').hidden=visible.length>0;
 let min=0,max=250;
 if($('tempDiv').value==='auto'){
  if(visible.length){min=Infinity;max=-Infinity;for(const p of visible){min=Math.min(min,p.low??p.temperature);max=Math.max(max,p.high??p.temperature);}const pad=Math.max(.5,(max-min)*.2);min-=pad;max+=pad;const rawStep=(max-min)/5,base=10**Math.floor(Math.log10(rawStep));const step=[1,2,2.5,5,10].find(v=>v*base>=rawStep)*base;const mid=(max+min)/2;min=Math.floor((mid-2.5*step)/step)*step;max=min+5*step;if(visible.some(p=>(p.high??p.temperature)>max)){min+=step;max+=step;}}
 }else if($('tempDiv').value!=='roast'){min=0;max=Number($('tempDiv').value)*5;}
 $('offset').value=min.toFixed(3);plotRange={min,max};
 const x=t=>left+(t-start)/span*pw,y=t=>top+(max-t)/(max-min)*ph;
 ctx.font='10px monospace';ctx.lineWidth=1;ctx.textBaseline='middle';
 const axisRun=viewed||active;
 const ticks=axisRun?recordingTicks(start,end,axisRun.start):Array.from({length:11},(_,i)=>start+i*span/10);
 ticks.forEach((t,i)=>{const xx=x(t);ctx.strokeStyle=i===0?'#bbbdb2':'#e0e0d6';ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,h-bottom);ctx.stroke();ctx.fillStyle='#7d8175';ctx.textAlign='center';if(axisRun||i%2===0){const label=axisRun?(t<axisRun.start?'−':'')+clock(Math.abs(t-axisRun.start)):new Date(t*1000).toLocaleTimeString('en-GB',{hour12:false});ctx.fillText(label,xx,h-14);}});

 for(let i=0;i<=5;i++){const yy=top+i*ph/5;ctx.strokeStyle='#d9dbd0';ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(w-right,yy);ctx.stroke();ctx.fillStyle='#7d8175';ctx.textAlign='right';ctx.fillText((max-i*(max-min)/5).toFixed(Math.max(0,-Math.floor(Math.log10((max-min)/5)))),left-10,yy);}
 ctx.strokeStyle='#999d91';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(left,top);ctx.lineTo(left,h-bottom);ctx.lineTo(w-right,h-bottom);ctx.stroke();ctx.fillStyle='#70776a';ctx.font='10px monospace';ctx.textAlign='right';ctx.fillText('°C',left-10,top-12);ctx.textAlign='left';
 for(let i=0;i<=50;i++){const xx=left+i*pw/50,yy=top+i*ph/50;ctx.beginPath();ctx.moveTo(xx,h-bottom);ctx.lineTo(xx,h-bottom-(i%5===0?7:3));ctx.moveTo(left,yy);ctx.lineTo(left+(i%10===0?7:3),yy);ctx.stroke();}
 ctx.save();ctx.beginPath();ctx.rect(left,top,pw,ph);ctx.clip();
 ctx.strokeStyle='#c44d31';ctx.lineWidth=2;ctx.beginPath();let previous=null;
 for(const p of visible){if(previous&&p.t-previous.t<Math.max(2,p.high!==undefined&&previous.high!==undefined?span/9000*2.5:2))ctx.lineTo(x(p.t),y(p.temperature));else ctx.moveTo(x(p.t),y(p.temperature));previous=p;}ctx.stroke();
 // On wide views, show bucket min/max as a thin envelope, retaining short peaks.
 ctx.globalAlpha=.25;ctx.lineWidth=1;ctx.beginPath();for(const p of visible){if(p.high>p.low){ctx.moveTo(x(p.t),y(p.low));ctx.lineTo(x(p.t),y(p.high));}}ctx.stroke();ctx.globalAlpha=1;
 const run=viewed||active;
 const inWindow=events.filter(e=>e.t>=start&&e.t<=end&&(!run||e.run_id===run.id));
 inWindow.forEach((e,i)=>{const xx=x(e.t);const ey=y(e.temperature??min),ly=Math.max(top+18,Math.min(h-bottom-25,ey-25-(i%3)*18));ctx.strokeStyle='#999b90';ctx.lineWidth=.8;ctx.beginPath();ctx.moveTo(xx,ey);ctx.lineTo(xx+12,ly);ctx.stroke();ctx.font='10px monospace';const tw=ctx.measureText(e.label).width;ctx.fillStyle='#f8f6f0e8';ctx.fillRect(xx+13,ly-8,tw+8,16);ctx.fillStyle='#4e5348';ctx.textAlign='left';ctx.fillText(e.label,xx+17,ly);});
 const last=visible.at(-1);
 if(last){
  const xx=x(last.t),yy=y(last.temperature);
  // A quiet live time guide; measured and future regions remain distinct.
  if(live&&!viewed){ctx.fillStyle='#e2e0d62a';ctx.fillRect(xx,top,w-right-xx,ph);ctx.strokeStyle='#b6b9ad';ctx.setLineDash([2,5]);ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,h-bottom);ctx.stroke();ctx.setLineDash([]);}
  ctx.fillStyle='#c44d31';ctx.beginPath();ctx.arc(xx,yy,2.5,0,Math.PI*2);ctx.fill();
  if($('prediction').checked&&prediction.valid&&live&&!viewed&&Date.now()/1000-last.t<2){
   const pp=prediction.points;
   ctx.fillStyle='#c44d3112';ctx.beginPath();pp.forEach((p,i)=>i?ctx.lineTo(x(p.t),y(p.low)):ctx.moveTo(x(p.t),y(p.low)));[...pp].reverse().forEach(p=>ctx.lineTo(x(p.t),y(p.high)));ctx.closePath();ctx.fill();
   ctx.strokeStyle='#c44d31';ctx.globalAlpha=.55;ctx.setLineDash([6,5]);ctx.lineWidth=2;ctx.beginPath();pp.forEach((p,i)=>i?ctx.lineTo(x(p.t),y(p.temperature)):ctx.moveTo(x(p.t),y(p.temperature)));ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;
  }
 }
 if(hover&&!drag){const t=start+(hover.x-left)/pw*span;let found=null,d=Infinity;for(const p of visible){if(Math.abs(p.t-t)<d){found=p;d=Math.abs(p.t-t);}}
  if(found&&hover.x>=left&&hover.x<=w-right){ctx.strokeStyle='#9b9f94';ctx.setLineDash([2,4]);ctx.beginPath();ctx.moveTo(x(found.t),top);ctx.lineTo(x(found.t),h-bottom);ctx.stroke();ctx.setLineDash([]);$('tooltip').hidden=false;$('tooltip').textContent=new Date(found.t*1000).toLocaleTimeString('en-GB')+' / '+num(found.temperature,2)+' °C';$('tooltip').style.left=Math.min(w-225,Math.max(60,hover.x+12))+'px';}else $('tooltip').hidden=true;
 }else $('tooltip').hidden=true;
 ctx.restore();
}
canvas.onpointerdown=e=>{canvas.setPointerCapture(e.pointerId);drag={x:e.clientX,end};live=false;refreshReading();};
canvas.onpointermove=e=>{const r=canvas.getBoundingClientRect();hover={x:e.clientX-r.left,y:e.clientY-r.top};if(drag){end=drag.end-(e.clientX-drag.x)/(r.width-80)*span;}};
canvas.onpointerup=e=>{if(!drag)return;drag=null;history();};canvas.onpointercancel=()=>{drag=null;};canvas.onpointerleave=()=>hover=null;
canvas.addEventListener('wheel',e=>{
 e.preventDefault();const r=canvas.getBoundingClientRect();
 if(live&&!viewed){
  const next=temperatureZoom(plotRange.min,plotRange.max,(e.clientY-r.top-25)/(r.height-60),e.deltaY);
  let option=$('tempDiv').querySelector('[data-custom]');
  if(!option){option=document.createElement('option');option.dataset.custom='1';$('tempDiv').append(option);}
  option.value=String(next.division);option.textContent=next.division.toFixed(next.division<1?3:2)+' CUSTOM';$('tempDiv').value=option.value;
  $('offset').value='0';$('offset').disabled=true;plotRange={min:next.min,max:next.max};
  // LIVE stays LIVE. The horizontal duration and data stream are untouched.
 }else{
  const anchor=Math.max(0,Math.min(1,(e.clientX-r.left-58)/(r.width-80))),time=end-span+anchor*span;
  span=Math.max(5,Math.min(86400,span*Math.exp(e.deltaY*.002)));end=time+(1-anchor)*span;
  live=false;clearTimeout(canvas.zoomTimer);canvas.zoomTimer=setTimeout(()=>history(),180);
 }
 refreshReading();
},{passive:false});
let lastFrame=0;function frame(now){if(now-lastFrame>32){render();lastFrame=now;}requestAnimationFrame(frame);}requestAnimationFrame(frame);
setInterval(()=>{refreshReading();updateRecords();if(Date.now()-lastRecordRefresh>10000){lastRecordRefresh=Date.now();api('/api/status').then(s=>status=s).catch(()=>{});}},500);
(async()=>{try{const [s,r,e]=await Promise.all([api('/api/status'),api('/api/runs'),api('/api/events')]);status=s;latest=s.latest;records({runs:r,events:e});syncLiveWindow();await history();}catch(e){toast(e.message);}startStream();})();

function showCalibration(){
 const running=calibrations.find(c=>!c.end);$('calibrationStart').disabled=!!running;$('calibrationMedium').disabled=!!running;$('calibrationFinish').disabled=!running;$('calibrationCancel').disabled=!running;
 $('calibrationStatus').textContent=running?running.medium+' STEP · '+clock(Date.now()/1000-running.start)+' · Finish after settling.':'No calibration running.';
 $('calibrationResults').replaceChildren();
 calibrations.filter(c=>c.result?.valid).forEach(c=>{const row=document.createElement('div');row.className='calibration-result';row.textContent=c.medium+' / τ '+c.result.tau_s+' s / RMSE '+c.result.rmse_c+' °C / '+new Date(c.start*1000).toLocaleString('en-GB');$('calibrationResults').append(row);});
}
async function calibrationAction(action){try{calibrations=await api('/api/calibration',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,medium:$('calibrationMedium').value})});showCalibration();}catch(e){toast(e.message);}}
$('calibrateButton').onclick=async()=>{try{calibrations=await api('/api/calibrations');showCalibration();$('calibrateDialog').showModal();}catch(e){toast(e.message);}};
$('closeCalibrate').onclick=()=>$('calibrateDialog').close();$('calibrationStart').onclick=()=>calibrationAction('start');$('calibrationFinish').onclick=()=>calibrationAction('finish');$('calibrationCancel').onclick=()=>calibrationAction('cancel');setInterval(()=>{if($('calibrateDialog').open)showCalibration();},1000);

let liveScores=[];
function showLearning(models){
 $('learningMetrics').replaceChildren();
 for(const h of ['30','60','180','300']){
  const m=models[h]||{},node=document.createElement('div'),title=document.createElement('b'),content=document.createElement('span'),state=document.createElement('small'),measured=document.createElement('small');
  title.textContent=Number(h)>=60?'+'+(Number(h)/60)+' min':'+'+h+' s';
  const future=prediction.points?.find(p=>Math.abs(p.t-(prediction.points[0].t+Number(h)))<.01);
  content.textContent=future?num(future.temperature,2)+' °C':'WAITING';
  state.textContent=m.valid?'THERMAL PARAMETERS IDENTIFIED':m.reason||'IDENTIFYING PARAMETERS';
  const score=liveScores.find(s=>s.horizon===Number(h));
  measured.textContent=score?'MAE '+score.mae_c.toFixed(3)+' °C / '+score.n+' scored':'AWAITING LATER MEASUREMENTS';
  node.append(title,content,state,measured);$('learningMetrics').append(node);
 }
}
api('/api/status').then(s=>showLearning(s.learning||{})).catch(()=>{});

async function updateLearning(){try{const data=await api('/api/learning');liveScores=data.live_scores;showLearning(data.models);}catch{}}updateLearning();setInterval(updateLearning,30000);

let discoveryPoll=null;
async function openDevice(){
 try{
  const d=await api('/api/device');
  $('deviceCurrent').textContent=d.host?(d.connected?'CONNECTED / ':'SELECTED / ')+d.host:'No device selected. Connect a thermometer to begin.';
  $('deviceHost').value=d.host||'';
  if(!$('deviceNetwork').value)$('deviceNetwork').value=d.networks[0]||'';
  $('deviceDialog').showModal();
 }catch(e){toast(e.message);}
}
async function deviceAction(action){
 const host=$('deviceHost').value.trim();$('testDevice').disabled=true;$('connectDevice').disabled=true;
 $('deviceTest').textContent=(action==='test'?'Testing ':'Connecting to ')+host+'…';
 try{
  const result=await api('/api/device',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,host})});
  $('deviceTest').textContent=result.host+' / '+result.status+(result.temperature_c!==null?' / '+num(result.temperature_c,2)+' °C':'')+(result.saved?' / SAVED':'');
  if(result.saved){$('deviceCurrent').textContent='SELECTED / '+result.host;toast('Device saved. Connecting…');}
 }catch(e){$('deviceTest').textContent=e.message;}
 finally{$('testDevice').disabled=false;$('connectDevice').disabled=false;}
}
function showDiscovery(scan){
 $('discoverDevices').disabled=scan.running;
 $('discoveryProgress').textContent=(scan.running?'SEARCHING / ':'FINISHED / ')+scan.checked+' of '+scan.total+' / '+scan.devices.length+' found'+(scan.error?' / '+scan.error:'');
 $('discoveredDevices').replaceChildren();
 for(const device of scan.devices){
  const row=document.createElement('div');row.className='discovered-device';const text=document.createElement('span'),button=document.createElement('button');
  text.textContent=device.host+' / '+device.status+(device.temperature_c!==null?' / '+num(device.temperature_c,1)+' °C':'');button.textContent='USE DEVICE';
  button.onclick=()=>{$('deviceHost').value=device.host;deviceAction('connect');};row.append(text,button);$('discoveredDevices').append(row);
 }
 if(!scan.running){clearInterval(discoveryPoll);discoveryPoll=null;}
}
$('deviceButton').onclick=openDevice;$('closeDevice').onclick=()=>$('deviceDialog').close();
$('testDevice').onclick=()=>deviceAction('test');$('connectDevice').onclick=()=>deviceAction('connect');
$('discoverDevices').onclick=async()=>{
 try{
  const scan=await api('/api/device',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'discover',network:$('deviceNetwork').value.trim()})});
  showDiscovery(scan);if(scan.running){clearInterval(discoveryPoll);discoveryPoll=setInterval(()=>api('/api/discovery').then(showDiscovery).catch(e=>{clearInterval(discoveryPoll);discoveryPoll=null;$('discoveryProgress').textContent=e.message;}),700);}
 }catch(e){$('discoveryProgress').textContent=e.message;}
};
$('deviceDialog').addEventListener('close',()=>{clearInterval(discoveryPoll);discoveryPoll=null;});
api('/api/device').then(d=>{if(!d.host&&!$('deviceDialog').open)openDevice();}).catch(()=>{});
