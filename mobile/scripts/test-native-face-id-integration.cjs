// App/native session integration with the production vault, UI controls and Api.
// SecureStore, Face ID and server responses are deterministic fixtures; this is
// not a physical-device Face ID test.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript');
const compile=file=>ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.React,target:ts.ScriptTarget.ES2020}}).outputText;
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const ORIGIN='https://fixture.invalid',TOKEN='routeShareToken',MARKER='seatpal.session.mode.v1',PROTECTED='seatpal.session.biometric.v1';
const lockedMarker=(accountId='account-a',origin=ORIGIN)=>JSON.stringify({mode:'locked',origin,accountId});
const plainMarker=(accountId='account-a',origin=ORIGIN)=>JSON.stringify({mode:'plain',origin,accountId});
const protectedSession=(token='saved-token',accountId='account-a',origin=ORIGIN)=>JSON.stringify({token,accountId,origin});

const stored=new Map();let secureReads=[],secureWrites=[],secureDeletes=[],cancelProtected=false,protectedGate=null;
const SecureStore={WHEN_PASSCODE_SET_THIS_DEVICE_ONLY:'when-passcode-set-this-device-only',canUseBiometricAuthentication:()=>true,
 async getItemAsync(key,options){secureReads.push({key,options});if(key===PROTECTED&&cancelProtected){cancelProtected=false;throw Object.assign(new Error('Face ID canceled'),{code:'AUTHENTICATION_CANCELED'});}if(key===PROTECTED&&protectedGate)await new Promise((resolve,reject)=>{protectedGate.resolve=resolve;protectedGate.reject=reject;});return stored.has(key)?stored.get(key):null;},
 async setItemAsync(key,value,options){secureWrites.push({key,value,options});stored.set(key,value);},
 async deleteItemAsync(key,options){secureDeletes.push({key,options});stored.delete(key);}};

let hooks=[],cursor=0,tree,dirty=false,effects=[],listeners=[],apiCalls=[],apiMode={bootstrapError:null,stateError:null},serverUser={id:'account-a',onboarding_required:false,access:{can_drive:false,can_request:true,is_staff:false}};
let React;
const native={Platform:{OS:'ios'},StyleSheet:{create:x=>x,absoluteFill:{}},useWindowDimensions:()=>({width:390,height:844}),AppState:{currentState:'active',addEventListener:(type,fn)=>{listeners.push(fn);return{remove(){listeners=listeners.filter(item=>item!==fn);}};}},BackHandler:{addEventListener:()=>({remove(){}})},Alert:{alert(){}},Linking:{openURL(){}},Share:{share(){}}};
for(const n of ['ActivityIndicator','Image','KeyboardAvoidingView','Pressable','ScrollView','StatusBar','TextInput','View'])native[n]=n;
React={createElement:(type,props,...children)=>({type,props:props||{},children}),
 useState:value=>{const i=cursor++;if(!(i in hooks))hooks[i]=typeof value==='function'?value():value;return[hooks[i],next=>{const result=typeof next==='function'?next(hooks[i]):next;if(result!==hooks[i]){hooks[i]=result;dirty=true;}}];},
 useRef:value=>{const i=cursor++;return hooks[i]||(hooks[i]={current:value});},
 useMemo:(fn,deps)=>{const i=cursor++;if(!hooks[i]||!same(hooks[i].deps,deps))hooks[i]={deps,value:fn()};return hooks[i].value;},
 useEffect:(fn,deps)=>{const i=cursor++;if(!hooks[i]||!same(hooks[i].deps,deps)){const previous=hooks[i];hooks[i]={deps};effects.push(()=>{previous?.cleanup?.();hooks[i].cleanup=fn();});}},};
React.useCallback=(fn,deps)=>React.useMemo(()=>fn,deps);React.default=React;
function same(a,b){return a&&b&&a.length===b.length&&a.every((value,index)=>value===b[index]);}

