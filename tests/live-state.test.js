// Exercise the real page controller with an in-memory DOM, HTTP, and SSE transport.
// No sensor, runtime data, browser package, or listening network socket is needed.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

class Element{
 constructor(){this.value='';this.options=[];this.dataset={};this.style={};this.children=[];this.classList={toggle(){}};}
 append(...nodes){this.children.push(...nodes);this.options.push(...nodes.filter(n=>n instanceof Element));}
 replaceChildren(...nodes){this.children=nodes;}
 querySelector(){return null;}
 addEventListener(){}
 getContext(){return new Proxy({measureText:t=>({width:t.length*6})},{get:(target,key)=>target[key]||(()=>{})});}
 getBoundingClientRect(){return {width:900,height:400,left:0,top:0};}
}
function page(wallSeconds=Date.now()/1000){
 let wallMs=wallSeconds*1000,monotonicMs=0;
 const nodes=new Map(),pending=[],streams=[];
 const node=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
 node('recordingMode').value='coffee';node('tempDiv').value='roast';
 const sandbox={
  document:{getElementById:node,createElement:()=>new Element(),createTextNode:t=>t,querySelector:node,querySelectorAll:()=>[],body:node('body'),documentElement:node('root')},
  window:{addEventListener(){}},localStorage:{getItem:()=>null,setItem(){}},
  Date:class extends Date{constructor(...args){super(...(args.length?args:[wallMs]));}static now(){return wallMs;}},
  performance:{now:()=>monotonicMs},devicePixelRatio:1,
  getComputedStyle:()=>({getPropertyValue:()=>''}),requestAnimationFrame(){},
  setInterval(){},setTimeout(){},clearTimeout(){},clearInterval(){},console,
  fetch:path=>new Promise(resolve=>pending.push({path,respond:data=>resolve({ok:true,json:async()=>data})})),
  EventSource:class{
   constructor(){this.listeners={};streams.push(this);}
   addEventListener(name,fn){this.listeners[name]=fn;}
   emit(name,data){return this.listeners[name]?.({data:JSON.stringify(data)});}
  }
 };
 const context=vm.createContext(sandbox);
 vm.runInContext(fs.readFileSync(require.resolve('../static/recording.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(require.resolve('../static/plot-scale.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(require.resolve('../static/app.js'),'utf8'),context);
 return {pending,stream:streams[0],nodes,state:expression=>vm.runInContext(expression,context),
  advance:seconds=>{wallMs+=seconds*1000;monotonicMs+=seconds*1000;},
  jumpWall:seconds=>{wallMs+=seconds*1000;}};
}
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
const status=()=>({connected:false,host:'probe.test',latest:null,prediction:{valid:false,points:[]}});
function reply(p,path,data){const i=p.pending.findIndex(q=>q.path===path);assert.notEqual(i,-1,'Missing request '+path);p.pending.splice(i,1)[0].respond(data);}
function replyHistory(p,data={samples:[],events:[]}){const i=p.pending.findIndex(q=>q.path.startsWith('/api/history?'));assert.notEqual(i,-1,'Missing history request');p.pending.splice(i,1)[0].respond(data);}
function clearBackground(p){
 // The controller also loads learning and device information outside the stream.
 reply(p,'/api/status',{learning:{}});
 reply(p,'/api/learning',{live_scores:[],models:{}});
 reply(p,'/api/device',{host:'probe.test'});
}

(async()=>{
 const p=page();clearBackground(p);await flush();
 const start=Date.now()/1000-100;
 const run={id:1,start,end:null,mode:'coffee',auto_drop:1,fc_start:null,weight_loss_pct:null};

 // A recording made by another browser must be recovered without a sensor sample.
 p.stream.emit('open');
 reply(p,'/api/status',status());reply(p,'/api/runs',[run]);reply(p,'/api/events',[]);
 await flush();
 assert.equal(p.state('active.id'),1);
 assert.equal(p.nodes.get('start').disabled,true);
 assert.equal(p.nodes.get('stop').disabled,false);

 // Reconnect after the other browser stopped: controls and the archived view recover.
 p.stream.onerror();
 p.stream.emit('open');
 reply(p,'/api/status',status());reply(p,'/api/runs',[{...run,end:start+80}]);reply(p,'/api/events',[]);
 await flush();
 assert.equal(p.state('active'),null);
 assert.equal(p.state('viewed.id'),1);
 assert.equal(p.nodes.get('stop').disabled,true);

 // An older reconnect snapshot must not overwrite a fresh SSE recording update.
 p.stream.emit('open');
 p.stream.emit('records',{runs:[{...run,id:2,start:start+90}],events:[]});
 reply(p,'/api/status',status());reply(p,'/api/runs',[{...run,end:start+80}]);reply(p,'/api/events',[]);
 await flush();
 assert.equal(p.state('active.id'),2);
 // Archive also lists the currently recording session (end=null).
 // Viewing it must retain its numerical reading, not compare timestamps with null.
 p.state('viewed=active;points=[{t:active.start+1,temperature:123.4,raw:123.5,d1:.1,d2:.01}];refreshReading();');
 assert.equal(p.nodes.get('temp').textContent,'123.4');

 // A pending history response cannot resurrect an event removed by an undo.
 // Use a fresh controller to isolate its history queue from prior reloads.
 const q=page();clearBackground(q);await flush();
 q.stream.emit('open');
 reply(q,'/api/status',status());reply(q,'/api/runs',[]);reply(q,'/api/events',[]);
 await flush();
 q.stream.emit('records',{runs:[],events:[]});
 const removed={id:99,t:Date.now()/1000,label:'FC START',temperature:190,run_id:1};
 replyHistory(q,{samples:[],events:[removed]});
 await flush();
 assert.equal(q.state('events.length'),0);
 replyHistory(q);await flush();
 assert.equal(q.state('events.length'),0);

 // Phones several minutes fast or slow must display the server's same timeline.
 const serverTime=1700000000;
 for(const skew of [-600,600]){
  const c=page(serverTime+skew);clearBackground(c);await flush();
  c.stream.emit('open');
  reply(c,'/api/status',{...status(),now:serverTime});reply(c,'/api/runs',[]);reply(c,'/api/events',[]);
  await flush();
  assert.equal(c.state('serverNow()'),serverTime);
  const liveSample={t:serverTime-.1,temperature:190,raw:190,d1:.1,d2:0};
  c.stream.emit('status',{...status(),now:serverTime,connected:true,latest:liveSample});
  const coffee={...run,start:serverTime-800,fc_start:serverTime-100};
  c.stream.emit('records',{runs:[coffee],events:[]});
  assert.equal(c.nodes.get('connection').textContent,'CONNECTED');
  assert.equal(c.nodes.get('timer').textContent,'13:20');
  assert.equal(c.nodes.get('development').textContent,'01:40');
  assert.equal(c.nodes.get('developmentRatio').textContent,'12.5% · LIVE');
  assert.equal(c.state('span'),1200);
  assert.equal(c.state('end-span'),coffee.start);

  // Forecast freshness uses that same clock, not the fast/slow client clock.
  c.state("$('prediction').checked=true;points=[latest];var forecastReads=0;prediction={valid:true,get points(){forecastReads++;return [{t:latest.t,temperature:190,low:190,high:190}];}};render();");
  assert.equal(c.state('forecastReads'),1);
  c.advance(3);c.state('refreshReading();render();');
  assert.equal(c.nodes.get('connection').textContent,'STALE / OFFLINE');
  assert.equal(c.state('forecastReads'),1);

  // A client clock correction during a disconnect cannot freeze or jump DTR.
  c.stream.onerror();c.jumpWall(3600);c.advance(7);c.state('updateRecords();');
  assert.equal(c.nodes.get('timer').textContent,'13:30');
  assert.equal(c.nodes.get('development').textContent,'01:50');
  assert.equal(c.nodes.get('developmentRatio').textContent,'13.6% · LIVE');

  // Resynchronize at the next status, including a corrected server timestamp.
  c.stream.emit('status',{...status(),now:serverTime+12});
  assert.equal(c.state('serverNow()'),serverTime+12);
  c.state('viewed=active;');c.nodes.get('hold').onclick();
  const query=new URL('http://fixture'+c.pending.filter(r=>r.path.startsWith('/api/history?')).at(-1).path);
  assert.ok(Math.abs(Number(query.searchParams.get('end'))-(serverTime+12.1))<.001);
 }
 console.log('PASS: reconnect and async state recovery; active archive readings; server-clock freshness, DTR, forecast, and history with fast/slow client clocks');
})().catch(error=>{console.error(error);process.exitCode=1;});
