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
export type Point = {label: string; lat: number; lon: number};
export type Match = Record<string, any>;
export type Booking = Record<string, any>;
export type AppState = {
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
    const headers: Record<string, string> = {Accept: 'application/json'};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (this.token) headers.Authorization = `Bearer ${this.token}`;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20_000);
    try {
      let response: Response;
      try {
        response = await fetch(`${API_BASE}${path}`, {
          method: method || (body === undefined ? 'GET' : 'POST'),
          headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
        });
      } catch (cause: any) {
        const error = new Error(cause?.name === 'AbortError'
          ? 'The request took too long. Check your connection and retry.'
          : (cause?.message || 'The service could not be reached.')) as ApiError;
        error.code = cause?.name === 'AbortError' ? 'ETIMEDOUT' : (cause?.code || 'ENETWORK');
        error.cause = cause;
        throw error;
      }

      let data: any;
      try {
        data = await response.json();
      } catch (cause) {
        if (response.ok) {
          const error = new Error('The service returned an unreadable response.') as ApiError;
          error.code = 'EBADRESPONSE';
          error.cause = cause;
          throw error;
        }
        data = {};
      }
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

  login(account: string, password: string) {
    return this.request('/api/mobile/login', {account, password});
  }

  logout() { return this.request('/api/mobile/logout', {}); }
  state(): Promise<AppState> { return this.request('/api/state'); }
  action(name: string, payload: Record<string, unknown>) { return this.request(`/api/${name}`, payload); }
  bootstrap() { return this.request('/api/bootstrap'); }
}
