// Recording coordinates and derived metrics share seconds as their time unit.
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
 const range=end-start,target=range/8;
 const step=[15,30,60,120,180,300,600,900,1800,3600,7200,14400].find(s=>s>=target)||Math.ceil(target/3600)*3600;
 const result=[];
 for(let i=Math.ceil((start-zero)/step);zero+i*step<=end+.001;i++)result.push(zero+i*step);
 return result;
}
if(typeof module!=='undefined')module.exports={recordingWindow,developmentMetrics,recordingTicks};
