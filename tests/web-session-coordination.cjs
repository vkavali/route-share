const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/vkava/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const root = path.resolve(__dirname, '..');
const server = http.createServer((req,res)=>{
  if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><meta charset="utf-8"><div id="app"></div>');return;}
  if(req.url==='/static/session-coordination.js'){res.setHeader('Content-Type','text/javascript');res.end(fs.readFileSync(path.join(root,'static/session-coordination.js')));return;}
  res.writeHead(404);res.end();
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const context=await browser.newContext();
 try{
  const a=await context.newPage(),b=await context.newPage();
  const url=`http://127.0.0.1:${server.address().port}/`;
  await Promise.all([a.goto(url),b.goto(url)]);
  await Promise.all([a.evaluate(async()=>{const {createSessionCoordinator}=await import('/static/session-coordination.js');window.events=[];window.coordinator=createSessionCoordinator({onChange:()=>events.push('change')});}),b.evaluate(async()=>{const {createSessionCoordinator}=await import('/static/session-coordination.js');window.events=[];window.coordinator=createSessionCoordinator({onChange:()=>events.push('change')});})]);
  await a.evaluate(()=>coordinator.announce());
  await b.waitForFunction(()=>events.length===1);
  const payloadPromise=b.evaluate(()=>new Promise(resolve=>{const bc=new BroadcastChannel('seatpal-session-events-v1');bc.onmessage=e=>{bc.close();resolve(e.data)};}));
  await a.evaluate(()=>coordinator.announce());
  const payload=await payloadPromise;
  assert.deepEqual(Object.keys(payload).sort(),['nonce','type']);
  assert.equal(payload.type,'session-changed');
  assert.equal(await b.evaluate(()=>events.length),2);
  const stored=await a.evaluate(()=>localStorage.getItem('seatpal-session-event-v1'));
  assert.equal(typeof stored,'string');
  assert.equal(await a.evaluate(()=>Object.keys(localStorage).some(k=>/token|account|user|csrf/i.test(k))),false);
  await Promise.all([a.evaluate(()=>coordinator.close()),b.evaluate(()=>coordinator.close())]);
  console.log('PASS two-tab session invalidation uses deduplicable secret-free broadcast and storage fallback payload');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;server.close();});
