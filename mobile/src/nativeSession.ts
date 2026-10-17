import * as SecureStore from 'expo-secure-store';
import * as LocalAuthentication from 'expo-local-authentication';
import {Platform} from 'react-native';
import {API_BASE} from './api';

const TOKEN = 'routeShareToken';
const MODE = 'seatpal.session.mode.v1';
const BIOMETRIC = 'seatpal.session.biometric.v1';
type StoreOptions = SecureStore.SecureStoreOptions;
type Storage = {
  getItemAsync(key: string, options?: StoreOptions): Promise<string | null>;
  setItemAsync(key: string, value: string, options?: StoreOptions): Promise<void>;
  deleteItemAsync(key: string, options?: StoreOptions): Promise<void>;
};
type Options = {apiOrigin: string; isIOS: boolean; supportsFaceID: () => Promise<boolean>; protectedOptions: StoreOptions};
type Marker = {mode: 'plain' | 'locked' | 'signed-out'; origin: string; accountId?: string};
export type SavedSession = {token: string; accountId: string | null};
export type SessionInspection = {kind: 'none'} | ({kind: 'password'} & SavedSession) | {kind: 'locked'};

export class NativeSessionError extends Error {
  constructor(public code: 'face_id_unavailable' | 'saved_session_missing' | 'session_storage_failed') {
    super(code);
    this.name = 'NativeSessionError';
  }
}

/** One remembered account per installation. Never stores a password or biometric data.
 * A durable marker is committed BEFORE removing credentials so failed deletes cannot
 * silently restore a signed-out session. Locked mode never falls back to the old key.
 */
export class NativeSessionVault {
  private tail: Promise<unknown> = Promise.resolve();
  constructor(private storage: Storage, private options: Options) {}

