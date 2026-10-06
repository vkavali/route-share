const activeLinks = new Map();

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function usableLink(value) {
  try {
    const parsed = new URL(value, location.origin);
    if (!['https:', 'http:'].includes(parsed.protocol)) return null;
    if (parsed.origin !== location.origin && parsed.protocol !== 'https:') return null;
    return parsed.href;
  } catch {
    return null;
  }
}

/**
 * Render and bind opt-in trusted trip links. URLs stay in memory only, never
 * browser storage. Cleanup detaches handlers without revoking a created link.
 * @param {{element:HTMLElement,bookingId:string,api:Function,lang:string,t?:Function,viewerId?:string}} options
 */
export function mountTripSharing({ element, bookingId, api, lang, t, viewerId = '' }) {
  if (!element || !bookingId || typeof api !== 'function') return () => {};
  const text = (key) => t?.(key) || key;
  const cacheKey = `${viewerId}:${bookingId}`;
  const abort = new AbortController();
  const { signal } = abort;
  let expiryTimer = null;
  const formatTime = (value) => {
    const time = new Date(value);
    if (Number.isNaN(time.valueOf())) return text('unknown');
    return new Intl.DateTimeFormat(lang === 'te' ? 'te-IN' : lang === 'hi' ? 'hi-IN' : 'en-IN', {
      dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata',
    }).format(time);
  };
  const expireIfNeeded = () => {
    const link = activeLinks.get(cacheKey);
    if (link && (!Number.isFinite(Date.parse(link.expires_at)) || Date.parse(link.expires_at) <= Date.now())) {
      activeLinks.delete(cacheKey);
      return true;
    }
    return false;
  };
  const currentLink = () => {
    if (expireIfNeeded()) render(text('tripLinkExpired'));
    return activeLinks.get(cacheKey) || null;
  };
  const copyText = async (value, input = null) => {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      if (!input) return false;
      input.focus(); input.select();
      try { return document.execCommand('copy') === true; }
      catch { return false; }
    }
  };

  const render = (message = '') => {
    if (expiryTimer) clearTimeout(expiryTimer);
    expiryTimer = null;
    if (expireIfNeeded()) message = text('tripLinkExpired');
    const link = activeLinks.get(cacheKey);
    if (!link) {
      element.innerHTML = `<section class="trip-share-control"><h3>${escapeHtml(text('tripLinkTitle'))}</h3><p>${escapeHtml(text('tripLinkDisclosure'))}</p>${message ? `<p role="status">${escapeHtml(message)}</p>` : ''}<button class="secondary" type="button" data-trip-link-create>${escapeHtml(text('tripLinkCreate'))}</button></section>`;
    } else {
      const url = usableLink(link.url);
      if (!url) {
        activeLinks.delete(cacheKey);
        render(text('tripLinkError'));
        return;
      }
      const expires = Date.parse(link.expires_at);
      expiryTimer = setTimeout(() => {
        if (signal.aborted || activeLinks.get(cacheKey)?.link_id !== link.link_id) return;
        render(expireIfNeeded() ? text('tripLinkExpired') : '');
      }, Math.min(Math.max(0, expires - Date.now()), 2147483000) + 5);
      element.innerHTML = `<section class="trip-share-control"><h3>${escapeHtml(text('tripLinkTitle'))}</h3><p role="status">${escapeHtml(text('tripLinkCreated').replace('{time}', formatTime(link.expires_at)))}</p><label><span class="sr-only">${escapeHtml(text('tripLinkTitle'))}</span><input type="url" readonly value="${escapeHtml(url)}" data-trip-link-url></label><div><button class="secondary" type="button" data-trip-link-copy>${escapeHtml(text('tripLinkCopy'))}</button><button class="secondary" type="button" data-trip-link-share>${escapeHtml(text('tripLinkShare'))}</button><button class="text-button" type="button" data-trip-link-revoke>${escapeHtml(text('tripLinkRevoke'))}</button></div>${message ? `<p role="status">${escapeHtml(message)}</p>` : ''}</section>`;
    }
    const create = element.querySelector('[data-trip-link-create]');
    create?.addEventListener('click', async () => {
      create.disabled = true;
      create.textContent = text('tripLinkCreating');
      try {
        const response = await api('/api/create_trip_link', 'POST', { booking_id: bookingId });
        if (signal.aborted) return;
        const url = usableLink(response?.url);
        if (!response?.link_id || !url || !response?.expires_at || Date.parse(response.expires_at) <= Date.now()) throw new Error('invalid link response');
        activeLinks.set(cacheKey, { link_id: response.link_id, url, expires_at: response.expires_at });
        render();
      } catch {
        if (!signal.aborted) render(text('tripLinkError'));
      }
    }, { signal });
    element.querySelector('[data-trip-link-copy]')?.addEventListener('click', async () => {
      const input = element.querySelector('[data-trip-link-url]');
      const link = currentLink();
      if (!input || !link) return;
      const copied = await copyText(link.url, input);
      if (!signal.aborted) render(text(copied ? 'tripLinkCopied' : 'tripLinkManualCopy'));
    }, { signal });
    element.querySelector('[data-trip-link-share]')?.addEventListener('click', async () => {
      const link = currentLink();
      if (!link) return;
      try {
        if (navigator.share) await navigator.share({ title: text('tripLinkTitle'), url: link.url });
        else {
          const copied = await copyText(link.url, element.querySelector('[data-trip-link-url]'));
          if (!signal.aborted) render(text(copied ? 'tripLinkCopied' : 'tripLinkManualCopy'));
        }
      } catch (error) {
        if (error?.name !== 'AbortError' && !signal.aborted) render(text('tripLinkError'));
      }
    }, { signal });
    element.querySelector('[data-trip-link-revoke]')?.addEventListener('click', async (event) => {
      const button = event.currentTarget;
      const link = currentLink();
      if (!link) return;
      button.disabled = true;
      try {
        await api('/api/revoke_trip_link', 'POST', { link_id: link.link_id });
        if (signal.aborted) return;
        activeLinks.delete(cacheKey);
        render(text('tripLinkRevoked'));
      } catch {
        if (!signal.aborted) { button.disabled = false; render(text('tripLinkError')); }
      }
    }, { signal });
  };

  render();
  return () => {
    if (expiryTimer) clearTimeout(expiryTimer);
    abort.abort();
  };
}

export function clearTripSharingState() {
  activeLinks.clear();
}
