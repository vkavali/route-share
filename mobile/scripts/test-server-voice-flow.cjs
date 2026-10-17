// Actual voice component and recording controller, with a synthetic local clip and deferred server responses.
// No human microphone, production account or network request is used.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const compile=file=>ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/voice',file),'utf8'),{compilerOptions:{module:1,jsx:2,target:7}}).outputText;
const load=(file,req)=>{const mod={exports:{}};vm.runInNewContext(compile(file),{module:mod,exports:mod.exports,require:req,Date,setTimeout,clearTimeout});return mod.exports;};
const parser=load('parser.ts',()=>({})),copyModule=load('copy.ts',()=>({})),recording=load('recordingSession.ts',()=>({})),transport=load('transport.ts',()=>({}));
const tick=()=>new Promise(setImmediate),deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
function mount(options={}){
 let slots=[],index=0,dirty=false,effects=[],tree,disposed=false,permission=options.permission!==false;
 let config=options.available!==false,capError=options.capError||null,clipSerial=0,dailyRemaining=options.dailyRemaining??100;
 const listeners=new Set(),operations=[],drafts=[],failures=[],log=[];
 const api={token:'fixture-only',voiceOperation:(id,language)=>{const result=deferred();const operation={id,language,result,cancelled:false,capturedToken:api.token,
  capabilities:async()=>{if(capError)throw Object.assign(new Error(),{code:capError});return{available:config,languages:['en','te'],max_seconds:45,max_bytes:2097152,daily_remaining:dailyRemaining,reset_at:'2026-10-09T00:00:00Z'};},
  transcribe:async uri=>{log.push(['transcribe',uri]);return result.promise;},cancel:async()=>{operation.cancelled=true;log.push(['cancel',id]);}};operations.push(operation);return operation;}};
 const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>v===b[i]);
 const React={createElement:(type,props,...children)=>typeof type==='function'?type({...props,children}):({type,props:props||{},children}),
  useState:value=>{const i=index++;if(!(i in slots))slots[i]=value;return[slots[i],value=>{const next=typeof value==='function'?value(slots[i]):value;if(next!==slots[i]){slots[i]=next;dirty=true;}}];},
  useRef:value=>{const i=index++;return slots[i]||(slots[i]={current:value});},
  useEffect:(fn,deps)=>{const i=index++;if(!slots[i]||!same(slots[i].deps,deps)){const old=slots[i];slots[i]={deps};effects.push(()=>{old?.cleanup?.();slots[i].cleanup=fn();});}},
 };React.default=React;
 let registeredStop;
 const speech={stopPlayback:async()=>{},hasSpokenVoice:async()=>true,registerCaptureStop:fn=>{registeredStop=fn;return()=>{registeredStop=null;}},stopVoice:async()=>{await registeredStop?.();}};
 const capture={recordingAvailable:()=>true,requestRecordingPermission:async()=>{log.push(['permission']);return options.permissionPromise||permission;},prepareVoiceStorage:async()=>{},createLocalCapture:()=>{const serial=++clipSerial;return{
  prepare:async()=>{log.push(['prepare',serial]);},start:()=>{log.push(['record',serial]);},
  finish:async()=>{log.push(['stop',serial]);return{uri:`file:///fixture-${serial}.m4a`,size:1000,durationMs:1000};},dispose:async()=>{log.push(['delete',serial]);}};}};
 const native={AppState:{addEventListener:(_,fn)=>{listeners.add(fn);return{remove:()=>listeners.delete(fn)};}},Linking:{openSettings:async()=>{}},StyleSheet:{create:x=>x}};
 for(const name of ['Pressable','Switch','TextInput','View'])native[name]=name;
 const imports={react:React,'react-native':native,'expo-crypto':{randomUUID:()=>`fixture-${operations.length}`},'./parser':parser,'./speech':speech,'./capture':capture,'./recordingSession':recording,'./transport':transport,'./copy':copyModule,'../SeatPalLoader':{SeatPalLoader:'SeatPalLoader'},'../NativeTypography':{AppText:'Text'}};
 const Component=load('VoiceTripInput.tsx',name=>{assert.ok(imports[name],`unexpected import ${name}; no legacy recognizer allowed`);return imports[name];}).VoiceTripInput;
 const props={api,lang:options.lang||'en',onDraft:d=>drafts.push(d),onFailure:e=>failures.push(e)};
 const nodes=(n,type)=>!n||typeof n!=='object'?[]:[...(n.type===type?[n]:[]),...(n.children||[]).flat(Infinity).flatMap(c=>nodes(c,type))];
 const text=n=>!n?'':typeof n==='string'?n:(n.children||[]).flat(Infinity).map(text).join('');
 const render=()=>{if(disposed)return;let count=0;do{dirty=false;index=0;tree=Component(props);const pending=effects;effects=[];pending.forEach(fn=>fn());assert.ok(++count<20);}while(dirty);};
 const settle=async()=>{for(let i=0;i<3;i++){await tick();render();}};
 const copy=()=>copyModule.voiceCopy(props.lang);
 const press=key=>{const n=nodes(tree,'Pressable').find(n=>text(n)===copy()[key]);assert.ok(n,`button ${key}`);assert.ok(!n.props.disabled,`${key} enabled`);n.props.onPress();render();};
 const input=()=>nodes(tree,'TextInput').find(n=>n.props.accessibilityLabel===copy().transcript);
 render();
 return{api,operations,drafts,failures,log,settle,press,copy,render,visibleText:()=>text(tree),loaders:()=>nodes(tree,'SeatPalLoader'),setDailyRemaining:value=>{dailyRemaining=value;},
  edit:value=>{assert.ok(input().props.editable!==false);input().props.onChangeText(value);render();},transcript:()=>input().props.value,
  disabled:key=>Boolean(nodes(tree,'Pressable').find(n=>text(n)===copy()[key])?.props.disabled),
  setAvailable:value=>{config=value;},permission:value=>{permission=value;},setCapError:value=>{capError=value;},
  async start(){press('listen');await settle();},async stop(){press('stop');await settle();},
  resolve:text=>{const op=operations.at(-1);op.result.resolve({request_id:op.id,language:op.language,text,duration_ms:1000});},
  reject:(code,extra={})=>operations.at(-1).result.reject(Object.assign(new Error(),{code,...extra})),
  appEvent:event=>{listeners.forEach(fn=>fn(event));render();},background:()=>{listeners.forEach(fn=>fn('background'));render();},language:lang=>{props.lang=lang;render();},
  logout:()=>{api.token=null;render();},dispose:()=>{disposed=true;slots.forEach(s=>s?.cleanup?.());},
 };
}
async function exerciseServerVoice(){
 const deps=JSON.parse(fs.readFileSync(path.join(__dirname,'../package.json'),'utf8')).dependencies;assert.ok(!deps['expo-speech-recognition'],'legacy recognizer is not a runtime dependency');
 const exports=fs.readFileSync(path.join(__dirname,'../src/voice/index.ts'),'utf8');assert.ok(!exports.includes("from './native'"),'public voice exports do not load old native recognizer');
 const h=mount();assert.equal(h.loaders().length,1);assert.equal(h.loaders()[0].props.label,h.copy().checking);await h.settle();assert.equal(h.loaders().length,0);await h.start();assert.equal(h.loaders().length,0,'actual recording has listening status, not pending logo');assert.ok(h.log.some(x=>x[0]==='record'));assert.equal(h.drafts.length,0);
 await h.stop();assert.equal(h.loaders().length,1);assert.equal(h.loaders()[0].props.label,h.copy().stopping);assert.ok(h.log.some(x=>x[0]==='transcribe'));assert.equal(h.drafts.length,0);
 h.resolve('Hyderabad to Vijayawada tomorrow at nine am for two people');await h.settle();assert.equal(h.loaders().length,0);assert.ok(h.transcript().includes('Hyderabad'));assert.equal(h.drafts.length,0,'transcription never triggers review or search');
 h.edit('Place A to Place B tomorrow morning for two people');h.press('review');await h.settle();assert.equal(h.drafts.length,1);assert.equal(h.drafts[0].fromQuery,'Place A');assert.equal(h.drafts[0].toQuery,'Place B');assert.equal(h.drafts[0].seats,2);assert.equal(h.drafts[0].time,undefined);const integratedDraft=h.drafts[0];
 await h.start();await h.stop();h.resolve('Kondapur to Eluru tomorrow morning for one person');await h.settle();assert.ok(h.transcript().includes('Kondapur'),'repeat voice replaces only editable transcript');assert.equal(h.drafts.length,1);h.dispose();
 for(const event of ['cancel','background','language','logout','dispose']){
  const c=mount();await c.settle();await c.start();await c.stop();const old=c.operations.at(-1);
  if(event==='cancel')c.press('cancel');else if(event==='language')c.language('te');else c[event]();
  old.result.resolve({request_id:old.id,language:'en',text:'Late secret route',duration_ms:1000});await c.settle();
  assert.equal(c.drafts.length,0,`${event}: no draft callback`);if(event!=='dispose')assert.equal(c.transcript(),'',`${event}: no late transcript`);
  assert.ok(old.cancelled,`${event}: original operation cancelled`);assert.equal(old.capturedToken,'fixture-only');c.dispose();
 }
 for(const failure of ['denied','unavailable','busy']){
  const c=mount({permission:failure!=='denied',available:failure!=='unavailable'});await c.settle();
  if(failure==='denied'){await c.start();assert.ok(!c.log.some(x=>x[0]==='record'));}
  if(failure==='busy'){await c.start();await c.stop();c.reject('VOICE_BUSY');await c.settle();}
  c.edit('Kondapur to Eluru tomorrow morning for one person');c.press('review');await c.settle();assert.equal(c.drafts.length,1,`${failure}: typing fallback`);c.dispose();
 }
 for(const lang of ['en','te']){
  for(const boundary of ['initial','preflight','response']){
   const c=mount({lang,dailyRemaining:boundary==='initial'?0:100});await c.settle();
   if(boundary==='preflight'){c.setDailyRemaining(0);await c.start();}
   if(boundary==='response'){await c.start();await c.stop();c.reject('VOICE_DAILY_LIMIT',{reset_at:'2026-10-10T00:00:00Z'});await c.settle();}
   assert.ok(c.disabled('listen'),`${lang} ${boundary}: exhausted Speak disabled`);
   assert.ok(c.visibleText().includes(c.copy().dailyLimit),`${lang} ${boundary}: clear daily-limit message`);
   assert.ok(c.visibleText().includes(boundary==='response'?'2026-10-10 00:00':'2026-10-09 00:00'),`${lang} ${boundary}: UTC reset shown`);
   if(boundary!=='response')assert.ok(!c.log.some(x=>['permission','prepare','record','transcribe'].includes(x[0])),`${lang} ${boundary}: no mic permission/capture/upload`);
   else assert.equal(c.log.filter(x=>x[0]==='transcribe').length,1,'quota rejection never retries upload');
   c.edit('Kondapur to Eluru tomorrow morning for one person');c.press('review');await c.settle();assert.equal(c.drafts.length,1,`${lang} ${boundary}: typed explicit review preserved`);c.dispose();
  }
 }
 for(const event of ['inactive','background']){
  const permission=deferred(),c=mount({permissionPromise:permission.promise});await c.settle();await c.start();c.appEvent(event);permission.resolve(true);await c.settle();
  assert.equal(c.log.some(x=>x[0]==='record'),event==='inactive',`${event}: pending permission boundary`);c.dispose();
 }
 const te=mount({lang:'te'});await te.settle();await te.start();await te.stop();te.resolve('గచ్చిబౌలి నుంచి విజయవాడకి రేపు ఉదయం ఒక్కరికి రైడ్ కావాలి');await te.settle();te.press('review');assert.equal(te.drafts.length,1);assert.equal(te.drafts[0].seats,1);te.dispose();
 console.log('PASS mounted voice component: record → Stop → server text → edit → explicit Review; repeat, EN/TE daily quota initial/preflight/response and typed review, denied/unavailable/busy typing fallback, cancel/background/language/logout/unmount late-result guards.');
 return integratedDraft;
}
module.exports={exerciseServerVoice};
if(require.main===module)exerciseServerVoice().catch(e=>{console.error(e);process.exitCode=1;});