class Api{constructor(token){this.token=token||null;apiCalls.push({kind:'construct',token:this.token});}async login(account,password){apiCalls.push({kind:'login',account,password});if(apiMode.loginError)throw apiMode.loginError;return apiMode.loginResult||{token:'login-token',user:serverUser};}async bootstrap(){apiCalls.push({kind:'bootstrap',token:this.token});if(apiMode.bootstrapError)throw apiMode.bootstrapError;return{user:serverUser,places:[],mode:'hosted_beta'};}async state(){apiCalls.push({kind:'state',token:this.token});if(apiMode.stateError)throw apiMode.stateError;return{trips:[],bookings:[],requests:[],ratings:[],safety_reports:[],blocks:[]};}async logout(){apiCalls.push({kind:'logout',token:this.token});}async action(){return{};}async request(){return{};}}
const theme=load('SeatPalTheme.ts',()=>{throw Error('unexpected theme import');});
const imports={react:React,'react-native':native,'expo-secure-store':SecureStore,'expo-local-authentication':{AuthenticationType:{FACIAL_RECOGNITION:2},hasHardwareAsync:async()=>true,isEnrolledAsync:async()=>true,supportedAuthenticationTypesAsync:async()=>[2]},'expo-location':{},'expo-crypto':{},'react-native-safe-area-context':{SafeAreaProvider:'SafeAreaProvider',SafeAreaView:'SafeAreaView'},'./api':{Api,API_BASE:ORIGIN},'./translation':{T:(_,key)=>key},'./generated/i18n':load('generated/i18n.js',()=>{throw Error('unexpected i18n dependency');}),'./MapPicker':{MapPicker:'MapPicker'},'./RouteMap':{RouteMap:'RouteMap'},'./DateTimeField':{DateTimeField:'DateTimeField'},'./SeatPalLoader':{SeatPalLoader:'SeatPalLoader'},'./NativeTypography':{AppText:'Text',NativeTypographyProvider:'Typography'},'./Icon':{Icon:'Icon'},'./IdentityVerificationScreen':{IdentityVerificationScreen:'IdentityVerification'},'./AccountLifecycleScreen':{AccountLifecycleScreen:'AccountLifecycle'},'./PhoneAuthScreen':{PhoneAuthScreen:'PhoneAuth'},'./CommunityScreens':{CommunityScreens:'Community'},'./ServiceScreens':{ServiceScreens:'ServiceScreens',serviceLabels:()=>({payments:'Payments',verification:'Verification',reviews:'Reviews',driver:'Driver profile',queue:'Document review'})},'./SeatPalTheme':theme,'./voice':{VoiceTripInput:'VoiceInput',stopVoice:async()=>{},speakReply:async()=>true}};
imports['./nativeErrorMessages']=load('nativeErrorMessages.ts',()=>({}));
imports['./travelDraft']=load('travelDraft.ts',()=>({}));
imports['./nativeSession']=load('nativeSession.ts',name=>{assert.ok(imports[name],name);return imports[name];});
imports['./FaceIdControls']=load('FaceIdControls.tsx',name=>{assert.ok(imports[name],name);return imports[name];});
const App=load('App.tsx',name=>{if(name.startsWith('../assets/'))return name;assert.ok(imports[name],name);return imports[name];}).default;
const nodes=(node,type)=>!node||typeof node!=='object'?[]:[...(node.type===type?[node]:[]),...(node.children||[]).flat(Infinity).flatMap(child=>nodes(child,type))];
const text=node=>!node?'':typeof node==='string'||typeof node==='number'?String(node):(node.children||[]).flat(Infinity).map(text).join('');
function expand(node){if(!node||typeof node!=='object')return node;if(node.type===imports['./FaceIdControls'].FaceIdUnlockScreen)return expand(node.type(node.props));if(node.children)node.children=node.children.map(expand);return node;}
function render(){let count=0;do{dirty=false;cursor=0;tree=expand(App());const pending=effects;effects=[];pending.forEach(fn=>fn());assert.ok(++count<30,'App render stabilizes');}while(dirty);}
async function settle(){for(let i=0;i<4;i++){await tick();render();}}
function press(label){const button=nodes(tree,'Pressable').find(node=>node.props.accessibilityLabel===label||text(node)===label);assert.ok(button,`button ${label}`);assert.ok(!button.props.disabled,`enabled ${label}`);button.props.onPress();render();}
function emit(state){native.AppState.currentState=state;for(const listener of [...listeners])listener(state);render();}
async function mount(seed,settings={}){for(const key of [...stored.keys()])stored.delete(key);for(const [key,value] of Object.entries(seed))stored.set(key,value);secureReads=[];secureWrites=[];secureDeletes=[];cancelProtected=false;protectedGate=null;apiCalls=[];apiMode={bootstrapError:null,stateError:null,...settings.apiMode};serverUser=settings.serverUser||{id:'account-a',onboarding_required:false,access:{can_drive:false,can_request:true,is_staff:false}};hooks=[];effects=[];listeners=[];native.AppState.currentState='active';render();await settle();}
function unmount(){for(const hook of hooks)hook?.cleanup?.();hooks=[];effects=[];listeners=[];}

