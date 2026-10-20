// Recording coordinates and derived metrics share seconds as their time unit.
// Server timestamps govern the timeline. Advance an accepted server timestamp
// with a monotonic clock so client wall-clock skew and later clock corrections
// cannot alter freshness, recording duration, or development ratios.
function createServerClock(wallNow=()=>Date.now()/1000,monotonicNow=()=>performance.now()/1000){
 let epoch=wallNow(),at=monotonicNow();
 return {
  now(){return epoch+Math.max(0,monotonicNow()-at);},
  sync(serverTime){
   if(!Number.isFinite(serverTime))return;
   epoch=serverTime;at=monotonicNow();
  }
 };
}
function recordingWindow(run,now){
 const finished=run.end!==null&&run.end!==undefined;
 const duration=Math.max(0,(finished?run.end:now)-run.start);
 const span=Math.max(960,Math.ceil((duration+(finished?30:300))/120)*120);
 return {start:run.start,end:run.start+span,span};
}
function developmentMetrics(run,now){
 if(!run||run.mode==='general'||run.fc_start===null||run.fc_start===undefined)return null;
 const finish=run.drop_t??run.end??now;
 if(finish<run.fc_start)return null;
 const duration=finish-run.fc_start,total=finish-run.start;
 return {seconds:duration,percent:total>0?100*duration/total:0,live:run.end===null};
}
function recordingTicks(start,end,zero){
 const range=end-start,target=range/10;
 const step=[15,30,60,120,180,300,600,900,1800,3600,7200,14400].find(s=>s>=target)||Math.ceil(target/3600)*3600;
 const result=[];
 for(let i=Math.ceil((start-zero)/step);zero+i*step<=end+.001;i++)result.push(zero+i*step);
 return result;
}
if(typeof module!=='undefined')module.exports={createServerClock,recordingWindow,developmentMetrics,recordingTicks};
