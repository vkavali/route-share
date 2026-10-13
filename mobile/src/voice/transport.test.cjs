const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), ts = require('typescript');
function load(name, mocks={}) {
  const file=path.join(__dirname,name+'.ts'),mod=new Module(file,module);mod.filename=file;mod.paths=module.paths;
  const original=mod.require.bind(mod);mod.require=name=>Object.hasOwn(mocks,name)?mocks[name]:original(name);
  mod._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,file);return mod.exports;
}
const {createVoiceOperation}=load('transport');
const id='aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};}
function response(data,status=200){return{ok:status<400,status,json:async()=>data};}
function setup(t,handler){
  const calls=[],oldFetch=global.fetch,oldForm=global.FormData;
  class Form {constructor(){this.parts=[];}append(...part){this.parts.push(part);}}
  global.FormData=Form;global.fetch=async(url,options)=>{calls.push({url,...options});return handler(url,options);};
  t.after(()=>{global.fetch=oldFetch;global.FormData=oldForm;});return calls;
}
test('authenticated upload binds UUID header and form, uses only original API origin, leaves multipart boundary to fetch',async t=>{
  const calls=setup(t,()=>response({request_id:id,text:'  గచ్చిబౌలి నుంచి విజయవాడ  ',language:'te',duration_ms:1200}));
  const result=await createVoiceOperation('https://route.example','original',id,'te').transcribe('file:///clip.m4a');
  assert.equal(result.text,'గచ్చిబౌలి నుంచి విజయవాడ');assert.equal(calls[0].url,'https://route.example/api/voice/transcribe');
  assert.equal(calls[0].headers.Authorization,'Bearer original');assert.equal(calls[0].headers['X-Voice-Request-ID'],id);assert.equal(calls[0].headers['Content-Type'],undefined);
  assert.deepEqual(calls[0].body.parts,[['audio',{uri:'file:///clip.m4a',name:'trip.m4a',type:'audio/mp4'}],['language','te'],['request_id',id]]);
});
test('Api operations capture token and cancellation aborts upload with original identity after account switch',async t=>{
  const wait=deferred();const calls=setup(t,url=>url.endsWith('/cancel')?response({cancelled:true}):wait.promise);
  const oldBase=process.env.EXPO_PUBLIC_API_URL;process.env.EXPO_PUBLIC_API_URL='https://route.example';t.after(()=>{if(oldBase===undefined)delete process.env.EXPO_PUBLIC_API_URL;else process.env.EXPO_PUBLIC_API_URL=oldBase;});
  const {Api}=load('../api',{'./voice/transport':{createVoiceOperation}});const api=new Api('first-account');const op=api.voiceOperation(id,'en');
  const upload=op.transcribe('file:///clip.m4a');api.token='second-account';await op.cancel();await op.cancel();
  assert.equal(calls[0].signal.aborted,true);assert.equal(calls.length,2);assert.equal(calls[1].headers.Authorization,'Bearer first-account');assert.equal(JSON.parse(calls[1].body).request_id,id);
  wait.resolve(response({request_id:id,text:'late',language:'en',duration_ms:5}));await assert.rejects(upload,{code:'VOICE_CANCELLED'});
});
test('cancellation before upload prevents sending any audio',async t=>{
  const calls=setup(t,()=>response({cancelled:true}));const op=createVoiceOperation('https://route.example','token',id,'te');await op.cancel();
  await assert.rejects(op.transcribe('file:///private.m4a'),{code:'VOICE_CANCELLED'});assert.equal(calls.length,0);
});
test('missing auth cannot send capabilities or audio',async t=>{
  const calls=setup(t,()=>response({}));const op=createVoiceOperation('https://route.example',null,id,'te');
  await assert.rejects(op.capabilities(),{code:'VOICE_UNAVAILABLE'});await assert.rejects(op.transcribe('file:///clip'),{code:'VOICE_UNAVAILABLE'});await op.cancel();assert.equal(calls.length,0);
});
test('capabilities fail closed for missing or malformed model metadata and honor tighter limits',async t=>{
  let body={available:true,languages:['en'],max_seconds:30,max_bytes:1000,daily_remaining:100,reset_at:'2026-10-09T00:00:00Z'};setup(t,()=>response(body));
  const op=createVoiceOperation('https://route.example','token',id,'te');assert.deepEqual(await op.capabilities(),body);
  for(const value of [{},null,{available:true,languages:['te'],max_seconds:0,max_bytes:200}]){body=value;await assert.rejects(op.capabilities(),{code:'VOICE_UNAVAILABLE'});}
});
test('wrong request identity or language and empty text never become an accepted transcript',async t=>{
  let body;setup(t,()=>response(body));
  const op=createVoiceOperation('https://route.example','token',id,'te');
  for(const value of [{request_id:'wrong',text:'hello',language:'te',duration_ms:100},{request_id:id,text:'hello',language:'en',duration_ms:100},{request_id:id,text:'x'.repeat(1001),language:'te',duration_ms:100}]){body=value;await assert.rejects(op.transcribe('file:///clip'),{code:'VOICE_FAILED'});}
  body={request_id:id,text:'  ',language:'te',duration_ms:100};await assert.rejects(op.transcribe('file:///clip'),{code:'VOICE_NO_SPEECH'});
});
test('busy, unavailable, no speech and server timeout retain actionable error codes',async t=>{
  let code='VOICE_BUSY',status=429;setup(t,()=>response({code},status));const op=createVoiceOperation('https://route.example','token',id,'en');
  for(const pair of [['VOICE_BUSY',429],['VOICE_UNAVAILABLE',503],['VOICE_TIMEOUT',504],['VOICE_NO_SPEECH',422],['VOICE_INVALID_AUDIO',413]]){[code,status]=pair;await assert.rejects(op.transcribe('file:///clip'),{code,status});}
});
test('client deadline is 90 seconds and aborts with timeout; cancel remains bounded separately',async t=>{
  const realSet=global.setTimeout,realClear=global.clearTimeout,timers=[];
  global.setTimeout=(fn,ms)=>{const timer={fn,ms};timers.push(timer);return timer;};global.clearTimeout=()=>{};t.after(()=>{global.setTimeout=realSet;global.clearTimeout=realClear;});
  setup(t,(_url,options)=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error(),{name:'AbortError'})))));
  const op=createVoiceOperation('https://route.example','token',id,'en');const upload=op.transcribe('file:///clip');assert.equal(timers[0].ms,90000);timers[0].fn();await assert.rejects(upload,{code:'VOICE_TIMEOUT'});
  const cancel=op.cancel();assert.equal(timers[1].ms,5000);timers[1].fn();await cancel;
});

