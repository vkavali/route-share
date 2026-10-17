const STORAGE_KEY = 'seatpal.landing-intent.v1';
const TTL_MS = 15 * 60 * 1000;
const MAX_PAYLOAD_LENGTH = 4096;
const MAX_LABEL_LENGTH = 120;

function cleanLabel(value) {
  if (typeof value !== 'string') return undefined;
  const label = value.trim();
  if (!label || label.length > MAX_LABEL_LENGTH || /[\u0000-\u001f\u007f]/.test(label)) return undefined;
  return label;
}

function decodePayload(encoded) {
  if (!encoded || encoded.length > MAX_PAYLOAD_LENGTH || !/^[A-Za-z0-9_-]+$/.test(encoded)) return null;
  try {
    const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - encoded.length % 4) % 4);
    const bytes = Uint8Array.from(atob(base64), char => char.charCodeAt(0));
    const value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (!value || value.v !== 1 || !['search', 'offer'].includes(value.intent)) return null;
    const intent = { v: 1, intent: value.intent };
    for (const key of ['originLabel', 'destinationLabel']) {
      const label = cleanLabel(value[key]);
      if (label) intent[key] = label;
    }
    return intent;
  } catch {
    return null;
  }
}

function availableStorage(storage) {
  if (storage) return storage;
  try { return window.sessionStorage; } catch { return null; }
}

export function captureLandingIntent(locationRef = window.location, historyRef = window.history,
                                     storage = null, now = Date.now()) {
  const match = String(locationRef.hash || '').match(/^#\/?login~sp1:(.*)$/s);
  if (!match) return null;
  storage = availableStorage(storage);

  // Remove even malformed payloads before the app router processes the hash.
  try {
    historyRef.replaceState(historyRef.state, '', `${locationRef.pathname}${locationRef.search}#/login`);
  } catch { /* Continue with the current page if history replacement is unavailable. */ }

  try { storage?.removeItem(STORAGE_KEY); } catch { /* Continue with ordinary login if storage is unavailable. */ }
  const intent = decodePayload(match[1]);
  if (!intent) return null;
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify({ ...intent, expiresAt: now + TTL_MS }));
  } catch { /* The login flow still works normally when storage is unavailable. */ }
  return intent;
}

export function consumeLandingIntent(storage = null, now = Date.now()) {
  storage = availableStorage(storage);
  if (!storage) return null;
  let raw;
  try {
    raw = storage.getItem(STORAGE_KEY);
    storage.removeItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  if (raw.length > MAX_PAYLOAD_LENGTH + 128) return null;
  try {
    const saved = JSON.parse(raw);
    if (!Number.isFinite(saved?.expiresAt) || saved.expiresAt <= now || saved.expiresAt > now + TTL_MS + 1000) return null;
    return decodePayload(encodePayload({ v: saved.v, intent: saved.intent,
      originLabel: saved.originLabel, destinationLabel: saved.destinationLabel }));
  } catch {
    return null;
  }
}

function encodePayload(value) {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
