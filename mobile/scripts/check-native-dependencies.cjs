#!/usr/bin/env node
'use strict';

// Match installed JavaScript dependencies to this installation's Expo SDK.
// This catches incompatible auto-installed peers; it does not prove native linking.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');

function checkNativeDependencies(projectRoot) {
  const root = path.resolve(projectRoot);
  const resolveFromApp = createRequire(path.join(root, 'package.json'));
  const app = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
  const expoPath = resolveFromApp.resolve('expo/package.json');
  const expo = JSON.parse(fs.readFileSync(expoPath, 'utf8'));
  const ranges = JSON.parse(fs.readFileSync(path.join(path.dirname(expoPath), 'bundledNativeModules.json'), 'utf8'));
  const semver = resolveFromApp('semver');
  const names = new Set([...Object.keys(app.dependencies || {}), 'expo-asset', 'expo-constants']);
  const failures = [];
  let checked = 0;
  for (const name of names) {
    const expected = ranges[name];
    if (!expected) {
      if (name === 'expo-asset' || name === 'expo-constants') {
        failures.push(`${name}: missing compatibility range in Expo ${expo.version} bundledNativeModules.json (${expoPath}).`);
      }
      continue;
    }
    checked++;
    let resolved;
    try {
      resolved = resolveFromApp.resolve(`${name}/package.json`);
      const installed = JSON.parse(fs.readFileSync(resolved, 'utf8'));
      if (!semver.valid(installed.version) || !semver.satisfies(installed.version, expected)) {
        failures.push(`${name}: expected ${expected} for Expo ${expo.version}; installed ${installed.version || '(missing version)'}; resolved ${resolved}.`);
      }
    } catch (error) {
      failures.push(`${name}: expected ${expected} for Expo ${expo.version}; cannot read installed package${resolved ? ` at ${resolved}` : ` from ${root}`}: ${error.message}`);
    }
  }
  return {expoVersion: expo.version, checked, failures};
}

if (require.main === module) {
  if (process.argv.length > 2) {
    console.error('Usage: node scripts/check-native-dependencies.cjs (no options). Native Pods/provider registration still requires a native build check.');
    process.exitCode = 2;
  } else {
    try {
      const result = checkNativeDependencies(path.resolve(__dirname, '..'));
      if (result.failures.length) {
        console.error(`Native dependency preflight FAILED (${result.failures.length} incompatibilities):\n${result.failures.map(value => `- ${value}`).join('\n')}`);
        console.error('Align the listed packages with the installed Expo SDK, regenerate the lockfile and native dependencies, then rerun this check. No files were changed.');
        process.exitCode = 1;
      } else {
        console.log(`Native dependency preflight passed: ${result.checked} installed packages match Expo ${result.expoVersion}. Native registration and device startup remain separate checks.`);
      }
    } catch (error) {
      console.error(`Native dependency preflight could not run: ${error.message}`);
      process.exitCode = 2;
    }
  }
}

module.exports = {checkNativeDependencies};
