export type VoiceCapabilities = {available: boolean; languages: ('en' | 'te')[]; max_seconds: number; max_bytes: number; daily_remaining: number; reset_at: string};
export type VoiceResult = {request_id: string; text: string; language: 'en' | 'te'; duration_ms: number};
export type VoiceOperation = {capabilities(): Promise<VoiceCapabilities>; transcribe(uri: string): Promise<VoiceResult>; cancel(): Promise<void>};
export const validVoiceReset = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) && Number.isFinite(Date.parse(value));
const failure = (code: string, status?: number) => Object.assign(new Error(code), {code, status});
/** Captured credentials keep cancellation tied to the original account after logout. */
export function createVoiceOperation(base: string, token: string | null, requestId: string, language: 'en' | 'te'): VoiceOperation {
  const controller = new AbortController();
  let cancelled = false, submitted = false, cancelPromise: Promise<void> | undefined;
  async function request(path: string, body?: FormData | string, cancellation = false): Promise<any> {
    if (!base || !token) throw failure('VOICE_UNAVAILABLE');
    if (cancelled && !cancellation) throw failure('VOICE_CANCELLED');
    const local = cancellation ? new AbortController() : controller;
    let timedOut = false;
    const timer = setTimeout(() => {timedOut = true; local.abort();}, cancellation ? 5000 : body instanceof FormData ? 90000 : 15000);
    try {
      const response = await fetch(base + path, {
        method: body === undefined ? 'GET' : 'POST', redirect: 'error', signal: local.signal,
        headers: {Accept: 'application/json', Authorization: `Bearer ${token}`, ...(body instanceof FormData ? {'X-Voice-Request-ID': requestId} : {}), ...(typeof body === 'string' ? {'Content-Type': 'application/json'} : {})}, body,
      });
      const data = await response.json();
      if (cancelled && !cancellation) throw failure('VOICE_CANCELLED');
      if (!response.ok) {
        const error = failure(typeof data?.code === 'string' ? data.code : 'VOICE_FAILED', response.status);
        if (data?.code === 'VOICE_DAILY_LIMIT' && validVoiceReset(data.reset_at)) Object.assign(error, {reset_at: data.reset_at});
        throw error;
      }
      return data;
    } catch (cause: any) {
      if (cancelled && !cancellation) throw failure('VOICE_CANCELLED');
      if (timedOut) throw failure('VOICE_TIMEOUT');
      if (cause?.code) throw cause;
      throw failure('VOICE_NETWORK');
    } finally {clearTimeout(timer);}
  }
  return {
    async capabilities() {
      const value = await request('/api/voice/capabilities');
      if (!value || typeof value.available !== 'boolean' || !Array.isArray(value.languages) || !Number.isFinite(value.max_seconds) || value.max_seconds <= 0 || !Number.isFinite(value.max_bytes) || value.max_bytes <= 0 || !Number.isInteger(value.daily_remaining) || value.daily_remaining < 0 || !validVoiceReset(value.reset_at)) throw failure('VOICE_UNAVAILABLE');
      return {available: value.available, languages: value.languages.filter((x: unknown) => x === 'en' || x === 'te'), max_seconds: Math.min(45, value.max_seconds), max_bytes: Math.min(2097152, value.max_bytes), daily_remaining: value.daily_remaining, reset_at: value.reset_at};
    },
    async transcribe(uri) {
      if (cancelled) throw failure('VOICE_CANCELLED');
      const body = new FormData();
      body.append('audio', {uri, name: 'trip.m4a', type: 'audio/mp4'} as any);
      body.append('language', language); body.append('request_id', requestId);
      submitted = true;
      const value = await request('/api/voice/transcribe', body);
      if (value?.request_id !== requestId || value?.language !== language || typeof value?.text !== 'string' || value.text.length > 1000 || !Number.isFinite(value.duration_ms) || value.duration_ms < 0 || value.duration_ms > 46000) throw failure('VOICE_FAILED');
      if (!value.text.trim()) throw failure('VOICE_NO_SPEECH');
      return {...value, text: value.text.trim()};
    },
    cancel() {
      if (cancelPromise) return cancelPromise;
      cancelled = true; controller.abort();
      if (!submitted) return cancelPromise = Promise.resolve();
      cancelPromise = request('/api/voice/cancel', JSON.stringify({request_id: requestId}), true).then(() => undefined, () => undefined);
      return cancelPromise;
    },
  };
}
