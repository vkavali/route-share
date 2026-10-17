/* Real Chromium DOM with isolated API fixtures; no live email/SMS delivery claim. */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/vkava/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const root = path.resolve(__dirname, '..');
const server = http.createServer((req, res) => {
  if (req.url === '/') { res.setHeader('Content-Type', 'text/html'); res.end('<!doctype html><div id="app"></div>'); return; }
  if (!/^\/static\/[a-z0-9-]+\.js$/.test(req.url)) { res.writeHead(404); res.end(); return; }
  res.setHeader('Content-Type', 'text/javascript'); res.end(fs.readFileSync(path.join(root, req.url)));
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({channel:'chrome', headless:true});
  const page = await browser.newPage({viewport:{width:390,height:844}});page.on('pageerror',e=>console.error('PAGE ERROR',e));
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.evaluate(async () => {
      const {makeAccountFlows} = await import('/static/account-flows.js');
      const {makePhoneAuth} = await import('/static/phone-auth.js');
      const {messages} = await import('/static/i18n.js');
      const esc = value => String(value ?? '').replace(/[&<>"']/g, v => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[v]));
      window.offset = 0; const realNow = Date.now; Date.now = () => realNow() + window.offset;
      const expires = () => new Date(Date.now()+300000).toISOString();
      const challenge = id => ({challenge_id:id, expires_at:expires(), resend_at:new Date(Date.now()+2000).toISOString(),masked_phone:'******4321',masked_email:'a***@example.com'});
      window.calls=[]; window.failEmail=true; window.mode='account'; window.authenticated=false;
      const state = {lang:'en',busy:false,user:{id:'person',phone_verified:true},data:{}};
      const lifecycle={recovery_key_configured:false,deletion_allowed:true,backup_email:{enabled:true,configured:false,masked_email:null,verified_at:null}};
      const api=async (url,method,payload)=>{
        window.calls.push({url,method,payload});
        if(url==='/api/account/lifecycle')return structuredClone(lifecycle);
        if(url==='/api/phone/capabilities')return {enabled:true,backup_email_enabled:true,otp_length:6,terms_url:'/terms',privacy_url:'/privacy',terms_version:'1',privacy_version:'1'};
        if(url==='/api/account/reauth/start'){window.reauthPurpose=payload.purpose;return challenge('reauth');}
        if(url==='/api/account/reauth/verify')return {purpose:window.reauthPurpose,action_token:'proof',expires_at:expires()};
        if(url==='/api/account/backup-email/start'){if(window.delayEnrollment){window.delayEnrollment=false;return new Promise(resolve=>window.releaseEnrollment=()=>resolve(challenge('late-enrollment')));}if(window.failEmail){window.failEmail=false;throw new TypeError('Network failed');}return challenge('enrollment');}
        if(url==='/api/account/backup-email/verify'){lifecycle.backup_email={enabled:true,configured:true,masked_email:'a***@example.com',verified_at:new Date(Date.now()).toISOString()};return {backup_email:structuredClone(lifecycle.backup_email)};}
        if(url==='/api/account/backup-email/remove'){lifecycle.backup_email={enabled:true,configured:false,masked_email:null,verified_at:null};return {backup_email:structuredClone(lifecycle.backup_email)};}
        if(url==='/api/account/recovery/email/start'){if(window.delayRecovery){window.delayRecovery=false;return new Promise(resolve=>window.releaseRecovery=()=>resolve(challenge('late-recovery')));}return challenge('email-recovery');}
        if(url==='/api/account/recovery/email/verify')return {recovery_token:'recovery-proof',expires_at:expires()};
        if(url==='/api/account/recovery/phone/start')return challenge('new-phone');
        if(url==='/api/account/recovery/phone/verify')return {user:{id:'person'},csrf_token:'test'};
        throw new Error('Unexpected API '+url);
      };
      const t=key=>messages[state.lang]?.[key]||messages.en[key]||key;
      let af,pa; const render=()=>{af?.unmount();pa?.unmount();const host=document.querySelector('#app');host.innerHTML=window.mode==='account'?af.page('account-security'):pa.page();if(window.mode==='account')af.mount(host,'account-security');else pa.mount(host,'login');};
      af=makeAccountFlows({state,t,esc,icon:()=>'',api,render,refresh:async()=>{},errorMessage:e=>e.message,expire:async()=>{},labelOf:()=>'',onDeleted:async()=>{}});
      pa=makePhoneAuth({state,t,esc,api,render,onAuthenticated:async()=>{window.authenticated=true;render();},onProfileSaved:async()=>{}});
      window.setAccountUser=user=>{state.user=user;render();};
      window.toggleEmail=value=>{lifecycle.backup_email.enabled=value;af.destroy();render();};
      window.switchAccount=()=>{state.user={id:'other-person',phone_verified:true};render();};
      window.showRecovery=()=>{af.destroy();state.user=null;window.mode='phone';render();};
      window.useTelugu=()=>{state.lang='te';render();};
      render();
    });
    const verify = async selector => { await page.locator(`${selector} [name=code]`).fill('123456'); await page.locator(`${selector} button[type=submit]`).click(); };
    await page.locator('[data-af-id=backup_email]').click();
    await page.locator('[data-af-action=life-send]').click();
    await verify('[data-af-form=life-verify]');
    await page.locator('[data-af-form=life-email-start] [name=email]').fill('alice@example.com');
    await page.locator('[data-af-form=life-email-start] button[type=submit]').click();
    assert.equal(await page.locator('[data-af-form=life-email-start] [name=email]').inputValue(),'alice@example.com');
    await page.locator('[data-af-form=life-email-start] button[type=submit]').click();
    assert(await page.locator('[data-af-action=life-email-resend]').isDisabled());
    await verify('[data-af-form=life-email-verify]');
    await page.locator('[data-af-id=backup_email_remove]').waitFor();
    assert(!await page.locator('#app').textContent().then(s=>s.includes('alice@example.com')));
    const emailPosts=await page.evaluate(()=>calls.filter(c=>c.url==='/api/account/backup-email/start'));
    assert.equal(emailPosts.length,2);assert.equal(emailPosts[0].payload.request_id,emailPosts[1].payload.request_id);
    assert(/^[A-Za-z0-9_-]{43}$/.test(emailPosts[0].payload.flow_token));
    await page.locator('[data-af-id=backup_email_remove]').click();await page.locator('[data-af-action=life-send]').click();await verify('[data-af-form=life-verify]');
    await page.locator('[data-af-form=life-email-remove] [name=confirm]').check();await page.locator('[data-af-form=life-email-remove] button[type=submit]').click();
    await page.locator('[data-af-id=backup_email]').waitFor();
    assert.equal(await page.locator('[data-af-id=backup_email_remove]').count(),0);
    console.log('PASS enrollment network retry retains email and request identity, verifies masked display, fresh-proof removal');
    await page.evaluate(()=>toggleEmail(false));await page.locator('.af-page').waitFor();await page.waitForTimeout(50);assert.equal(await page.locator('[data-af-id=backup_email]').count(),0);await page.evaluate(()=>toggleEmail(true));
    await page.locator('[data-af-id=backup_email]').click();await page.locator('[data-af-action=life-send]').click();await verify('[data-af-form=life-verify]');
    await page.locator('[data-af-form=life-email-start] [name=email]').fill('other@example.com');await page.evaluate(()=>delayEnrollment=true);await page.locator('[data-af-form=life-email-start] button[type=submit]').click();
    await page.locator('[data-af-form=life-email-start] button[type=submit]').evaluate(el=>el.click());
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.url==='/api/account/backup-email/start').length),3);
    await page.evaluate(()=>switchAccount());await page.locator('[data-af-id=backup_email]').waitFor();await page.evaluate(()=>releaseEnrollment());await page.waitForTimeout(100);
    assert.equal(await page.locator('[data-af-form=life-email-verify]').count(),0);assert(await page.locator('[data-af-id=backup_email]').isEnabled());
    console.log('PASS enrollment duplicate click suppressed and stale response ignored after account switch');
    await page.evaluate(()=>setAccountUser({id:'demo',phone_verified:true,development:true}));assert.equal(await page.locator('[data-af-action=life-choose]').count(),0);await page.evaluate(()=>setAccountUser({id:'admin',phone_verified:true,role:'admin'}));assert.equal(await page.locator('[data-af-action=life-choose]').count(),0);console.log('PASS feature-off enrollment hidden and development/admin accounts have no self-serve recovery controls');
    await page.evaluate(()=>showRecovery());await page.locator('[data-phone-action=recover]').click();await page.locator('[data-phone-action=recovery-email]').click();
    await page.locator('[data-phone-form=email-recovery-start] [name=recovery_email]').fill('alice@example.com');await page.locator('[data-phone-form=email-recovery-start] button[type=submit]').click();
    await page.evaluate(()=>offset+=300001);await page.waitForTimeout(1100);
    assert(await page.locator('[data-phone-form=email-recovery-verify] button[type=submit]').isDisabled());
    await page.locator('[data-phone-action=email-recovery-resend]').click();await verify('[data-phone-form=email-recovery-verify]');
    await page.locator('[data-phone-form=email-phone-start] [name=new_phone]').fill('9876543210');await page.locator('[data-phone-form=email-phone-start] button[type=submit]').click();await verify('[data-phone-form=email-phone-verify]');
    await page.waitForFunction(()=>authenticated);
    const posts=await page.evaluate(()=>calls.filter(c=>c.url.startsWith('/api/account/recovery/')));
    assert.equal(new Set(posts.map(c=>c.payload.flow_token)).size,1);
    assert.equal(await page.evaluate(()=>localStorage.length),0);
    console.log('PASS email expiry blocks verification; resend then new-phone proof recovers; single flow token and no persisted secrets');
    await page.locator('[data-phone-action=recover]').click();await page.locator('[data-phone-action=recovery-email]').click();await page.locator('[data-phone-form=email-recovery-start] [name=recovery_email]').fill('alice@example.com');
    await page.evaluate(()=>delayRecovery=true);await page.locator('[data-phone-form=email-recovery-start] button[type=submit]').click();await page.locator('[data-phone-form=email-recovery-start] button[type=submit]').evaluate(el=>el.click());
    const beforeBack=await page.evaluate(()=>calls.filter(c=>c.url==='/api/account/recovery/email/start').length);assert.equal(beforeBack,3);
    await page.locator('[data-phone-action=recovery-back]').click();await page.evaluate(()=>releaseRecovery());await page.waitForTimeout(100);assert.equal(await page.locator('[data-phone-form=email-recovery-verify]').count(),0);
    await page.locator('[data-phone-action=recovery-email]').click();await page.locator('[data-phone-form=email-recovery-start] [name=recovery_email]').fill('alice@example.com');await page.locator('[data-phone-form=email-recovery-start] button[type=submit]').click();await verify('[data-phone-form=email-recovery-verify]');
    await page.locator('[data-phone-form=email-phone-start] [name=new_phone]').fill('9876543210');await page.locator('[data-phone-form=email-phone-start] button[type=submit]').click();await page.evaluate(()=>authenticated=false);await verify('[data-phone-form=email-phone-verify]');await page.waitForFunction(()=>authenticated);
    console.log('PASS back invalidates late response, duplicate recovery submit suppressed, full recovery works a second time');
    await page.evaluate(()=>useTelugu());assert((await page.locator('#app').textContent()).includes('ఫోన్'));
    console.log('PASS Telugu strings render');
  } finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
})().catch(error=>{console.error(error);process.exitCode=1;server.close();});
