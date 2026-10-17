// Native session vault behavioral checks. SecureStore and Face ID are fixtures;
// these tests do not prove behavior on a physical iOS device.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const source = fs.readFileSync(path.join(__dirname, '../src/nativeSession.ts'), 'utf8');
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const moduleFixture = { exports: {} };
const imports = {
  'expo-secure-store': {
    WHEN_PASSCODE_SET_THIS_DEVICE_ONLY: 'when-passcode-set-this-device-only',
    AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY: 'after-first-unlock-this-device-only',
    canUseBiometricAuthentication: () => true,
  },
  'expo-local-authentication': {
    AuthenticationType: { FACIAL_RECOGNITION: 2 },
    hasHardwareAsync: async () => true,
    isEnrolledAsync: async () => true,
    supportedAuthenticationTypesAsync: async () => [2],
  },
  'react-native': { Platform: { OS: 'ios' } },
  './api': { API_BASE: 'https://fixture.invalid' },
};
vm.runInNewContext(code, {
  module: moduleFixture,
  exports: moduleFixture.exports,
  require(name) { assert.ok(imports[name], `unexpected import: ${name}`); return imports[name]; },
  JSON, Promise, Error, Object, String, Boolean, Array,
});
const { NativeSessionVault, sessionVault } = moduleFixture.exports;
assert.equal(typeof NativeSessionVault, 'function', 'exports NativeSessionVault');
assert.ok(sessionVault instanceof NativeSessionVault, 'exports the configured native sessionVault factory');

const LEGACY = 'routeShareToken';
const MARKER = 'seatpal.session.mode.v1';
const PROTECTED = 'seatpal.session.biometric.v1';
const ORIGIN = 'https://fixture.invalid';
const marker = (mode, accountId, origin = ORIGIN) => JSON.stringify({ mode, origin, ...(accountId == null ? {} : { accountId }) });
const envelope = (token, accountId, origin = ORIGIN) => JSON.stringify({ token, accountId, origin });
const tick = () => new Promise(resolve => setImmediate(resolve));

function fixture(seed = {}, options = {}) {
  const values = new Map(Object.entries(seed));
  const reads = [], writes = [], deletes = [];
  const fail = new Map();
  const delayedEnableRead = { resolve: null };
  const storage = {
    async getItemAsync(key, opts) {
      reads.push({ key, opts });
      const error = fail.get(`get:${key}`); if (error) throw error;
      if (key === PROTECTED && options.delayProtectedRead) await new Promise(resolve => { delayedEnableRead.resolve = resolve; });
      return values.has(key) ? values.get(key) : null;
    },
    async setItemAsync(key, value, opts) {
      writes.push({ key, value, opts });
      const error = fail.get(`set:${key}`); if (error) throw error;
      values.set(key, value);
    },
    async deleteItemAsync(key, opts) {
      deletes.push({ key, opts });
      const error = fail.get(`delete:${key}`); if (error) throw error;
      values.delete(key);
    },
  };
  const prompts = [];
  const config = {
    apiOrigin: ORIGIN,
    isIOS: true,
    supportsFaceID: async () => options.available !== false,
    protectedOptions: { keychainService: 'seatpal.biometric.session', requireAuthentication: true, keychainAccessible: 'when-passcode-set-this-device-only' },
  };
  const vault = new NativeSessionVault(storage, config);
  return { vault, values, reads, writes, deletes, fail, prompts, storage, options, config, delayedEnableRead };
}

