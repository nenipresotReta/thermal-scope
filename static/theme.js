'use strict';
// Apply before the stylesheet paints; each browser keeps its own preference.
(() => {
 const key='thermal-scope-theme', valid=value=>value==='paper'||value==='github-dark';
 function saved(){try{return localStorage.getItem(key);}catch{return null;}}
 function apply(value, persist=false){
  const theme=valid(value)?value:'github-dark';
  document.documentElement.dataset.theme=theme;
  const meta=document.querySelector('meta[name="theme-color"]');
  if(meta)meta.content=theme==='paper'?'#eeeae1':'#0d1117';
  const select=document.getElementById('themeSelect');
  if(select)select.value=theme;
  if(persist){try{localStorage.setItem(key,theme);}catch{/* Private storage may be unavailable. */}}
  window.dispatchEvent(new Event('themechange'));
 }
 apply(saved());
 document.addEventListener('DOMContentLoaded',()=>{
  const select=document.getElementById('themeSelect');
  select.value=document.documentElement.dataset.theme;
  select.addEventListener('change',()=>apply(select.value,true));
 });
 window.addEventListener('storage',event=>{
  if(event.key===key||event.key===null)apply(saved());
 });
})();
