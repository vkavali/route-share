const CHANNEL_NAME = 'seatpal-session-events-v1';
const STORAGE_KEY = 'seatpal-session-event-v1';

function nonce() {
  try { return crypto.randomUUID(); }
  catch { return `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
}

/** Coordinate session rechecks without publishing account data or credentials. */
export function createSessionCoordinator({ onChange, target = globalThis.window,
  BroadcastChannelImpl = globalThis.BroadcastChannel, storage = globalThis.localStorage } = {}) {
  if (!target || typeof onChange !== 'function') return { announce() {}, close() {} };
  const seen = new Set();
  let channel = null;
  const receive = value => {
    if (!value || value.type !== 'session-changed' || typeof value.nonce !== 'string'
        || !value.nonce || seen.has(value.nonce)) return;
    seen.add(value.nonce);
    if (seen.size > 64) seen.delete(seen.values().next().value);
    onChange();
  };
  try {
    if (typeof BroadcastChannelImpl === 'function') {
      channel = new BroadcastChannelImpl(CHANNEL_NAME);
      channel.addEventListener('message', event => receive(event.data));
    }
  } catch { channel = null; }
  const onStorage = event => {
    if (event.key === STORAGE_KEY && event.newValue) {
      receive({ type: 'session-changed', nonce: event.newValue });
    }
  };
  target.addEventListener('storage', onStorage);
  return {
    announce() {
      const id = nonce();
      const message = { type: 'session-changed', nonce: id };
      try { channel?.postMessage(message); } catch { /* storage remains the fallback */ }
      try { storage?.setItem(STORAGE_KEY, id); } catch { /* BroadcastChannel remains available */ }
    },
    close() {
      target.removeEventListener('storage', onStorage);
      try { channel?.close(); } catch { /* already closed */ }
      channel = null;
    },
  };
}
