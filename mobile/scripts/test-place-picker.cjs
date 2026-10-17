// Bounded interaction regression checks against the real native component, without a device or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const compile = name => ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src', name), 'utf8'), {
  compilerOptions: {jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}
}).outputText;
const load = (code, requireMock) => { const mod = {exports: {}}; vm.runInNewContext(code, {
  module: mod, exports: mod.exports, require: requireMock, setTimeout, clearTimeout, Error
}); return mod.exports; };
const selection = load(compile('placeSelection.ts'), () => ({}));
const theme = load(compile('SeatPalTheme.ts'), () => ({}));
const pickerCode = compile('MapPicker.tsx');
const flush = () => new Promise(setImmediate);
const deferred = () => {let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;});return {promise,resolve,reject};};
const place = (label,lat=17,lon=78) => ({label,lat,lon,name:label,address:`${label}, City, India`});
function harness(extra={}) {
  let slots=[], index=0, tree, effects=[], stateWrites=0;
  const requests=[], chosen=[], errors=[], injections=[], gps=[];
  const React = {
    createElement:(type,props,...children)=>({type,props:props||{},children}),
    useRef:value=>{const i=index++;return slots[i]||(slots[i]={current:value});},
    useState:value=>{const i=index++;if(!(i in slots))slots[i]=typeof value==='function'?value():value;
      return [slots[i],value=>{stateWrites++;slots[i]=typeof value==='function'?value(slots[i]):value;}];},
    useMemo:fn=>{const i=index++;if(!(i in slots))slots[i]=fn();return slots[i];},
    useEffect:fn=>{const i=index++;if(!(i in slots)){slots[i]=true;effects.push(fn());}}
  };React.default=React;
  const native={StyleSheet:{create:x=>x},Keyboard:{dismiss:()=>{}},Linking:{openURL:()=>{}},
    View:'View',TextInput:'Input',Pressable:'Button',ScrollView:'Scroll',ActivityIndicator:'Spinner'};
  const Component=load(pickerCode, name=>name==='react'?React:name==='react-native'?native:
    name==='react-native-webview'?{WebView:'Map'}:name==='expo-location'?{
      Accuracy:{High:1},requestForegroundPermissionsAsync:async()=>({granted:true}),
      getCurrentPositionAsync:()=>{const d=deferred();gps.push(d);return d.promise;}
    }:name==='./placeSelection'?selection:name==='./translation'?{T:(_,key)=>key}:
      name==='./SeatPalLoader'?{SeatPalLoader:'SeatPalLoader'}:name==='./NativeTypography'?{AppText:'Text'}:
      name==='./SeatPalTheme'?theme:{LEAFLET_CSS:'',LEAFLET_JS:''}).MapPicker;
  const props={lang:'en',api:{request:url=>{const d=deferred();requests.push({url,...d});return d.promise;}},
    onChoose:p=>chosen.push(p),onCancel:()=>{},onFailure:e=>errors.push(e),...extra};
  const nodes=(node,type)=>!node||typeof node!=='object'?[]:[...(node.type===type?[node]:[]),...(node.children||[]).flat(Infinity).flatMap(n=>nodes(n,type))];
  const text=node=>!node?'':typeof node==='string'?node:(node.children||[]).flat(Infinity).map(text).join('');
  const render=()=>{index=0;tree=Component(props);const map=nodes(tree,'Map')[0];map.props.ref.current={injectJavaScript:s=>injections.push(s)};return tree;};
  render();
  return {requests,chosen,errors,injections,gps,render,
    input:value=>{nodes(tree,'Input')[0].props.onChangeText(value);render();},
    search:()=>{nodes(tree,'Input')[0].props.onSubmitEditing();render();},
    press:label=>{const button=nodes(tree,'Button').find(n=>text(n)===label);assert.ok(button,`button ${label}`);assert.ok(!button.props.disabled,`${label} enabled`);button.props.onPress();render();},
    confirmDisabled:()=>Boolean(nodes(tree,'Button').find(n=>text(n)==='mapUsePoint').props.disabled),
    texts:()=>nodes(tree,'Text').map(text),
    loaders:()=>nodes(tree,'SeatPalLoader'),
    resultLabels:()=>nodes(tree,'Button').filter(n=>n.props.accessibilityState).map(text),
    map:message=>{nodes(tree,'Map')[0].props.onMessage({nativeEvent:{data:JSON.stringify(message)}});render();},
    loadEnd:()=>{nodes(tree,'Map')[0].props.onLoadEnd();render();},
    dispose:()=>{effects.forEach(fn=>fn&&fn());},writes:()=>stateWrites,
  };
}
(async()=>{
 let checks=0;
 const h=harness({initialPoint:place('Old pickup')});
 h.input('Hyderabad');assert.ok(h.confirmDisabled());assert.equal(h.requests.length,0);checks+=2;
 h.search();h.search();assert.equal(h.requests.length,1);checks++;
 assert.equal(h.loaders().length,1);assert.equal(h.loaders()[0].props.label,'mapSearchLoading');assert.ok(!h.texts().includes('mapLocationBusy'));checks++;
 h.input('Vijayawada');h.search();h.requests[1].resolve({places:[place('Vijayawada')]});await flush();h.render();
 h.requests[0].resolve({places:[place('Hyderabad')]});await flush();h.render();
 assert.ok(h.resultLabels()[0].startsWith('Vijayawada'));assert.ok(h.confirmDisabled());checks+=2;
 h.press('VijayawadaVijayawada, City, India');assert.ok(!h.confirmDisabled());checks++;
 h.map({type:'ready'});h.loadEnd();assert.ok(h.injections.every(s=>!s.includes('Old pickup')));checks++;
 h.press('mapUsePoint');assert.equal(h.chosen[0].address,'Vijayawada, City, India');checks++;
 const a=harness({initialPoint:place('Old',17,78),initialQuery:'voice place'});
 assert.ok(a.confirmDisabled());assert.equal(a.requests.length,0);checks+=2;
 a.map({type:'ready'});assert.ok(a.injections.at(-1).includes('null,null'));checks++;
 a.input('Some place');a.search();a.map({type:'candidate',lat:16.5,lon:80.6});
 a.requests[0].resolve({places:[place('Late result')]});await flush();a.render();
 assert.equal(a.resultLabels().length,0);a.press('mapUsePoint');assert.equal(a.chosen[0].lat,16.5);checks+=2;
 const b=harness();b.input('Hyderabad');b.search();b.press('mapMyLocation');await flush();
 b.requests[0].resolve({places:[place('Late search')]});b.gps[0].resolve({coords:{latitude:15,longitude:79}});await flush();b.render();
 assert.equal(b.resultLabels().length,0);b.press('mapUsePoint');assert.equal(b.chosen[0].lat,15);checks+=2;
 const c=harness();c.press('mapMyLocation');await flush();c.map({type:'candidate',lat:14,lon:77});
 c.gps[0].resolve({coords:{latitude:15,longitude:79}});await flush();c.render();c.press('mapUsePoint');assert.equal(c.chosen[0].lat,14);checks++;
 const d=harness();d.map({type:'candidate',lat:14,lon:77});d.press('mapResolveAddress');
 d.requests[0].resolve({place:place('Nearby stop',14.1,77.1)});await flush();d.render();d.press('mapUsePoint');
 assert.equal(d.chosen[0].lat,14);assert.equal(d.chosen[0].lon,77);assert.equal(d.chosen[0].name,'Nearby stop');checks+=3;
 const e=harness();e.input('Empty query');e.search();e.requests[0].resolve({places:[]});await flush();e.render();
 assert.equal(e.loaders().length,0);assert.ok(e.texts().includes('mapSearchEmpty'));assert.ok(e.confirmDisabled());checks+=2;
 const f=harness();f.input('Failing query');f.search();f.requests[0].reject(new Error('offline'));await flush();f.render();
 assert.equal(f.loaders().length,0);assert.ok(f.texts().includes('mapSearchError'));assert.ok(f.confirmDisabled());checks+=2;
 const g=harness();g.input('Leaving picker');g.search();g.dispose();const before=g.writes();
 g.requests[0].resolve({places:[place('Late result')]});await flush();assert.equal(g.writes(),before);checks++;
 const k=harness({initialPoint:place('Old',17,78)});k.map({type:'candidate',lat:16,lon:80});k.map({type:'ready'});k.loadEnd();
 assert.ok(k.injections.every(s=>s.includes('(16,80)')));checks++;
 assert.equal(selection.normalizePlace({label:'Invalid',lat:null,lon:78}),null);checks++;
 assert.equal(selection.normalizePlace({label:'x'.repeat(240),lat:17,lon:78,address:'full address'}).label.length,120);checks++;
 console.log(`PASS ${checks} native picker state checks (mocked native rendering/GPS; no device or network claims).`);
})().catch(error=>{console.error(error);process.exitCode=1;});