async function testAppFlow(){
 await mount({[TOKEN]:'legacy-stale',[MARKER]:lockedMarker(),[PROTECTED]:protectedSession()});
 assert.equal(apiCalls.filter(call=>call.kind==='bootstrap'||call.kind==='state').length,0,'locked startup calls neither bootstrap nor state');
 assert.ok(nodes(tree,'Pressable').some(node=>node.props.testID==='face-id-unlock'));
 assert.equal(nodes(tree,'Community').length,0,'locked startup renders no private account component');
 assert.equal(secureReads.some(read=>read.key===TOKEN),false,'locked startup never reads legacy/plain token');

 cancelProtected=true;press('Unlock with Face ID');await settle();
 assert.equal(apiCalls.filter(call=>call.kind==='bootstrap').length,0,'canceled biometric does not bootstrap');
 assert.ok(text(tree).includes('Face ID did not unlock SeatPal'),'canceled biometric leaves retry message');
 assert.equal(JSON.parse(stored.get(MARKER)).mode,'locked');
 assert.equal(nodes(tree,'Pressable').some(node=>node.props.testID==='face-id-unlock'),true);

 press('Unlock with Face ID');await settle();
 assert.ok(apiCalls.some(call=>call.kind==='bootstrap'&&call.token==='saved-token'));
 assert.ok(apiCalls.some(call=>call.kind==='state'&&call.token==='saved-token'));
 assert.ok(nodes(tree,'Pressable').some(node=>text(node)==='voiceEntry'),'successful unlock reaches private home');

 const bearerCallsBeforeBackground=apiCalls.filter(call=>call.token==='saved-token').length;emit('background');await settle();
 assert.equal(nodes(tree,'Pressable').some(node=>text(node)==='voiceEntry'),false,'background removes private content');
 assert.equal(apiCalls.filter(call=>call.token==='saved-token').length,bearerCallsBeforeBackground,'background sends no additional requests with the old bearer');
 assert.equal(apiCalls.at(-1)?.token,null,'background erases the in-memory API bearer');
 assert.equal((await imports['./nativeSession'].sessionVault.inspect()).kind,'locked');
 emit('active');await settle();
 assert.equal(nodes(tree,'Pressable').some(node=>node.props.testID==='face-id-unlock'),true,'foreground does not unlock automatically');
 assert.equal(apiCalls.filter(call=>call.kind==='bootstrap').length,1,'foreground does not bootstrap until explicit unlock');

 press('Unlock with Face ID');await settle();assert.ok(nodes(tree,'Pressable').some(node=>text(node)==='voiceEntry'));
 press('communityProfile');await settle();
 const community=nodes(tree,'Community')[0];assert.ok(community,'profile settings path renders CommunityScreens');
 const setting=community.props.profileExtra;assert.equal(setting.type,imports['./FaceIdControls'].FaceIdSetting,'profileExtra points to the production FaceIdSetting');
 assert.equal(setting.props.enabled,true,'profile setting reflects the restored Face ID session');
 const settingTree=setting.type(setting.props);const toggle=nodes(settingTree,'Pressable').find(node=>node.props.testID==='face-id-toggle');assert.ok(toggle);
 toggle.props.onPress();render();await settle();
 assert.equal(JSON.parse(stored.get(MARKER)).mode,'plain','explicit profile toggle disables Face ID');
 assert.equal(stored.has(PROTECTED),false);

 nodes(tree,'Community')[0].props.onBack();render();await settle();
 press('logout');await settle();
 assert.equal(JSON.parse(stored.get(MARKER)).mode,'signed-out','logout commits signed-out marker');
 assert.equal(stored.has(TOKEN),false);assert.equal(stored.has(PROTECTED),false);
 assert.ok(nodes(tree,'PhoneAuth').length,'logout returns to ordinary login');
 unmount();
}