async function run() {
  // A saved ordinary session is recoverable, but never writes a password.
  {
    const f = fixture();
    await f.vault.save('token-a', 'account-a');
    assert.equal(f.values.get(LEGACY), 'token-a');
    assert.equal(JSON.parse(f.values.get(MARKER)).mode, 'plain');
    assert.equal(JSON.parse(f.values.get(MARKER)).accountId, 'account-a');
    assert.equal(f.values.has(PROTECTED), false);
    assert.equal((await f.vault.inspect()).kind, 'password');
    assert.deepEqual({ ...await f.vault.inspect() }, { kind: 'password', token: 'token-a', accountId: 'account-a' });
    assert.ok(![...f.values.values()].some(value => String(value).includes('password')));
  }

  // Legacy migration may read an unmarked token. Locked, signed-out, malformed,
  // and wrong-origin metadata must never fall through to that legacy token.
  {
    const f = fixture({ [LEGACY]: 'legacy-token' });
    assert.deepEqual({ ...await f.vault.inspect() }, { kind: 'password', token: 'legacy-token', accountId: null });
    for (const value of [marker('locked', 'account-a'), marker('signed-out')]) {
      const blocked = fixture({ [LEGACY]: 'must-not-restore', [MARKER]: value });
      assert.notEqual((await blocked.vault.inspect().catch(() => ({ kind: 'error' }))).kind, 'password');
      assert.equal(blocked.reads.some(read => read.key === LEGACY), false, `did not read legacy token for marker ${value}`);
    }
    for (const value of ['{bad-json', marker('plain', 'account-a', 'https://other.invalid')]) {
      const blocked = fixture({ [LEGACY]: 'must-not-restore', [MARKER]: value });
      await assert.rejects(blocked.vault.inspect(), /saved_session_missing/);
      assert.equal(blocked.reads.some(read => read.key === LEGACY), false, `did not read legacy token for invalid marker ${value}`);
    }
  }

  // Face ID availability gates enrollment. Enrollment writes a lock before the
  // authenticated protected read, then removes the plain token only on success.
  {
    const f = fixture({ [LEGACY]: 'token-a', [MARKER]: marker('plain', 'account-a') }, { available: false });
    assert.equal(await f.vault.available(), false);
    await assert.rejects(f.vault.enable('token-a', 'account-a', 'Confirm Face ID'));
    assert.equal(JSON.parse(f.values.get(MARKER)).mode, 'plain');
    assert.equal(f.values.get(LEGACY), 'token-a');
  }
  {
    const f = fixture({ [LEGACY]: 'token-a', [MARKER]: marker('plain', 'account-a') });
    await f.vault.enable('token-a', 'account-a', 'Confirm Face ID');
    assert.equal(JSON.parse(f.values.get(MARKER)).mode, 'locked');
    assert.equal(f.values.has(LEGACY), false);
    assert.deepEqual({ ...await f.vault.inspect() }, { kind: 'locked' });
    const protectedValue = JSON.parse(f.values.get(PROTECTED));
    assert.deepEqual({ ...protectedValue }, { token: 'token-a', accountId: 'account-a', origin: ORIGIN });
    assert.ok(f.writes.some(w => w.key === PROTECTED && w.opts?.requireAuthentication === true));
    assert.ok(f.writes.some(w => w.key === PROTECTED && w.opts?.keychainAccessible === 'when-passcode-set-this-device-only'));
    assert.ok(f.reads.some(r => r.key === PROTECTED && r.opts?.requireAuthentication === true), 'enrollment confirms with authenticated native read');
  }

  // Cancel, unavailable/malformed protected data, or wrong account/origin all
  // keep the vault locked and require normal login.
  {
    const cases = [
      {},
      { [PROTECTED]: '{broken' },
      { [PROTECTED]: envelope('', 'account-a') },
      { [PROTECTED]: envelope('token-a', 'account-b') },
      { [PROTECTED]: envelope('token-a', 'account-a', 'https://other.invalid') },
    ];
    for (const protectedData of cases) {
      const f = fixture({ [MARKER]: marker('locked', 'account-a'), ...protectedData });
      const result = await f.vault.unlock('Unlock SeatPal').catch(() => null);
      assert.equal(result, null);
      assert.notEqual((await f.vault.inspect()).kind, 'password');
      assert.equal(f.reads.some(r => r.key === LEGACY), false);
    }
    const canceled = fixture({ [MARKER]: marker('locked', 'account-a'), [PROTECTED]: envelope('token-a', 'account-a') });
    const authError = new Error('authentication canceled');
    canceled.fail.set(`get:${PROTECTED}`, authError);
    await assert.rejects(canceled.vault.unlock('Unlock SeatPal'), error => error === authError);
    assert.deepEqual({ ...await canceled.vault.inspect() }, { kind: 'locked' });
    assert.equal(canceled.reads.some(r => r.key === LEGACY), false, 'canceled Face ID never reads the plain token');
  }

  // Disable requires an authenticated protected read and restores the ordinary
  // session only after that confirmation.
  {
    const f = fixture({ [MARKER]: marker('locked', 'account-a'), [PROTECTED]: envelope('token-a', 'account-a') });
    await f.vault.disable('Turn off Face ID');
    assert.equal(f.values.get(LEGACY), 'token-a');
    assert.equal(JSON.parse(f.values.get(MARKER)).mode, 'plain');
    assert.equal(f.values.has(PROTECTED), false);
    assert.ok(f.reads.some(r => r.key === PROTECTED && r.opts?.requireAuthentication === true));
  }

  // Forget establishes a signed-out tombstone before key cleanup. Cleanup
  // errors must not make inspect restore a stale credential.
  {
    const f = fixture({ [LEGACY]: 'stale-token', [MARKER]: marker('plain', 'account-a'), [PROTECTED]: envelope('old', 'account-a') });
    f.fail.set(`delete:${PROTECTED}`, new Error('keychain cleanup failed'));
    await assert.rejects(f.vault.forget());
    assert.equal(JSON.parse(f.values.get(MARKER)).mode, 'signed-out');
    assert.notEqual((await f.vault.inspect()).kind, 'password');
  }
  {
    const f = fixture({ [LEGACY]: 'stale-token', [MARKER]: marker('plain', 'account-a') });
    await f.vault.forget();
    assert.equal(JSON.parse(f.values.get(MARKER)).mode, 'signed-out');
    assert.equal(f.values.has(LEGACY), false);
    assert.notEqual((await f.vault.inspect()).kind, 'password');
  }

  // A normal save for a different account removes the prior protected restore.
  {
    const f = fixture({ [LEGACY]: 'old-token', [MARKER]: marker('locked', 'account-a'), [PROTECTED]: envelope('old-token', 'account-a') });
    await f.vault.save('new-token', 'account-b');
    assert.equal(f.values.has(PROTECTED), false);
    assert.deepEqual({ ...await f.vault.inspect() }, { kind: 'password', token: 'new-token', accountId: 'account-b' });
  }

  // Failed metadata or credential writes cannot produce a restorable plain
  // token. Failed authenticated enrollment rolls back to ordinary mode only
  // when that rollback is complete.
  {
    const f = fixture();
    f.fail.set(`set:${MARKER}`, new Error('metadata write failed'));
    await assert.rejects(f.vault.save('token-a', 'account-a'));
    assert.notEqual((await f.vault.inspect()).kind, 'password');
  }
  {
    const f = fixture();
    f.fail.set(`set:${LEGACY}`, new Error('plain credential write failed'));
    await assert.rejects(f.vault.save('token-a', 'account-a'));
    assert.notEqual((await f.vault.inspect()).kind, 'password');
  }
  {
    const f = fixture({ [LEGACY]: 'token-a', [MARKER]: marker('plain', 'account-a') });
    f.fail.set(`set:${PROTECTED}`, new Error('protected write failed'));
    await assert.rejects(f.vault.enable('token-a', 'account-a', 'Confirm Face ID'));
    assert.equal(JSON.parse(f.values.get(MARKER)).mode, 'plain');
    assert.equal(f.values.get(LEGACY), 'token-a');
    assert.notEqual((await f.vault.inspect()).kind, 'locked');
  }

  // Calls racing a protected read cannot resurrect credentials after a later
  // save/clear. The vault itself serializes writes; app logout also invalidates
  // any separately held unlock result and is covered by integration checks.
  {
    const f = fixture({ [LEGACY]: 'token-a', [MARKER]: marker('plain', 'account-a') }, { delayProtectedRead: true });
    // The storage fixture pauses the protected read until both mutations have
    // been started, then lets the queue settle in invocation order.
    const enable = f.vault.enable('token-a', 'account-a', 'Confirm Face ID');
    for (let i = 0; i < 20 && !f.delayedEnableRead.resolve; i++) await tick();
    assert.equal(typeof f.delayedEnableRead.resolve, 'function', 'enable reached the delayed protected read');
    const forget = f.vault.forget();
    f.delayedEnableRead.resolve?.();
    await Promise.all([enable.catch(() => {}), forget]);
    assert.equal(JSON.parse(f.values.get(MARKER)).mode, 'signed-out');
    assert.notEqual((await f.vault.inspect()).kind, 'password');
  }

  console.log('PASS native session vault: legacy/plain restore, fail-closed marker/origin handling, Face ID enrollment confirmation, canceled and invalid unlock, authenticated disable, signed-out tombstone cleanup, account isolation, storage failures, and delayed-operation logout race. SecureStore/Face ID are mocks; physical-device behavior is not verified.');
}

run().catch(error => { console.error(error); process.exitCode = 1; });
