'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../desktop/index.html'),'utf8');
const fn=html.slice(html.indexOf('function applyConnectionState('),html.indexOf('async function poll()'));
assert.ok(fn.includes('runningElsewhere'));
function render(state,busy=false){
 const nodes={};
 const $=id=>nodes[id]||(nodes[id]={textContent:'',checked:false,disabled:false,hidden:false,open:false,
  classList:{toggle(){}},showModal(){this.open=true},close(){this.open=false}});
 const context={state,$,sessionStorage:{getItem:()=>null},document:{querySelectorAll:()=>[]}};
 vm.runInNewContext(fn+'\napplyConnectionState('+busy+');',context);
 return $;
}
let $=render({configured:false,vmRunning:false,connection:{runningElsewhere:true,canConnect:true,message:'Your existing iPhone'}});
assert.equal($('vm-state').textContent,'iPhone running elsewhere');
assert.equal($('connection-banner').hidden,false);
assert.equal($('connect-running').disabled,false);
assert.equal($('start').textContent,'Connect to iPhone');assert.equal($('start').disabled,false);
assert.equal($('prepare-apple').disabled,true);assert.equal($('onboarding').open,false);
$=render({configured:false,vmRunning:false,connection:{runningElsewhere:true,canConnect:false}});
assert.equal($('connect-running').hidden,true);assert.equal($('start').disabled,true);
$=render({configured:false,vmRunning:false,connection:{runningElsewhere:false}});
assert.equal($('start').textContent,'Set up iPhone');assert.equal($('start').disabled,false);
assert.equal($('onboarding').open,true);
$=render({configured:true,vmRunning:true,guest:{version:7},connection:{runningElsewhere:false}});
assert.equal($('vm-state').textContent,'iPhone online');assert.equal($('shutdown').disabled,false);
assert.equal($('connection-banner').hidden,true);
$=render({configured:false,vmRunning:false,connection:{runningElsewhere:true,canConnect:true}},true);
assert.equal($('connect-running').disabled,true);
console.log('PASS Studio reconnect UI: existing, unknown, fresh, connected and busy states');
