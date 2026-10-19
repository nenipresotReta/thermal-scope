// Axis transforms are independent of drawing and acquisition.
function temperatureZoom(min,max,pointerFraction,deltaY){
 // Live zoom has a fixed zero baseline; cursor position cannot translate it.
 const upper=Math.max(.05,Math.min(2000,Math.max(.05,max)*Math.exp(Math.max(-1000,Math.min(1000,deltaY))*.0015)));
 return {min:0,max:upper,division:upper/5,center:upper/2};
}
if(typeof module!=='undefined')module.exports={temperatureZoom};
