const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), ts = require('typescript');
function load(name, mocks) {
  const file = path.join(__dirname, name + '.ts');
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS}}).outputText;
  const mod = new Module(file, module); mod.filename = file; mod.paths = module.paths;
  const original = mod.require.bind(mod); mod.require = name => Object.hasOwn(mocks,name) ? mocks[name] : original(name);
  mod._compile(compiled, file); return mod.exports;
}
function deferred() {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise, resolve};}
function nativeFixture(platform = 'ios', prepareWait, modeWait) {
  const data = new Map(), dirs = new Set(['file:///cache/Audio', 'file:///cache/ExpoAudio']), log = [], recorders = [];
  const uri = parts => 'file:///' + parts.map(value => typeof value === 'string' ? value : value.uri).join('/').replace(/^file:\/*/,'').replace(/\/{2,}/g,'/');
  class File {
    constructor(...parts) {this.uri = uri(parts);}
    get name() {return this.uri.split('/').at(-1);}
    get exists() {return data.has(this.uri);}
    get size() {return data.get(this.uri) || 0;}
    delete() {data.delete(this.uri); log.push('delete');}
    move(destination) {data.set(destination.uri, data.get(this.uri)); data.delete(this.uri); this.uri = destination.uri;}
  }
  class Directory {
    constructor(...parts) {this.uri = uri(parts);}
    get exists() {return dirs.has(this.uri);}
    create() {dirs.add(this.uri);}
    list() {return [...data.keys()].filter(value => value.startsWith(this.uri+'/') && !value.slice(this.uri.length+1).includes('/')).map(value => new File(value));}
  }
  class Recorder {
    constructor(options) {this.options=options; this.uri=`file:///cache/${platform==='ios'?'ExpoAudio':'Audio'}/recording-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa${options.extension}`;this.isRecording=false;recorders.push(this);}
    addListener(name, callback) {this.listener=callback;return {remove:()=>{this.listener=null;}};}
    async prepareToRecordAsync() {if(prepareWait)await prepareWait;data.set(this.uri,1000);log.push('prepare');}
    record(options) {this.isRecording=true;this.startOptions=options;log.push('record');}
    async stop() {this.isRecording=false;log.push('stop');}
    release() {log.push('release');}
  }
  const audio = {AudioModule:{AudioRecorder:Recorder},RecordingPresets:{HIGH_QUALITY:{extension:'.m4a',sampleRate:44100,numberOfChannels:2,bitRate:128000,ios:{outputFormat:'aac'},android:{outputFormat:'mpeg4',audioEncoder:'aac'},web:{}}},setAudioModeAsync:async mode=>{log.push(mode.allowsRecording ? 'mode recording' : 'mode stopped');if(!mode.allowsRecording && modeWait) await modeWait;},requestRecordingPermissionsAsync:async()=>({granted:false})};
  const api = load('capture',{'react-native':{Platform:{OS:platform}},'expo-audio':audio,'expo-file-system':{File,Directory,Paths:{cache:'file:///cache'}}});
  return {api,data,log,recorders};
}
test('local capture uses mono marked M4A and the native 45-second limit', async()=>{
  const {api,recorders,data,log}=nativeFixture(); const capture=api.createLocalCapture(()=>{});
  await capture.prepare();capture.start(99);
  assert.equal(recorders[0].options.numberOfChannels,1);assert.equal(recorders[0].startOptions.forDuration,45);
  const clip=await capture.finish('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');
  assert.match(clip.uri,/route-share-voice\/route-share-voice-/);assert.equal(clip.size,1000);
  await capture.dispose();assert.equal(data.size,0);assert.ok(log.indexOf('stop')<log.indexOf('release'));
});
test('cancel during prepare releases and deletes a late-created local recording',async()=>{
  const wait=deferred();const {api,data,log}=nativeFixture('ios',wait.promise);const capture=api.createLocalCapture(()=>{});
  const preparing=capture.prepare();await new Promise(r=>setImmediate(r));const disposing=capture.dispose();wait.resolve();
  await preparing;await disposing;assert.equal(data.size,0);assert.ok(!log.includes('record'));assert.throws(()=>capture.start(45),/VOICE_CANCELLED/);
});
test('startup cleanup is feature scoped on both platforms and skips active capture',async()=>{
  for(const platform of ['ios','android']){
    const {api,data}=nativeFixture(platform);const folder=platform==='ios'?'ExpoAudio':'Audio';
    const unrelated=`file:///cache/${folder}/recording-bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb.m4a`;
    const orphan=`file:///cache/${folder}/recording-cccccccc-cccc-cccc-cccc-cccccccccccc.route-share-voice.m4a`;
    data.set(unrelated,1000);data.set(orphan,1000);
    const capture=api.createLocalCapture(()=>{});await capture.prepare();await api.cleanupVoiceFiles();
    assert.ok(data.has(unrelated));assert.ok(!data.has(orphan));assert.equal(data.size,2);
    await capture.dispose();assert.equal(data.size,1);
  }
});
test('permission denial does not create or start a recorder',async()=>{
  const {api,recorders}=nativeFixture();assert.equal(await api.requestRecordingPermission(),false);assert.equal(recorders.length,0);
});
test('native finish event is exposed without starting any follow-up action',async()=>{
  const {api,recorders}=nativeFixture();const finished=[];const capture=api.createLocalCapture(failed=>finished.push(failed));
  await capture.prepare();capture.start(45);recorders[0].listener({isFinished:true,hasError:false});
  assert.deepEqual(finished,[false]);await capture.dispose();
});
function speechFixture(voices) {
  const log=[],callbacks={};const native={Platform:{OS:'ios'},AppState:{currentState:'active',addEventListener:(name,cb)=>{callbacks.change=cb;return{remove(){}};}}};
  const engine={stop:async()=>{log.push('stop');},getAvailableVoicesAsync:async()=>voices,speak:(text,options)=>{log.push({text,options});options.onDone();}};
  return {api:load('speech',{'react-native':native,'expo-speech':engine}),log,callbacks,engine};
}
test('Telugu speech never silently uses an English voice',async()=>{
  const {api,log}=speechFixture([{language:'en-IN',identifier:'english'}]);let unavailable=false;
  assert.equal(await api.speakReply('నమస్తే','te',{enabled:true,onUnavailable:()=>{unavailable=true;}}),false);
  assert.equal(unavailable,true);assert.equal(log.filter(value=>typeof value==='object').length,0);
});
test('capture cleanup completes before spoken replies begin',async()=>{
  const {api,log}=speechFixture([{language:'te-IN',identifier:'telugu'}]);const capture=deferred();api.registerCaptureStop(()=>capture.promise);
  const reply=api.speakReply('నమస్తే','te',{enabled:true});await new Promise(r=>setImmediate(r));assert.equal(log.filter(v=>typeof v==='object').length,0);
  capture.resolve();assert.equal(await reply,true);assert.equal(log.at(-1).options.language,'te-IN');
});
test('background or cancellation invalidates pending speech voice lookup',async()=>{
  const {api,log,engine,callbacks}=speechFixture([]);const voices=deferred();engine.getAvailableVoicesAsync=()=>voices.promise;
  const reply=api.speakReply('నమస్తే','te',{enabled:true});await new Promise(r=>setImmediate(r));callbacks.change('background');voices.resolve([{language:'te-IN',identifier:'telugu'}]);
  assert.equal(await reply,false);assert.equal(log.filter(v=>typeof v==='object').length,0);
});

test('native lease spans old component disposal and new component preparation',async()=>{
  const wait=deferred();const {api,log,recorders}=nativeFixture('ios',wait.promise);
  const old=api.createLocalCapture(()=>{});const preparing=old.prepare();await new Promise(r=>setImmediate(r));
  const disposing=old.dispose();const fresh=api.createLocalCapture(()=>{});const newPrepare=fresh.prepare();
  await new Promise(r=>setImmediate(r));assert.equal(log.filter(x=>x==='mode recording').length,1);assert.equal(recorders.length,1);
  wait.resolve();await preparing;await disposing;await newPrepare;fresh.start(45);
  assert.ok(log.indexOf('release')<log.lastIndexOf('mode recording'));
  assert.ok(log.indexOf('mode stopped')<log.lastIndexOf('mode recording'));
  assert.ok(log.lastIndexOf('mode recording')<log.indexOf('record'));
  await fresh.dispose();
});

test('unmounted capture cleanup stays registered until TTS can safely speak',async()=>{
  const {api,log}=speechFixture([{language:'te-IN',identifier:'telugu'}]);const wait=deferred();
  const unregister=api.registerCaptureStop(()=>wait.promise);unregister();
  const reply=api.speakReply('నమస్తే','te',{enabled:true});await new Promise(r=>setImmediate(r));
  assert.equal(log.filter(v=>typeof v==='object').length,0);wait.resolve();assert.equal(await reply,true);
});
test('failed unmounted cleanup prevents later TTS even after failure settles',async()=>{
  const {api,log}=speechFixture([{language:'te-IN',identifier:'telugu'}]);
  const unregister=api.registerCaptureStop(()=>Promise.reject(new Error('native stop failed')));unregister();await new Promise(r=>setImmediate(r));
  assert.equal(await api.speakReply('నమస్తే','te',{enabled:true}),false);assert.equal(log.filter(v=>typeof v==='object').length,0);
});

test('cancel during final audio-mode reset cannot release lease ahead of that reset',async()=>{
  const wait=deferred();const {api,recorders}=nativeFixture('ios',undefined,wait.promise);
  const old=api.createLocalCapture(()=>{});await old.prepare();old.start(45);
  const finishing=old.finish('aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa').catch(cause=>cause);await new Promise(r=>setImmediate(r));
  const disposing=old.dispose();const fresh=api.createLocalCapture(()=>{});const preparing=fresh.prepare();
  await new Promise(r=>setImmediate(r));assert.equal(recorders.length,1);
  wait.resolve();assert.equal((await finishing).code,'VOICE_CANCELLED');await disposing;await preparing;
  fresh.start(45);assert.equal(recorders[1].isRecording,true);await fresh.dispose();
});