  private serial<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.tail.then(operation, operation);
    this.tail = result.catch(() => undefined);
    return result;
  }

  private protectedOptions(prompt?: string): StoreOptions {
    return {...this.options.protectedOptions, requireAuthentication: true,
      keychainService: 'com.seatpal.session.biometric.v1', ...(prompt ? {authenticationPrompt: prompt} : {})};
  }

  private async marker(): Promise<Marker | null> {
    const raw = await this.storage.getItemAsync(MODE);
    if (raw === null) return null; // One-time compatibility with existing native sessions.
    try {
      const value = JSON.parse(raw);
      if (!value || value.origin !== this.options.apiOrigin || !['plain', 'locked', 'signed-out'].includes(value.mode)
          || (value.mode !== 'signed-out' && (typeof value.accountId !== 'string' || !value.accountId))) {
        throw new Error('Invalid marker');
      }
      return value;
    } catch {
      // Unknown, damaged or other-environment metadata must not unlock the legacy token.
      throw new NativeSessionError('saved_session_missing');
    }
  }

  private mark(mode: Marker['mode'], accountId?: string): Promise<void> {
    return this.storage.setItemAsync(MODE, JSON.stringify({mode, origin: this.options.apiOrigin, ...(accountId ? {accountId} : {})}));
  }

  private async forgetStored(): Promise<void> {
    await this.mark('signed-out');
    // Keep the tombstone even after successful cleanup, including across app reinstall.
    const results = await Promise.allSettled([
      this.storage.deleteItemAsync(TOKEN),
      this.storage.deleteItemAsync(BIOMETRIC, this.protectedOptions()),
    ]);
    if (results.some(result => result.status === 'rejected')) throw new NativeSessionError('session_storage_failed');
  }

  private async assertCurrent(isCurrent: () => boolean): Promise<void> {
    if (!isCurrent()) {
      await this.forgetStored();
      throw new NativeSessionError('saved_session_missing');
    }
  }

  private async saveStored(token: string, accountId: string, isCurrent: () => boolean = () => true): Promise<void> {
    if (!token || !accountId) throw new NativeSessionError('saved_session_missing');
    await this.forgetStored();
    await this.assertCurrent(isCurrent);
    await this.storage.setItemAsync(TOKEN, token);
    await this.assertCurrent(isCurrent);
    await this.mark('plain', accountId);
    await this.assertCurrent(isCurrent);
  }

  available(): Promise<boolean> {
    if (!this.options.isIOS) return Promise.resolve(false);
    return this.options.supportsFaceID().catch(() => false);
  }

  inspect(): Promise<SessionInspection> {
    return this.serial(async () => {
      const marker = await this.marker();
      if (marker?.mode === 'signed-out') return {kind: 'none'};
      if (marker?.mode === 'locked') return {kind: 'locked'};
      const token = await this.storage.getItemAsync(TOKEN);
      return token ? {kind: 'password', token, accountId: marker?.accountId || null} : {kind: 'none'};
    });
  }

  save(token: string, accountId: string): Promise<void> {
    // A new ordinary login always replaces the prior account and its biometric consent.
    return this.serial(() => this.saveStored(token, accountId));
  }

  enable(token: string, accountId: string, prompt: string, isCurrent: () => boolean = () => true): Promise<void> {
    return this.serial(async () => {
      if (!token || !accountId) throw new NativeSessionError('saved_session_missing');
      const available = await this.available();
      if (!isCurrent()) {
        await this.forgetStored();
        throw new NativeSessionError('saved_session_missing');
      }
      if (!available) throw new NativeSessionError('face_id_unavailable');
      const envelope = JSON.stringify({token, accountId, origin: this.options.apiOrigin});
      try {
        if (!isCurrent()) throw new NativeSessionError('saved_session_missing');
        // A process interruption at any later step must require Face ID/normal sign-in.
        await this.mark('locked', accountId);
        await this.storage.setItemAsync(BIOMETRIC, envelope, this.protectedOptions(prompt));
        // iOS creation does not prompt. Read it back to verify consent/authentication.
        const confirmed = await this.storage.getItemAsync(BIOMETRIC, this.protectedOptions(prompt));
        if (!isCurrent()) throw new NativeSessionError('saved_session_missing');
        if (confirmed !== envelope) throw new NativeSessionError('saved_session_missing');
        await this.storage.deleteItemAsync(TOKEN);
      } catch (error) {
        // Backgrounding/signing out during enrollment revokes rollback permission.
        // Do not recreate an ordinary token after the app has deliberately locked.
        if (!isCurrent()) {
          await this.forgetStored();
          throw error;
        }
        // Canceled opt-in keeps the previous ordinary login if rollback succeeds.
        // Failed rollback leaves the durable marker blocking any partial credential.
        try { await this.saveStored(token, accountId, isCurrent); }
        catch { throw new NativeSessionError('session_storage_failed'); }
        throw error;
      }
    });
  }

  private async readProtected(prompt: string): Promise<{token: string; accountId: string}> {
    const marker = await this.marker();
    if (marker?.mode !== 'locked') throw new NativeSessionError('saved_session_missing');
    // Cancellation/lockout errors propagate without erasing a still-valid saved login.
    const raw = await this.storage.getItemAsync(BIOMETRIC, this.protectedOptions(prompt));
    try {
      const value = raw ? JSON.parse(raw) : null;
      if (!value || typeof value.token !== 'string' || !value.token || value.accountId !== marker.accountId
          || value.origin !== this.options.apiOrigin) throw new Error('Invalid protected session');
      return {token: value.token, accountId: value.accountId};
    } catch {
      await this.forgetStored();
      throw new NativeSessionError('saved_session_missing');
    }
  }

  unlock(prompt: string): Promise<{token: string; accountId: string}> {
    return this.serial(() => this.readProtected(prompt));
  }

  disable(prompt: string, isCurrent: () => boolean = () => true): Promise<void> {
    return this.serial(async () => {
      const saved = await this.readProtected(prompt);
      await this.assertCurrent(isCurrent);
      await this.storage.setItemAsync(TOKEN, saved.token);
      await this.assertCurrent(isCurrent);
      await this.storage.deleteItemAsync(BIOMETRIC, this.protectedOptions());
      await this.assertCurrent(isCurrent);
      // Only this final commit permits restoring the ordinary saved token again.
      await this.mark('plain', saved.accountId);
      await this.assertCurrent(isCurrent);
    });
  }

  forget(): Promise<void> { return this.serial(() => this.forgetStored()); }
}

export const sessionVault = new NativeSessionVault(SecureStore, {
  apiOrigin: API_BASE,
  isIOS: Platform.OS === 'ios',
  protectedOptions: {keychainAccessible: SecureStore.WHEN_PASSCODE_SET_THIS_DEVICE_ONLY},
  supportsFaceID: async () => SecureStore.canUseBiometricAuthentication()
    && await LocalAuthentication.hasHardwareAsync()
    && await LocalAuthentication.isEnrolledAsync()
    && (await LocalAuthentication.supportedAuthenticationTypesAsync()).includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION),
});
