// First-use phone-auth copy and tester entry are exercised with mocked native primitives.
// No real identity provider, SMS transport, or credentials are used.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');

const source=fs.readFileSync(path.join(__dirname,'../src/PhoneAuthScreen.tsx'),'utf8');
const code=ts.transpileModule(source,{compilerOptions:{module:1,jsx:2,target:7}}).outputText;
const translateModule={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/generated/i18n.js'),'utf8'),{compilerOptions:{module:1,target:7}}).outputText,{module:translateModule,exports:translateModule.exports});
const themeModule={exports:{}};
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/SeatPalTheme.ts'),'utf8'),{compilerOptions:{module:1,target:7}}).outputText,{module:themeModule,exports:themeModule.exports});

let slots=[],cursor=0,dirty=false,tree,effects=[],props,legacyCalls=[],capabilityCalls=0;
const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>v===b[i]);
const React={
 createElement:(type,props,...children)=>({type,props:props||{},children}),
 useState:value=>{const i=cursor++;if(!(i in slots))slots[i]=value;return[slots[i],next=>{slots[i]=typeof next==='function'?next(slots[i]):next;dirty=true;}];},
 useRef:value=>{const i=cursor++;return slots[i]||(slots[i]={current:value});},
 useEffect:(fn,deps)=>{const i=cursor++;if(!slots[i]||!same(slots[i].deps,deps)){slots[i]={deps};effects.push(()=>{slots[i].cleanup=fn();});}}
};
React.default=React;
const native={StyleSheet:{create:value=>value},Linking:{openURL:async()=>{}}};
for(const name of ['ActivityIndicator','Image','Pressable','ScrollView','TextInput','View'])native[name]=name;
const imports={
 react:React,'react-native':native,'expo-crypto':{randomUUID:()=> 'fixture-id',getRandomBytesAsync:async n=>new Uint8Array(n)},
 './api':{API_BASE:'https://fixture.invalid'},'./SeatPalLoader':{SeatPalLoader:'SeatPalLoader'},'./NativeTypography':{AppText:'Text'},
 './SeatPalTheme':themeModule.exports,'./translation':{T:(lang,key)=>translateModule.exports.messages[lang]?.[key]||translateModule.exports.messages.en[key]||key}
};
const screenModule={exports:{}};
vm.runInNewContext(code,{module:screenModule,exports:screenModule.exports,require:name=>{if(name.startsWith('../assets/'))return name;assert.ok(imports[name],`Unexpected import: ${name}`);return imports[name];},Date,URL,setInterval:()=>1,clearInterval:()=>{}});
const PhoneAuthScreen=screenModule.exports.PhoneAuthScreen;
const nodes=(node,type)=>!node||typeof node!=='object'?[]:[...(node.type===type?[node]:[]),...(node.children||[]).flat(Infinity).flatMap(child=>nodes(child,type))];
const text=node=>!node?'':typeof node==='string'||typeof node==='number'?String(node):(node.children||[]).flat(Infinity).map(text).join('');
function render(){let count=0;do{dirty=false;cursor=0;tree=PhoneAuthScreen(props);const pending=effects;effects=[];pending.forEach(run=>run());assert.ok(++count<20,'render/effect loop');}while(dirty);}
async function settle(){await new Promise(setImmediate);render();await new Promise(setImmediate);render();}
function findById(id){return nodes(tree,'Pressable').find(node=>node.props.testID===id)||nodes(tree,'Text').find(node=>node.props.testID===id);}
function reset(capability){slots=[];effects=[];legacyCalls=[];capabilityCalls=0;props={lang:'en',profile:false,api:{phoneCapabilities:async()=>{capabilityCalls++;return capability;},phoneStart:async()=>{throw Error('phone start must not be called by first-use tests');},phoneVerify:async()=>{throw Error('phone verify must not be called by first-use tests');}},onAuthenticated:async()=>{},onProfileSaved:async()=>{},onLegacy:(...args)=>legacyCalls.push(args),onRecovery:()=>{},onSignOut:()=>{},onLanguage:()=>{}};render();}

