const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const root = path.resolve(__dirname, '..');
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.json':'application/json','.webmanifest':'application/manifest+json','.png':'image/png','.jpg':'image/jpeg','.woff2':'font/woff2'};
const server=http.createServer((req,res)=>{let pathname=new URL(req.url,'http://local').pathname;if(pathname==='/')pathname='/static/index.html';const file=path.resolve(root,`.${pathname}`);if(!file.startsWith(path.resolve(root,'static'))) {res.writeHead(404);res.end();return;}try{res.setHeader('Content-Type',types[path.extname(file)]||'application/octet-stream');res.end(fs.readFileSync(file));}catch{res.writeHead(404);res.end();}});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({channel:'chrome',headless:true});const context=await browser.newContext();
 let user=null,logoutPosts=[],loginPosts=[],statePosts=[],bootstrapReads=0;let failNextLogout=false,loseNextLogoutResponse=false,holdNextState=false,releaseHeldState=null;
 await context.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()).pathname,method=req.method(),headers=req.headers();
  if(url==='/api/bootstrap'){bootstrapReads++;return route.fulfill({json:{csrf_token:'fixture-csrf',user: user?{...user}:null,mode:'local_beta',flags:{demo_password_enabled:true,public_registration_enabled:false,festival_greetings_enabled:false}}});}
  if(url==='/api/phone/capabilities')return route.fulfill({json:{enabled:false,backup_email_enabled:false}});
  if(url==='/api/login'&&method==='POST'){const body=req.postDataJSON();loginPosts.push(body.account);user={id:body.account,name:`Fixture ${body.account}`,phone_verified:true,access:{can_drive:false},onboarding_required:false};return route.fulfill({json:{user:{...user},csrf_token:'fixture-csrf'}});}
  if(url==='/api/state'){statePosts.push({expected:headers['x-expected-user-id'],csrf:headers['x-csrf-token']});const snapshot={user:user?{...user}:null,trips:[],bookings:[],requests:[],ratings:[],notifications:[],chats:[]};if(holdNextState){holdNextState=false;return new Promise(resolve=>{releaseHeldState=()=>resolve(route.fulfill({json:snapshot}));});}return route.fulfill({json:snapshot});}
  if(url==='/api/logout'&&method==='POST'){logoutPosts.push({expected:headers['x-expected-user-id'],csrf:headers['x-csrf-token']});if(failNextLogout||loseNextLogoutResponse){if(loseNextLogoutResponse)user=null;failNextLogout=false;loseNextLogoutResponse=false;return route.fulfill({status:503,json:{error:'fixture network failure'}});}if(headers['x-expected-user-id']!==user?.id||headers['x-csrf-token']!=='fixture-csrf')return route.fulfill({status:409,json:{code:'account_changed',error:'account changed'}});user=null;return route.fulfill({json:{ok:true}});}
  return route.fulfill({json:{}});
 });
 await context.route('**/fixture/switch-account',async route=>{user={id:'passenger2',name:'Fixture passenger2',phone_verified:true,access:{can_drive:false},onboarding_required:false};return route.fulfill({json:{ok:true}})});
 const base=`http://127.0.0.1:${server.address().port}/?app=1`;
 try{
  const a=await context.newPage(),b=await context.newPage();a.on('pageerror',e=>console.error('A PAGE',e));b.on('pageerror',e=>console.error('B PAGE',e));
  await Promise.all([a.goto(base),b.goto(base)]);await a.locator('#login-password').fill('fixture-password');const anonymousBoots=bootstrapReads;await a.evaluate(()=>window.dispatchEvent(new Event('focus')));await a.waitForTimeout(100);assert.equal(bootstrapReads,anonymousBoots);assert.equal(await a.locator('#login-password').inputValue(),'fixture-password');
  await a.locator('[data-account-choice="passenger"]').click();await a.locator('#login-password').fill('fixture-password');await a.locator('#login-form button[type=submit]').click();
  await a.locator('[data-action="menu-toggle"]').click();await a.locator('#account-menu').getByText('Fixture passenger',{exact:true}).waitFor();
  await b.locator('[data-action="menu-toggle"]').click();await b.locator('#account-menu').getByText('Fixture passenger',{exact:true}).waitFor({timeout:5000});const privateBoots=bootstrapReads;await a.evaluate(()=>window.dispatchEvent(new Event('focus')));for(let i=0;i<100&&bootstrapReads===privateBoots;i++)await new Promise(resolve=>setTimeout(resolve,20));assert(bootstrapReads>privateBoots);
  failNextLogout=true;await a.locator('#account-menu [data-action="logout"]').click();
  await a.getByText('Sign-out could not be confirmed. Retry.').waitFor();assert.equal(await a.getByText('Fixture passenger',{exact:true}).count(),0);
  await a.locator('[data-action="retry-signout"]').click();await a.getByRole('heading',{name:'Signing out'}).waitFor();
  await a.getByText('Sign in',{exact:true}).waitFor({timeout:5000});await b.getByText('Sign in',{exact:true}).waitFor({timeout:5000});
  assert.equal(logoutPosts.length,2);assert(logoutPosts.every(x=>x.expected==='passenger'&&x.csrf==='fixture-csrf'));
  await a.locator('[data-account-choice=passenger2]').click();await a.locator('#login-password').fill('fixture-password');await a.locator('#login-form button[type=submit]').click();await a.locator('#account-menu').waitFor({state:'detached'});await a.locator('[data-action=menu-toggle]').click();await a.locator('#account-menu [data-action=logout]').waitFor();
  loseNextLogoutResponse=true;await a.locator('#account-menu [data-action=logout]').click();await a.getByText('Sign in',{exact:true}).waitFor({timeout:5000});await b.getByText('Sign in',{exact:true}).waitFor({timeout:5000});assert.equal(logoutPosts.length,3);assert.equal(logoutPosts[2].expected,'passenger2');
  await a.locator('[data-account-choice=passenger]').click();await a.locator('#login-password').fill('fixture-password');await a.locator('#login-form button[type=submit]').click();await a.locator('[data-action=menu-toggle]').click();await a.locator('#account-menu [data-action=logout]').waitFor();failNextLogout=true;await a.locator('#account-menu [data-action=logout]').click();await a.getByText('Sign-out could not be confirmed. Retry.').waitFor();await a.evaluate(()=>fetch('/fixture/switch-account'));await a.locator('[data-action=retry-signout]').click();await a.getByText('Another account is active. Continue only if you recognize it.').waitFor();assert.equal(await a.getByText('Fixture passenger2',{exact:true}).count(),0);await a.locator('[data-action=continue-current-session]').click();await a.locator('[data-action=menu-toggle]').click();await a.locator('#account-menu').getByText('Fixture passenger2',{exact:true}).waitFor();
  await a.locator('#account-menu [data-action=logout]').click();await a.getByText('Sign in',{exact:true}).waitFor({timeout:5000});
  holdNextState=true;await b.locator('[data-account-choice=passenger]').click();await b.locator('#login-password').fill('fixture-password');await b.locator('#login-form button[type=submit]').click();for(let i=0;i<100&&!releaseHeldState;i++)await new Promise(resolve=>setTimeout(resolve,20));assert.equal(typeof releaseHeldState,'function');await a.locator('[data-action=menu-toggle]').click();await a.locator('#account-menu').getByText('Fixture passenger',{exact:true}).waitFor({timeout:5000});await a.locator('#account-menu [data-action=logout]').click();await b.getByText('Sign in',{exact:true}).waitFor({timeout:5000});releaseHeldState();releaseHeldState=null;await b.waitForTimeout(150);assert.equal(await b.locator('[data-action=menu-toggle]').count(),0);
  console.log('PASS mocked actual UI: cross-tab login/logout, retry bound to captured identity, lost-response reconciliation, different-account confirmation gate, and stale held state cannot restore old private UI');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;server.close();});
