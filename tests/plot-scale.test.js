const assert=require('node:assert/strict');
const {temperatureZoom}=require('../static/plot-scale.js');
for(const position of [0,.2,.5,1]){
 const a=temperatureZoom(0,250,position,-120);
 assert.equal(a.min,0);assert.ok(a.max<250);
 assert.deepEqual(a,temperatureZoom(0,250,.5,-120));
 const b=temperatureZoom(a.min,a.max,position,120);
 assert.equal(b.min,0);assert.ok(Math.abs(b.max-250)<1e-9);
}
assert.equal(temperatureZoom(-180,550,.2,100).min,0);
console.log('PASS: fixed-zero temperature zoom, independent of pointer position');
