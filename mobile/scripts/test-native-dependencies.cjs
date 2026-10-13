'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const semver = require('semver');
const code = fs.readFileSync(path.join(__dirname, 'check-native-dependencies.cjs'), 'utf8');
const root = path.resolve('/fixture/route-share');
const ranges = {'expo-asset':'~12.0.13','expo-constants':'~18.0.14','expo-font':'~14.0.12'};
function run(overrides = {}) {
  const packages = {'expo':{version:'54.0.37'},'expo-asset':{version:'12.0.13'},'expo-constants':{version:'18.0.14'},'expo-font':{version:'14.0.12'},...overrides};
  const app = {dependencies:{expo:'~54.0.0','expo-font':'~14.0.12','unlisted-js-library':'1.0.0'}};
  const files = {[path.join(root,'package.json')]:app};
  for (const [name,value] of Object.entries(packages)) if (value) files[path.join(root,'node_modules',name,'package.json')] = value;
  files[path.join(root,'node_modules/expo/bundledNativeModules.json')] = ranges;
  const fakeRequire = name => {assert.equal(name,'semver'); return semver;};
  fakeRequire.resolve = name => {
    const target = path.join(root,'node_modules',name);
    if (!(target in files)) throw new Error(`Cannot find ${name}`);
    return target;
  };
  const module = {exports:{}};
  vm.runInNewContext(code,{module,require:name=>{
    if(name==='node:fs')return {readFileSync:file=>{assert.ok(file in files,`unexpected read ${file}`);return JSON.stringify(files[file]);}};
    if(name==='node:path')return path;
    if(name==='node:module')return {createRequire:file=>{assert.equal(file,path.join(root,'package.json'));return fakeRequire;}};
    throw new Error(`unexpected import ${name}`);
  }});
  return module.exports.checkNativeDependencies(root);
}
assert.equal(run().failures.length,0,'compatible tree passes');
assert.equal(run().checked,3,'includes implicit asset/constants; ignores packages outside SDK catalog');
const skew=run({'expo-asset':{version:'57.0.19'},'expo-constants':{version:'57.0.21'}});
assert.equal(skew.failures.length,2);
assert.ok(skew.failures[0].includes('expected ~12.0.13')&&skew.failures[0].includes('installed 57.0.19')&&skew.failures[0].includes(path.join(root,'node_modules/expo-asset/package.json')));
assert.equal(run({'expo-font':{version:'15.0.0'}}).failures.length,1,'declared SDK dependency checked');
assert.ok(run({'expo-asset':null}).failures[0].includes('cannot read installed package'),'missing package fails');
assert.ok(run({'expo-asset':{version:'bogus'}}).failures[0].includes('installed bogus'),'invalid version fails');
console.log('PASS 7 native dependency guard checks; synthetic resolutions only, no package installation or native-linking claim.');
