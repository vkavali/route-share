const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const script = fs.readFileSync(require('node:path').resolve(__dirname, '../static/root-entry.js'), 'utf8');

function run(pathname, search = '', hash = '', options = {}) {
  const navigations = [];
  const context = {
    location: { pathname, search, hash, replace: value => navigations.push(value) },
    URLSearchParams,
    ...(options.hasDisplayMode ? { matchMedia: query => ({ matches: query === '(display-mode: standalone)' && options.displayMode }) } : {}),
    ...(options.hasNavigator ? { navigator: { standalone: options.iosStandalone } } : {}),
  };
  vm.runInNewContext(script, context);
  return navigations;
}

assert.deepEqual(run('/'), ['/welcome?lang=en']);
assert.deepEqual(run('/', '?lang=te'), ['/welcome?lang=te']);
assert.deepEqual(run('/', '?lang=hi'), ['/welcome?lang=en']);
assert.deepEqual(run('/', '?app=1'), [], 'installed PWA app entry remains on app shell');
assert.deepEqual(run('/', '?lang=en', '#/login'), [], 'explicit login hash remains on app shell');
assert.deepEqual(run('/', '', '#/trip/booking-123'), [], 'app deep links remain on app shell');
assert.deepEqual(run('/', '', '#/login~sp1:eyJ2IjoxfQ'), [], 'landing handoff fragment remains on app shell');
assert.deepEqual(run('/', '', '', { hasDisplayMode: true, displayMode: true }), [], 'standalone PWA launch remains on app shell');
assert.deepEqual(run('/', '', '', { hasNavigator: true, iosStandalone: true }), [], 'installed iOS web app launch remains on app shell');
assert.deepEqual(run('/', '', '', { hasDisplayMode: true, displayMode: false, hasNavigator: true, iosStandalone: false }), ['/welcome?lang=en']);
assert.deepEqual(run('/welcome', '?lang=en'), [], 'landing paths are not redirected');

console.log('root entry routing tests passed');
