const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), ts = require('typescript');
const file = path.join(__dirname, 'recordingSession.ts');
const mod = new Module(file, module); mod.filename = file; mod.paths = module.paths;
mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS}}).outputText, file);
const {RecordingSession} = mod.exports;
function deferred() {let resolve; const promise = new Promise(r => {resolve=r;}); return {promise,resolve};}
const tick = () => new Promise(r => setImmediate(r));
function fixture(overrides={}) {
  const log=[],captures=[];let done;
  const deps={
    async stopPlayback(){log.push('playback stopped');},async permission(){return true;},async storage(){},
    create(callback){done=callback;const capture={async prepare(){log.push('prepare');},start(seconds){log.push(['start',seconds]);},async finish(){log.push('finish');return {uri:'local',size:10};},async dispose(){log.push('dispose');},...overrides.capture};captures.push(capture);return capture;},
    onStatus(value){log.push(value);},onError(code){log.push(code);},...overrides,
  };
  return {log,captures,session:new RecordingSession(deps),nativeDone:()=>done(false)};
}
test('leaving immediately before start continuation never requests microphone',async()=>{
  let permissions=0;const {session,captures}=fixture({permission:async()=>{permissions++;return true;}});
  const start=session.start('id',45,async()=>{});await session.cancel();await start;
  assert.equal(permissions,0);assert.equal(captures.length,0);
});
test('late first-use permission after cancellation cannot create a recorder',async()=>{
  const wait=deferred();const {session,captures}=fixture({permission:()=>wait.promise});
  const start=session.start('id',45,async()=>{});await tick();await session.cancel();wait.resolve(true);await start;assert.equal(captures.length,0);
});
test('denied permission preserves typing fallback and never creates capture',async()=>{
  const {session,log,captures}=fixture({permission:async()=>false});await session.start('id',45,async()=>{});
  assert.equal(captures.length,0);assert.ok(log.includes('VOICE_DENIED'));assert.equal(log.filter(x=>['idle','starting','recording','finishing'].includes(x)).at(-1),'idle');
});
test('cancel while preparing then retry waits for old disposal before a fresh start',async()=>{
  const wait=deferred(),disposed=deferred();let starts=0;
  const {session,captures}=fixture({capture:{prepare:()=>wait.promise,start(){starts++;},dispose:()=>disposed.promise}});
  const first=session.start('first',45,async()=>{});await tick();const cancel=session.cancel();
  const second=session.start('second',45,async()=>{});await tick();assert.equal(captures.length,1);
  wait.resolve();await first;assert.equal(starts,0);disposed.resolve();await cancel;await second;
  assert.equal(captures.length,2);assert.equal(starts,1);await session.cancel();
});
test('manual and native finish produce one clip, then dispose after consumer finishes',async()=>{
  const consumed=deferred();let count=0;const {session,log,nativeDone}=fixture();
  await session.start('id',45,async()=>{count++;await consumed.promise;});
  const finish=session.finish();nativeDone();await tick();assert.equal(count,1);assert.equal(log.includes('dispose'),false);
  consumed.resolve();await finish;assert.equal(log.filter(x=>x==='dispose').length,1);assert.equal(log.filter(x=>['idle','starting','recording','finishing'].includes(x)).at(-1),'idle');
});
test('cancellation during native stop discards the late finished clip',async()=>{
  const stopped=deferred();let consumed=false;const {session}=fixture({capture:{finish:()=>stopped.promise}});
  await session.start('id',45,async()=>{consumed=true;});const finish=session.finish();await session.cancel();stopped.resolve({uri:'local',size:1});await finish;
  assert.equal(consumed,false);
});
test('consumer failure reports an actionable error and deletes local audio',async()=>{
  const {session,log}=fixture();await session.start('id',45,async()=>{throw Object.assign(new Error(),{code:'VOICE_BUSY'});});await session.finish();
  assert.ok(log.includes('VOICE_BUSY'));assert.ok(log.includes('dispose'));assert.equal(log.filter(x=>['idle','starting','recording','finishing'].includes(x)).at(-1),'idle');
});