(async()=>{
 reset({enabled:false});
 const initialTitle=nodes(tree,'Text').find(node=>node.props.testID==='phone-first-use-title');
 assert.ok(initialTitle,'first-use heading has a stable selector while capabilities load');
 const initialCopy=text(initialTitle).toLowerCase();
 assert.ok(!/create|register|registration/.test(initialCopy),'loading heading must not promise public signup');
 assert.ok(!text(tree).includes(translateModule.exports.messages.en.phoneProofOnly),'loading state must not describe the OTP flow before capability is known');
 assert.equal(nodes(tree,'Pressable').some(node=>node.props.testID==='phone-capability-retry'),false,'pending capability fetch must not show a dead Retry control');
 await settle();
 assert.equal(capabilityCalls,1);
 const title=nodes(tree,'Text').find(node=>node.props.testID==='phone-first-use-title');
 assert.ok(title,'first-use heading remains available after capability resolution');
 assert.ok(!/create|register|registration/.test(text(title).toLowerCase()),'disabled phone sign-in must not promise public signup');
 const unavailable=nodes(tree,'Text').find(node=>node.props.testID==='phone-signin-unavailable');
 assert.ok(unavailable,'disabled capability explains the unavailable member flow');
 assert.ok(!text(tree).includes(translateModule.exports.messages.en.phoneProofOnly),'unavailable state must not describe an OTP flow that is not offered');
 const card=nodes(tree,'View').find(node=>node.props.testID==='phone-auth-card');
 assert.ok(card,'auth card is selectable for placement assertions');
 const cardText=text(card);
 assert.match(cardText,/Member sign-in and registration are not currently open\./,'unavailable copy states the disabled behavior');
 const action=findById('phone-test-account-card-action');
 assert.ok(action,'unavailable state offers the in-card test-account path');
 assert.match(text(action),/Sign in with a test account/i);
 assert.ok(nodes(card,'Pressable').includes(action),'test-account action is inside the auth card');
 assert.equal(nodes(card,'TextInput').length,0,'first-use action does not expose account or password fields');
 action.props.onPress();
 assert.equal(legacyCalls.length,1,'existing legacy login callback is reached');
 assert.deepEqual(legacyCalls[0],[],'screen passes no credentials to the legacy login callback');

 reset({enabled:true,otp_length:6,terms_version:'fixture',privacy_version:'fixture',terms_url:'/terms',privacy_url:'/privacy'});
 await settle();
 const enabledCard=nodes(tree,'View').find(node=>node.props.testID==='phone-auth-card');
 assert.ok(enabledCard);
 assert.equal(nodes(enabledCard,'Pressable').some(node=>node.props.testID==='phone-test-account-card-action'),false,'enabled phone capability keeps the separate test-account action out of the card');
 const enabledTitle=nodes(enabledCard,'Text').find(node=>node.props.testID==='phone-first-use-title');
 assert.match(text(enabledTitle).toLowerCase(),/sign in or create|sign in.*account/,'enabled phone capability may retain the sign-in/create heading');
 assert.ok(text(enabledCard).includes(translateModule.exports.messages.en.phoneProofOnly),'enabled phone capability retains the OTP proof explanation');
 const phoneLabel=translateModule.exports.messages.en.phoneNumber;
 assert.ok(nodes(enabledCard,'TextInput').some(node=>node.props.accessibilityLabel===phoneLabel),'enabled phone capability retains its phone sign-in form');
 assert.equal(capabilityCalls,1);
 console.log('PASS native first-use auth: neutral loading and disabled headings, unavailable copy, in-card test-account action, existing credential-free legacy callback, and enabled-capability placement.');
})().catch(error=>{console.error(error);process.exitCode=1;});