async function testRacesAndFailClosed(){
 const seed={[TOKEN]:'stale-plain',[MARKER]:lockedMarker(),[PROTECTED]:protectedSession()};
 await mount(seed);protectedGate={resolve:null};press('Unlock with Face ID');
 for(let i=0;i<20&&!protectedGate.resolve;i++)await tick();assert.equal(typeof protectedGate.resolve,'function','unlock reaches delayed keychain read');
 emit('background');await settle();protectedGate.resolve();await settle();
 assert.equal(nodes(tree,'Pressable').some(node=>text(node)==='voiceEntry'),false,'late unlock cannot restore after background');
 assert.equal((await imports['./nativeSession'].sessionVault.inspect()).kind,'locked');
 unmount();

 await mount({[TOKEN]:'stale-plain',[MARKER]:'{malformed'});
 assert.equal(apiCalls.filter(call=>call.kind==='bootstrap').length,0,'invalid metadata never bootstraps');
 assert.equal(secureReads.some(read=>read.key===TOKEN),false,'invalid metadata never falls through to plaintext token');
 assert.ok(nodes(tree,'PhoneAuth').length===0,'invalid metadata remains on failed/retry screen');
 unmount();

 await mount({[TOKEN]:'expired-token',[MARKER]:plainMarker(),[PROTECTED]:protectedSession('other-token')},{apiMode:{bootstrapError:{status:401,code:'session_expired',message:'expired'}}});
 await settle();
 assert.equal(JSON.parse(stored.get(MARKER)).mode,'signed-out','server 401 purges session with tombstone');
 assert.equal(stored.has(TOKEN),false);assert.equal(stored.has(PROTECTED),false);
 assert.equal(nodes(tree,'Pressable').some(node=>text(node)==='voiceEntry'),false,'401 removes private view');
 assert.ok(nodes(tree,'PhoneAuth').length,'401 purge returns the app to ordinary sign-in');
 unmount();

 const newUser={id:'account-b',onboarding_required:false,access:{can_drive:false,can_request:true,is_staff:false}};
 await mount({[MARKER]:JSON.stringify({mode:'signed-out',origin:ORIGIN}),[PROTECTED]:protectedSession('old-account-token','account-a')},{serverUser:newUser});
 const phone=nodes(tree,'PhoneAuth')[0];assert.ok(phone);await phone.props.onAuthenticated({token:'new-account-token',user:newUser,onboarding_required:false});await settle();
 assert.equal(JSON.parse(stored.get(MARKER)).mode,'plain');assert.equal(JSON.parse(stored.get(MARKER)).accountId,'account-b');
 assert.equal(stored.has(PROTECTED),false,'new account does not inherit previous biometric credential');
 press('communityProfile');await settle();assert.equal(nodes(tree,'Community')[0].props.profileExtra.props.enabled,false);
 unmount();
}

