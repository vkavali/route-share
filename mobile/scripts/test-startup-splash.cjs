// Focused unit test for native splash reveal scheduling; this mocks the platform API.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const sourcePath=path.join(__dirname,'../src/startupSplash.ts');
function load(hideAsync){
 const callbacks=[];let prevented=0;
 const imported={'expo-splash-screen':{preventAutoHideAsync:()=>{prevented++;return Promise.resolve();},hideAsync}};
 const module={exports:{}};
 const code=ts.transpileModule(fs.readFileSync(sourcePath,'utf8'),{compilerOptions:{module:1,target:7,esModuleInterop:true}}).outputText;
 vm.runInNewContext(code,{module,exports:module.exports,require:name=>{assert.ok(name in imported,name);return imported[name];},requestAnimationFrame:fn=>{callbacks.push(fn);return callbacks.length;}});
 return{reveal:module.exports.revealNativeFrame,callbacks,getPrevented:()=>prevented};
}
function flushFrame(env){const callback=env.callbacks.shift();assert.ok(callback,'expected queued animation frame');callback();}
(async()=>{
 let hides=0;
 const success=load(()=>{hides++;return Promise.resolve();});
 assert.equal(success.getPrevented(),1);
 success.reveal(); // first layout
 success.reveal(); // repeated layout coalesces
 assert.equal(hides,0,'no hide during layout');
 assert.equal(success.callbacks.length,1,'only one first-frame callback is queued');
 flushFrame(success);
 assert.equal(hides,0,'first RAF is not enough');
 success.reveal();
 assert.equal(success.callbacks.length,1,'repeated layout between frames coalesces');
 flushFrame(success);
 assert.equal(hides,1,'hide happens after the second RAF');
 success.reveal();
 assert.equal(success.callbacks.length,0,'successful hide is single-shot');
 assert.equal(hides,1);

 let attempts=0;
 const retry=load(()=>{attempts++;return attempts===1?Promise.reject(new Error('native hide failed')):Promise.resolve();});
 retry.reveal();flushFrame(retry);assert.equal(attempts,0);flushFrame(retry);assert.equal(attempts,1);
 await Promise.resolve();await Promise.resolve();
 retry.reveal();assert.equal(retry.callbacks.length,1,'rejected hide permits a later reveal attempt');
 flushFrame(retry);assert.equal(attempts,1);flushFrame(retry);assert.equal(attempts,2);
 retry.reveal();assert.equal(retry.callbacks.length,0,'successful retry remains single-shot');
 console.log('PASS startup splash: waits two RAFs, coalesces layouts, hides once, and retries after hide failure.');
})().catch(error=>{console.error(error);process.exitCode=1;});
