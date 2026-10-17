import {createVoiceOperation} from './voice/transport';
const rawBase = process.env.EXPO_PUBLIC_API_URL || '';

function validateBase(raw: string) {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error('Set EXPO_PUBLIC_API_URL to the local beta API address.');
  }
  const loopback = ['localhost', '127.0.0.1', '::1', '[::1]'].includes(url.hostname.toLowerCase());
  if (url.protocol !== 'https:' && !(loopback && url.protocol === 'http:')) {
    throw new Error('The API address must use HTTPS.');
  }
  if (url.username || url.password || url.hash || url.search || (url.pathname && url.pathname !== '/')) {
    throw new Error('EXPO_PUBLIC_API_URL must be an API origin without credentials, path, or query.');
  }
  return url.origin;
}

export const API_BASE = rawBase ? validateBase(rawBase) : '';
export type Point = {
  label: string;
  lat: number;
  lon: number;
  id?: string;
  name?: string;
  address?: string;
  kind?: string;
  /** Nominatim order: [south, north, west, east], not GeoJSON order. */
  bbox?: [number, number, number, number] | null;
};
export type Match = Record<string, any>;
export type Booking = Record<string, any>;
export type AppState = {
  access?: Record<string, unknown>;
  user?: any;
  trips: any[];
  bookings: Booking[];
  requests: any[];
  ratings: any[];
  safety_reports: any[];
  blocks: any[];
};

type ApiError = Error & {status?: number; code?: string; cause?: unknown};

export class Api {
  token: string | null = null;

  constructor(token?: string | null) {
    this.token = token || null;
  }