async function testEnrollmentInvalidation(){
 const {NativeSessionVault}=imports['./nativeSession'];
 const gate=()=>({resolve:null,reject:null});
 const options={apiOrigin:ORIGIN,isIOS:true,protectedOptions:{keychainAccessible:SecureStore.WHEN_PASSCODE_SET_THIS_DEVICE_ONLY},supportsFaceID:async()=>true};
 const makeStorage=values=>({async getItemAsync(key){return values.has(key)?values.get(key):null;},async setItemAsync(key,value){values.set(key,value);},async deleteItemAsync(key){values.delete(key);}});

 // Backgrounding while availability is still resolving must tombstone rather
 // than save the prior plain token as a rollback.
 {
  const values=new Map([[TOKEN,'plain-a'],[MARKER,plainMarker('account-a')]]),availability=gate();let current=true;
  const vault=new NativeSessionVault(makeStorage(values),{...options,supportsFaceID:()=>new Promise(resolve=>{availability.resolve=resolve;})});
  const pending=vault.enable('plain-a','account-a','Confirm Face ID',()=>current);
  for(let i=0;i<20&&!availability.resolve;i++)await tick();assert.equal(typeof availability.resolve,'function');
  current=false;availability.resolve(true);await assert.rejects(pending);
  assert.equal(JSON.parse(values.get(MARKER)).mode,'signed-out');assert.equal(values.has(TOKEN),false);
  assert.notEqual((await vault.inspect()).kind,'password');
 }

 // A native prompt canceled after invalidation also leaves a tombstone and
 // never restores the plain credential.
 {
  const values=new Map([[TOKEN,'plain-a'],[MARKER,plainMarker('account-a')]]),read=gate();let current=true;
  const storage=makeStorage(values);storage.getItemAsync=async key=>{if(key===PROTECTED)return new Promise((resolve,reject)=>{read.resolve=resolve;read.reject=reject;});return values.has(key)?values.get(key):null;};
  const vault=new NativeSessionVault(storage,options),pending=vault.enable('plain-a','account-a','Confirm Face ID',()=>current);
  for(let i=0;i<20&&!read.reject;i++)await tick();assert.equal(typeof read.reject,'function');
  current=false;read.reject(Object.assign(new Error('Face ID canceled'),{code:'AUTHENTICATION_CANCELED'}));await assert.rejects(pending);
  assert.equal(JSON.parse(values.get(MARKER)).mode,'signed-out');assert.equal(values.has(TOKEN),false);
  assert.notEqual((await vault.inspect()).kind,'password');
 }

 // Turning Face ID off has multiple asynchronous commit points. Lifecycle
 // invalidation during either the plain-token write or final plain-marker
 // write must be followed by a signed-out tombstone and full cleanup.
 for(const delayedKey of [TOKEN,MARKER]){
  const values=new Map([[MARKER,lockedMarker('account-a')],[PROTECTED,protectedSession('protected-a','account-a')]]),write=gate();let current=true;
  const storage=makeStorage(values);const set=storage.setItemAsync.bind(storage);
  storage.setItemAsync=async(key,value)=>{if(key===delayedKey&&(key!==MARKER||JSON.parse(value).mode==='plain')){await new Promise(resolve=>{write.resolve=resolve;});}return set(key,value);};
  const vault=new NativeSessionVault(storage,options),pending=vault.disable('Turn off Face ID',()=>current);
  for(let i=0;i<30&&!write.resolve;i++)await tick();assert.equal(typeof write.resolve,'function',`disable reaches delayed ${delayedKey} write`);
  current=false;write.resolve();await assert.rejects(pending);
  assert.equal(JSON.parse(values.get(MARKER)).mode,'signed-out',`${delayedKey} race leaves tombstone`);
  assert.equal(values.has(TOKEN),false,`${delayedKey} race removes plain token`);assert.equal(values.has(PROTECTED),false);
  assert.notEqual((await vault.inspect()).kind,'password');
 }

 // A canceled opt-in normally rolls back to the existing ordinary session.
 // If backgrounding begins during that rollback's token write, the predicate
 // must be rechecked after the await and the partial rollback must be cleared.
 {
  const values=new Map([[TOKEN,'plain-a'],[MARKER,plainMarker('account-a')]]),rollbackWrite=gate();let current=true;
  const storage=makeStorage(values),set=storage.setItemAsync.bind(storage);
  storage.setItemAsync=async(key,value)=>{if(key===TOKEN)await new Promise(resolve=>{rollbackWrite.resolve=resolve;});return set(key,value);};
  storage.getItemAsync=async key=>{if(key===PROTECTED)throw Object.assign(new Error('Face ID canceled'),{code:'AUTHENTICATION_CANCELED'});return values.has(key)?values.get(key):null;};
  const vault=new NativeSessionVault(storage,options),pending=vault.enable('plain-a','account-a','Confirm Face ID',()=>current);
  for(let i=0;i<30&&!rollbackWrite.resolve;i++)await tick();assert.equal(typeof rollbackWrite.resolve,'function','canceled enrollment reaches delayed rollback token write');
  current=false;rollbackWrite.resolve();await assert.rejects(pending);
  assert.equal(JSON.parse(values.get(MARKER)).mode,'signed-out');assert.equal(values.has(TOKEN),false);assert.equal(values.has(PROTECTED),false);
  assert.notEqual((await vault.inspect()).kind,'password');
 }

 // Replay enrollment cancellation through the actual App callback, then mount
 // again as a fresh process. No plain rollback may appear or auto-restore.
 const newUser={id:'enrollment-account',onboarding_required:false,access:{can_drive:false,can_request:true,is_staff:false}};
 await mount({[MARKER]:JSON.stringify({mode:'signed-out',origin:ORIGIN})},{serverUser:newUser});
 await nodes(tree,'PhoneAuth')[0].props.onAuthenticated({token:'enrollment-token',user:newUser,onboarding_required:false});await settle();
 press('communityProfile');await settle();const profile=nodes(tree,'Community')[0];const setting=profile.props.profileExtra;
 assert.equal(setting.props.enabled,false);protectedGate=gate();
 const toggle=nodes(setting.type(setting.props),'Pressable').find(node=>node.props.testID==='face-id-toggle');toggle.props.onPress();render();
 for(let i=0;i<30&&!protectedGate.reject;i++)await tick();assert.equal(typeof protectedGate.reject,'function','App enrollment reaches native confirmation read');
 emit('background');await settle();protectedGate.reject(Object.assign(new Error('Face ID canceled'),{code:'AUTHENTICATION_CANCELED'}));await settle();
 assert.equal(JSON.parse(stored.get(MARKER)).mode,'signed-out','App background cancels enrollment with tombstone');assert.equal(stored.has(TOKEN),false);
 unmount();
 await mount(Object.fromEntries(stored));
 assert.equal(apiCalls.filter(call=>call.kind==='bootstrap').length,0,'restart after enrollment race does not bootstrap a session');
 assert.equal(apiCalls.filter(call=>call.kind==='state').length,0);assert.equal(nodes(tree,'Pressable').some(node=>text(node)==='voiceEntry'),false);
 assert.notEqual((await imports['./nativeSession'].sessionVault.inspect()).kind,'password');unmount();
}

