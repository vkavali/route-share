const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const moduleUrl = pathToFileURL(path.resolve(__dirname, '../static/landing-intent.js')).href;
  const { captureLandingIntent, consumeLandingIntent } = await import(moduleUrl);

function fixture(hash) {
  const values = new Map();
  const location = { hash, pathname: '/', search: '?lang=te' };
  const history = { state: { keep: true }, replaceState(state, _title, url) { this.url = url; } };
  const storage = {
    setItem(key, value) { values.set(key, value); },
    getItem(key) { return values.get(key) ?? null; },
    removeItem(key) { values.delete(key); },
    values,
  };
  return { location, history, storage };
}

function fragment(value) {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

const valid = fixture(`#/login~sp1:${fragment({ v: 1, intent: 'search', originLabel: '  కోకాపేట  ', destinationLabel: 'Airport' })}`);
const captured = captureLandingIntent(valid.location, valid.history, valid.storage, 1000);
assert.deepEqual(captured, { v: 1, intent: 'search', originLabel: 'కోకాపేట', destinationLabel: 'Airport' });
assert.equal(valid.history.url, '/?lang=te#/login');
assert.equal(consumeLandingIntent(valid.storage, 1001).originLabel, 'కోకాపేట');
assert.equal(consumeLandingIntent(valid.storage, 1002), null, 'handoff is consumed only once');

const expired = fixture(`#/login~sp1:${fragment({ v: 1, intent: 'offer', originLabel: 'Hyderabad' })}`);
captureLandingIntent(expired.location, expired.history, expired.storage, 1000);
assert.equal(consumeLandingIntent(expired.storage, 1000 + 15 * 60 * 1000), null, 'expired handoff is discarded');

for (const value of [
  { v: 2, intent: 'search' },
  { v: 1, intent: 'operations' },
]) {
  const bad = fixture(`#/login~sp1:${fragment(value)}`);
  captureLandingIntent(bad.location, bad.history, bad.storage, 1000);
  assert.equal(bad.history.url, '/?lang=te#/login', 'payload is stripped before routing even when invalid');
  assert.equal(consumeLandingIntent(bad.storage, 1001), null, 'invalid payload creates no usable handoff');
}

for (const [key, label] of [['originLabel', 'x'.repeat(121)], ['destinationLabel', 'bad\nlabel']]) {
  const labelOnly = fixture(`#/login~sp1:${fragment({ v: 1, intent: 'search', [key]: label })}`);
  captureLandingIntent(labelOnly.location, labelOnly.history, labelOnly.storage, 1000);
  const safe = consumeLandingIntent(labelOnly.storage, 1001);
  assert.equal(safe.intent, 'search');
  assert.equal(Object.hasOwn(safe, key), false, 'invalid labels are dropped');
}

const tooLong = fixture(`#/login~sp1:${'A'.repeat(4097)}`);
captureLandingIntent(tooLong.location, tooLong.history, tooLong.storage, 1000);
assert.equal(tooLong.history.url, '/?lang=te#/login');
assert.equal(consumeLandingIntent(tooLong.storage, 1001), null);

const ordinary = fixture('#/login');
assert.equal(captureLandingIntent(ordinary.location, ordinary.history, ordinary.storage, 1000), null);
assert.equal(ordinary.history.url, undefined, 'ordinary login link is unchanged');

const oldIntent = fixture(`#/login~sp1:${fragment({ v: 1, intent: 'search', originLabel: 'Old route' })}`);
captureLandingIntent(oldIntent.location, oldIntent.history, oldIntent.storage, 1000);
const malformedReplacement = { ...oldIntent.location, hash: '#/login~sp1:not-a-payload!' };
captureLandingIntent(malformedReplacement, oldIntent.history, oldIntent.storage, 1001);
assert.equal(consumeLandingIntent(oldIntent.storage, 1002), null, 'malformed new intent clears an older pending route');

const blocked = fixture(`#/login~sp1:${fragment({ v: 1, intent: 'search', originLabel: 'Safe fallback' })}`);
const throwingStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
assert.equal(captureLandingIntent(blocked.location, blocked.history, throwingStorage, 1000).intent, 'search');
assert.equal(consumeLandingIntent(throwingStorage, 1001), null, 'storage failure does not prevent ordinary login');

global.window = {};
Object.defineProperty(global.window, 'sessionStorage', { get() { throw new Error('blocked getter'); } });
const getterBlocked = fixture(`#/login~sp1:${fragment({ v: 1, intent: 'offer' })}`);
assert.equal(captureLandingIntent(getterBlocked.location, getterBlocked.history, undefined, 1000).intent, 'offer');
assert.equal(consumeLandingIntent(undefined, 1001), null, 'blocked sessionStorage getter is caught');
delete global.window;

console.log('landing-intent contract tests passed');

})();