  async request(path: string, body?: unknown, method?: string): Promise<any> {
    if (!API_BASE) throw new Error('Configure EXPO_PUBLIC_API_URL before using the app.');
    const requestToken = this.token;
    const assertCurrentSession = () => {
      if (this.token !== requestToken) {
        const error = new Error('The account session changed while the request was running.') as ApiError;
        error.code = 'ESESSION_CHANGED';
        throw error;
      }
    };
    const headers: Record<string, string> = {Accept: 'application/json'};
    const multipart = typeof FormData !== 'undefined' && body instanceof FormData;
    if (body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
    if (this.token) headers.Authorization = `Bearer ${this.token}`;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    try {
      let response: Response;
      try {
        response = await fetch(`${API_BASE}${path}`, {
          method: method || (body === undefined ? 'GET' : 'POST'),
          headers,
          body: body === undefined ? undefined : multipart ? body as FormData : JSON.stringify(body),
          signal: controller.signal,
        });
      } catch (cause: any) {
        assertCurrentSession();
        const error = new Error(cause?.name === 'AbortError'
          ? 'The request took too long. Check your connection and retry.'
          : (cause?.message || 'The service could not be reached.')) as ApiError;
        error.code = cause?.name === 'AbortError' ? 'ETIMEDOUT' : (cause?.code || 'ENETWORK');
        error.cause = cause;
        throw error;
      }

      assertCurrentSession();

      let data: any;
      try {
        data = await response.json();
      } catch (cause) {
        assertCurrentSession();
        if (response.ok) {
          const error = new Error('The service returned an unreadable response.') as ApiError;
          error.code = 'EBADRESPONSE';
          error.cause = cause;
          throw error;
        }
        data = {};
      }
      assertCurrentSession();
      if (!response.ok) {
        const error = new Error(data.error || `Request failed (${response.status}).`) as ApiError;
        error.status = response.status;
        error.code = data.code;
        throw error;
      }
      return data;
    } finally {
      clearTimeout(timeout);
    }
  }

  voiceOperation(requestId: string, language: 'en' | 'te') {
    return createVoiceOperation(API_BASE, this.token, requestId, language);
  }

  login(account: string, password: string) {
    return this.request('/api/mobile/login', {account, password});
  }

  phoneCapabilities() { return this.request('/api/phone/capabilities'); }
  phoneStart(payload: Record<string, unknown>) { return this.request('/api/mobile/phone/start', payload); }
  phoneResend(payload: Record<string, unknown>) { return this.request('/api/mobile/phone/resend', payload); }
  phoneVerify(payload: Record<string, unknown>) { return this.request('/api/mobile/phone/verify', payload); }
  phoneProfile(name: string) { return this.request('/api/phone/profile', {name}); }
  identityApplication() { return this.request('/api/identity_application'); }
  saveIdentityApplication(body: Record<string, unknown>) { return this.request('/api/identity_application', body); }
  identityVerificationQueue() { return this.request('/api/identity_verification_queue'); }
  identityReviewProgress(applicationId: string) {
    return this.request(`/api/identity_review_progress?application_id=${encodeURIComponent(applicationId)}`);
  }
  saveIdentityReviewProgress(body: Record<string, unknown>) { return this.request('/api/identity_review_progress', body); }
  driverReviewProgress(applicationId: string) {
    return this.request(`/api/driver_review_progress?application_id=${encodeURIComponent(applicationId)}`);
  }
  saveDriverReviewProgress(body: Record<string, unknown>) { return this.request('/api/driver_review_progress', body); }
  documentPreview(kind: 'identity'|'driver', documentId: string, page: number) {
    const path = kind === 'identity' ? '/api/identity_document_preview' : '/api/driver_document_preview';
    return this.request(`${path}?document_id=${encodeURIComponent(documentId)}&page=${encodeURIComponent(String(page))}`);
  }
  uploadIdentityDocument(body: FormData) { return this.request('/api/identity_documents', body); }
  submitIdentityApplication(body: Record<string, unknown>) { return this.action('submit_identity_application', body); }
  withdrawIdentityApplication(body: Record<string, unknown>) { return this.action('withdraw_identity_application', body); }
  reviewIdentityApplication(body: Record<string, unknown>) { return this.action('review_identity_application', body); }
  accountLifecycle() { return this.request('/api/account/lifecycle'); }
  accountReauthStart(body: Record<string, unknown>) { return this.request('/api/account/reauth/start', body); }
  accountReauthVerify(body: Record<string, unknown>) { return this.request('/api/account/reauth/verify', body); }
  saveRecoveryKey(body: Record<string, unknown>) { return this.request('/api/account/recovery-key', body); }
  deleteAccount(body: Record<string, unknown>) { return this.request('/api/account/delete', body); }
  recoverAccountStart(body: Record<string, unknown>) { return this.request('/api/mobile/account/recovery/start', body); }
  recoverAccountVerify(body: Record<string, unknown>) { return this.request('/api/mobile/account/recovery/verify', body); }
  backupEmailStart(body: Record<string, unknown>) { return this.request('/api/account/backup-email/start', body); }
  backupEmailVerify(body: Record<string, unknown>) { return this.request('/api/account/backup-email/verify', body); }
  backupEmailRemove(body: Record<string, unknown>) { return this.request('/api/account/backup-email/remove', body); }
  recoverEmailStart(body: Record<string, unknown>) { return this.request('/api/mobile/account/recovery/email/start', body); }
  recoverEmailVerify(body: Record<string, unknown>) { return this.request('/api/mobile/account/recovery/email/verify', body); }
  recoverEmailPhoneStart(body: Record<string, unknown>) { return this.request('/api/mobile/account/recovery/phone/start', body); }
  recoverEmailPhoneVerify(body: Record<string, unknown>) { return this.request('/api/mobile/account/recovery/phone/verify', body); }

  logout() { return this.request('/api/mobile/logout', {}); }
  state(): Promise<AppState> { return this.request('/api/state'); }
  action(name: string, payload: Record<string, unknown>) { return this.request(`/api/${name}`, payload); }
  bootstrap() { return this.request('/api/bootstrap'); }
}