async function testApiGenerationGuards(){
 let fetchImpl,requests=[];
 const compiled=compile('api.ts'),apiModule={exports:{}};
 vm.runInNewContext(compiled,{module:apiModule,exports:apiModule.exports,require:name=>{if(name==='./voice/transport')return{createVoiceOperation(){return{};}};throw Error(`unexpected API import ${name}`);},process:{env:{EXPO_PUBLIC_API_URL:ORIGIN}},URL,fetch:(...args)=>fetchImpl(...args),setTimeout,clearTimeout,AbortController,FormData:undefined,Error,JSON,Object,String,Promise});
 const {Api}=apiModule.exports;assert.equal(typeof Api,'function');
 const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
 const api=new Api('old-token');
 fetchImpl=(url,options)=>{requests.push({url,options});return new Promise(resolve=>{requests.at(-1).resolve=resolve;});};
 const first=api.request('/api/state');await tick();assert.equal(requests[0].options.headers.Authorization,'Bearer old-token');api.token='new-token';requests[0].resolve({ok:false,status:401,json:async()=>({code:'old_401'})});
 await assert.rejects(first,error=>error.code==='ESESSION_CHANGED','a delayed old-account 401 is discarded before JSON handling');

 const staleAccountData=api.request('/api/bootstrap');await tick();api.token='new-account-token';requests[1].resolve({ok:true,status:200,json:async()=>({user:{id:'old-account'}})});
 await assert.rejects(staleAccountData,error=>error.code==='ESESSION_CHANGED','a successful old-account payload is never returned to the new account');

 const jsonGate=deferred();fetchImpl=async()=>({ok:false,status:401,json:()=>jsonGate.promise});api.token='old-token-2';const second=api.request('/api/state');await tick();await tick();api.token='new-token-2';jsonGate.resolve({code:'old_json_401'});
 await assert.rejects(second,error=>error.code==='ESESSION_CHANGED','a response whose JSON is pending cannot affect a new account');
 assert.equal(requests[0].options.headers.Authorization,'Bearer old-token','old request retained only its original bearer');
}