test('daily quota metadata is retained and missing/invalid remaining limits fail closed',async t=>{
  const good={available:true,languages:['en','te'],max_seconds:45,max_bytes:2097152,daily_remaining:0,reset_at:'2026-10-09T00:00:00Z'};
  let body=good;setup(t,()=>response(body));const op=createVoiceOperation('https://route.example','token',id,'te');
  assert.deepEqual(await op.capabilities(),good);
  for(const invalid of [undefined,-1,0.5,'0']){body={...good,daily_remaining:invalid};await assert.rejects(op.capabilities(),{code:'VOICE_UNAVAILABLE'});}
  body={...good,reset_at:'tomorrow morning'};await assert.rejects(op.capabilities(),{code:'VOICE_UNAVAILABLE'});
});
test('quota rejection preserves the new UTC reset without silently retrying upload',async t=>{
  const calls=setup(t,()=>response({code:'VOICE_DAILY_LIMIT',daily_remaining:0,reset_at:'2026-10-10T00:00:00Z'},429));
  const op=createVoiceOperation('https://route.example','token',id,'te');
  await assert.rejects(op.transcribe('file:///clip'),{code:'VOICE_DAILY_LIMIT',status:429,reset_at:'2026-10-10T00:00:00Z'});assert.equal(calls.length,1);
});
