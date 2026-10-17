const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const root=path.resolve(__dirname,'..');let server;
(async()=>{
 server=spawn(process.env.PYTHON || 'python',['tests/session-live-fixture.py'],{cwd:root,stdio:['ignore','pipe','inherit']});
 let pending='';const port=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(new Error('fixture server startup timed out')),20000);server.stdout.on('data',chunk=>{pending+=chunk.toString();const line=pending.split(/\r?\n/)[0];try{const data=JSON.parse(line);clearTimeout(timer);resolve(data.port)}catch{}});server.once('error',reject);server.once('exit',code=>reject(new Error(`fixture server exited ${code}`)));});
 const browser=await chromium.launch({channel:'chrome',headless:true});const context=await browser.newContext();const page=await context.newPage();
 const logs=[];page.on('response',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))logs.push({path:new URL(r.url()).pathname,status:r.status()})});
 try{
  await page.goto(`http://127.0.0.1:${port}/?app=1`);
  const logoutHeaders=[];page.on('request',r=>{if(new URL(r.url()).pathname==='/api/logout')logoutHeaders.push(r.headers())});
  for(let i=0;i<2;i++){
   await page.locator('[data-account-choice="passenger"]').click();
   await page.locator('#login-form button[type=submit]').click();
   await page.locator('[data-action="menu-toggle"]').waitFor();
   await page.locator('[data-action="menu-toggle"]').click();
   const responsePromise=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/logout');
   await page.locator('#account-menu [data-action="logout"]').click();
   const response=await responsePromise;assert.equal(response.status(),200,`logout ${i+1} failed`);
   await page.getByText('Sign in',{exact:true}).waitFor({timeout:5000});
   const boot=await page.evaluate(async()=>fetch('/api/bootstrap').then(r=>r.json()));assert.equal(boot.user,null);
  }
  assert.equal(logoutHeaders.length,2);assert(logoutHeaders.every(h=>h['x-expected-user-id']&&h['x-csrf-token']));
  assert.equal(logs.filter(x=>x.path==='/api/login'&&x.status===200).length,2);
  console.log('PASS live Flask + temporary SQLite: two password logins and two CSRF-authenticated logout POSTs each end with anonymous bootstrap',JSON.stringify(logs));
 }finally{await browser.close();server.kill();}
})().catch(e=>{console.error(e);if(server)server.kill();process.exitCode=1;});