async function testPasswordFallbackRetry(){
 const user={id:'fallback-account',onboarding_required:false,access:{can_drive:false,can_request:true,is_staff:false}};
 await mount({[MARKER]:JSON.stringify({mode:'signed-out',origin:ORIGIN})},{serverUser:user,apiMode:{loginError:{status:401,code:'invalid_credentials'}}});
 const phone=nodes(tree,'PhoneAuth')[0];assert.ok(phone,'signed-out user starts at normal phone entry');phone.props.onLegacy();render();
 const legacyAccount=nodes(tree,'TextInput').find(node=>node.props.testID==='legacy-account-id');assert.ok(legacyAccount,'staff/test access has an explicitly labeled account ID field');assert.equal(legacyAccount.props.value,'','account ID starts blank');
 assert.equal(nodes(tree,'Pressable').filter(node=>['accountDriver','accountPassenger','accountPassenger2','accountAdmin'].includes(text(node))).length,0,'legacy sign-in has no assumed-identity role presets');
 legacyAccount.props.onChangeText('  staff.test+fixture 42  ');render();
 let password=nodes(tree,'TextInput').find(node=>node.props.accessibilityLabel==='password');assert.ok(password);password.props.onChangeText('wrong-password');render();press('signin');await settle();
 assert.equal(nodes(tree,'Pressable').some(node=>text(node)==='voiceEntry'),false,'invalid legacy login never opens private content');
 assert.ok(text(tree).includes('invalidCredentials'),'invalid legacy credentials show the existing error');
 assert.ok(apiCalls.some(call=>call.kind==='login'&&call.account==='staff.test+fixture 42'&&call.password==='wrong-password'),'invalid login also uses the explicitly entered, outer-trimmed account ID');
 password=nodes(tree,'TextInput').find(node=>node.props.accessibilityLabel==='password');assert.equal(password.props.value,'','failed legacy login clears password');

 apiMode.loginError=null;apiMode.loginResult={token:'fallback-valid-token',user};
 const accountAfterFailure=nodes(tree,'TextInput').find(node=>node.props.testID==='legacy-account-id');accountAfterFailure.props.onChangeText('  staff.test+fixture 42  ');render();
 password=nodes(tree,'TextInput').find(node=>node.props.accessibilityLabel==='password');password.props.onChangeText('valid-password');render();press('signin');await settle();
 assert.ok(apiCalls.some(call=>call.kind==='login'&&call.account==='staff.test+fixture 42'&&call.password==='valid-password'),'submit trims only outer account ID whitespace and uses the exact entered ID');
 assert.ok(apiCalls.some(call=>call.kind==='bootstrap'&&call.token==='fallback-valid-token'));
 assert.ok(apiCalls.some(call=>call.kind==='state'&&call.token==='fallback-valid-token'));
 assert.ok(nodes(tree,'Pressable').some(node=>text(node)==='voiceEntry'),'valid fallback retry reaches authenticated home');
 assert.equal(JSON.parse(stored.get(MARKER)).mode,'plain');assert.equal(JSON.parse(stored.get(MARKER)).accountId,'fallback-account');
 assert.equal(stored.has(PROTECTED),false,'normal fallback login does not enable Face ID');unmount();
}

(async()=>{await testAppFlow();await testEnrollmentInvalidation();await testRacesAndFailClosed();await testApiGenerationGuards();await testPasswordFallbackRetry();console.log('PASS Face ID app integration: locked startup, explicit unlock, cancellation, background lock, profile setting, logout tombstone, delayed unlock/background, invalid storage, server 401 purge, and account isolation.');console.log('PASS lifecycle mutation races: invalidated enrollment, disable during plain-token/final-marker writes, and cancellation during delayed plain rollback all end signed out.');console.log('PASS production API generation guards: late old-token responses and 401 JSON cannot affect a replacement account. SecureStore, Face ID, AppState and server behavior are fixtures; no physical-device claim.');console.log('PASS legacy password fallback: invalid credentials stay on the sign-in form with cleared password, then a valid retry restores the normal session.');})().catch(error=>{console.error(error);process.exitCode=1;});

function load(file,requireImpl){const m={exports:{}};vm.runInNewContext(compile(file),{module:m,exports:m.exports,require:requireImpl||(()=>({})),Date,URL,setInterval,clearInterval});return m.exports;}
