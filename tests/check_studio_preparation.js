'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(path.join(__dirname,'../desktop/index.html'),'utf8');
const code=html.slice(html.indexOf('function duration('),html.indexOf('let preparationLogBusy='));
function render(p){const nodes={};const $=id=>nodes[id]||(nodes[id]={hidden:false,textContent:''});vm.runInNewContext(code+';renderPreparation(p);',{p,$});return $;}
let $=render(null);assert.equal($('preparation-status').hidden,true);
$=render({stage:'Copying system files',status:'running',elapsedSeconds:123,outputAgeSeconds:2,processId:12,writeBytes:1048576,cpuSeconds:14,logFile:'logs/preparation/run/preparation.log',copyProgress:{percent:45,rate:'2.0MB/s'}});
assert.equal($('prep-stage').textContent,'Copying system files');assert.equal($('prep-warning').hidden,true);
assert.match($('prep-meta').textContent,/elapsed 2m 3s/);assert.match($('prep-meta').textContent,/Current copy only: 45%/);
$=render({stage:'Mounting',status:'running',elapsedSeconds:150,outputAgeSeconds:140});assert.match($('prep-warning').textContent,/not confirmed/);
$=render({stage:'Mounting',status:'running',stale:true,heartbeatAgeSeconds:60});assert.match($('prep-warning').textContent,/not checked in/);
$=render({stage:'Mounting',status:'failed',error:'Cannot mount image'});assert.equal($('prep-warning').textContent,'Cannot mount image');
$=render({stage:'Copying',status:'running',copyProgress:{percent:99,rate:'8MB/s',transferredFiles:143143,discoveredEntries:262888,listingInProgress:true}});
assert.match($('prep-meta').textContent,/Files transferred: 143143/);assert.match($('prep-meta').textContent,/Still discovering files/);
assert.ok(html.includes("box.value=JSON.stringify"));assert.ok(!html.includes('box.innerHTML'));
console.log('PASS Studio preparation diagnostics: elapsed time, copy-only progress, quiet, stale, failed, safe plain text');
