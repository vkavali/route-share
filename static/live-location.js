import { appIcon } from './icons.js';

const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const FRESH_FOR_MS = 15_000;
const MAX_ACCURACY_M = 200;
const MIN_SEND_INTERVAL_MS = 5_000;
const MAX_RETAIN_MS = 120_000;
const REQUEST_TIMEOUT_MS = 12_000;

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

function coordinates(point) {
  const lat = Number(point?.lat);
  const lon = Number(point?.lon);
  return Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180
    ? [lat, lon]
    : null;
}

function routePoints(booking) {
  const route = booking?.route || booking?.trip_route || booking?.match?.route || booking?.trip?.route;
  const points = route?.coordinates;
  if (!Array.isArray(points)) return [];
  return points.filter(point => Array.isArray(point) && point.length >= 2
    && Number.isFinite(Number(point[0])) && Number.isFinite(Number(point[1]))
    && Math.abs(Number(point[1])) <= 90 && Math.abs(Number(point[0])) <= 180)
    .map(point => [Number(point[1]), Number(point[0])]);
}

function haversineMeters(a, b) {
  const radians = value => value * Math.PI / 180;
  const dLat = radians(b[0] - a[0]);
  const dLon = radians(b[1] - a[1]);
  const lat1 = radians(a[0]);
  const lat2 = radians(b[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 6_371_000 * 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}

function formatTime(value, lang) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  const locale = lang === 'te' ? 'te-IN' : lang === 'hi' ? 'hi-IN' : 'en-IN';
  return new Intl.DateTimeFormat(locale, { hour: 'numeric', minute: '2-digit', timeZone: 'Asia/Kolkata' }).format(date);
}

function makePointMarker(L, map, point, className) {
  const latLng = coordinates(point);
  if (!latLng) return null;
  const marker = L.circleMarker(latLng, {
    radius: 8,
    color: '#ffffff',
    weight: 3,
    fillColor: className === 'pickup' ? '#173d34' : '#d6ee7a',
    fillOpacity: 1,
    className: `live-location-marker live-location-marker-${className}`,
  }).addTo(map);
  if (point?.label) {
    const label = document.createElement('span');
    label.textContent = String(point.label);
    marker.bindTooltip(label, { direction: 'top', offset: [0, -8] });
  }
  return marker;
}

function makeDeviceMarker(L, map, location) {
  return L.circleMarker([Number(location.lat), Number(location.lon)], {
    radius: 7,
    color: '#ffffff',
    weight: 2,
    fillColor: '#18845b',
    fillOpacity: 1,
    className: 'live-location-marker live-location-marker-device',
  }).addTo(map);
}

/**
 * Mount an opt-in live-location view for one accepted booking.
 * All coordinates and watch tokens remain in this closure and are discarded by cleanup.
 */
export function mountLiveLocation({
  element, booking, lang = 'en', t, api, onExpired = () => {}, getCsrf = () => '', viewerId = '',
  labelPoint = point => point?.label || '',
}) {
  if (!element || typeof t !== 'function' || typeof api !== 'function') {
    throw new TypeError('Live location requires an element, translator, and API helper.');
  }

  const policyCopy = {
    en: {opens: 'Sharing opens at', visible: 'Visible to', ends: 'until this passenger’s drop-off. You can stop at any time.', boarding: 'Sharing paused when you boarded. Start again only if you want to keep sharing.', emergency: 'Emergency · Call 112'},
    te: {opens: 'లొకేషన్ షేరింగ్ మొదలయ్యే టైమ్', visible: 'మీ లొకేషన్ చూడగలిగేది', ends: 'డ్రాప్ అయ్యే వరకు మాత్రమే. మీరు ఎప్పుడైనా ఆపొచ్చు.', boarding: 'కారు ఎక్కాక షేరింగ్ ఆగింది. కొనసాగించాలంటే మళ్లీ స్టార్ట్ చేయండి.', emergency: 'ఎమర్జెన్సీ · 112కి కాల్'},
    hi: {opens: 'लोकेशन शेयर करने का समय', visible: 'लोकेशन देख सकते हैं', ends: 'ड्रॉप होने तक। आप कभी भी रोक सकते हैं।', boarding: 'सवार होने पर शेयरिंग रुकी। जारी रखने के लिए दोबारा शुरू करें।', emergency: 'आपातकाल · 112 पर कॉल'}
  }[lang] || {opens: 'Sharing opens at', visible: 'Visible to', ends: 'until drop-off.', emergency: 'Emergency · Call 112'};
  const bookingId = String(booking?.id || '');
  let pickup = booking?.match?.routed_pickup || booking?.pickup || booking?.match?.pickup;
  let dropoff = booking?.match?.routed_dropoff || booking?.dropoff || booking?.match?.dropoff;
  let pickupPoint = coordinates(pickup);
  let dropoffPoint = coordinates(dropoff);
  let displayedRoute = routePoints(booking);
  const hasL = Boolean(window.L?.map && window.L?.tileLayer);
  const center = pickupPoint || dropoffPoint || displayedRoute[0] || null;

  element.innerHTML = `<section class="live-location" aria-labelledby="live-location-title">
    <h2 id="live-location-title" class="sr-only">${escapeHtml(t('liveTitle'))}</h2>
    <div class="live-location-map" role="img" aria-label="${escapeHtml(t('liveTitle'))}"></div>
    <div class="live-location-sheet">
      <div class="live-journey-summary"><span class="live-journey-icon">${appIcon('car')}</span>
        <div class="live-journey-labels"><strong class="live-pickup-label">${escapeHtml(labelPoint(pickup) || t('origin'))}</strong>
          ${appIcon('arrowRight', {className: 'live-journey-arrow', size: 18})}<strong class="live-dropoff-label">${escapeHtml(labelPoint(dropoff) || t('destination'))}</strong></div>
      </div>
      <p class="live-location-status" role="status" aria-live="polite"></p>
      <div class="live-location-details"><span class="live-location-detail-updated"></span><span class="live-location-detail-accuracy"></span></div>
      <div class="live-privacy-banner"><span class="live-privacy-icon">${appIcon('mapPin')}</span><div>
        <p class="live-location-own-status" role="status" aria-live="polite"></p>
        <p class="live-location-privacy">${escapeHtml(t('livePrivacy'))}</p>
        <p class="hint">${escapeHtml(t('liveForegroundOnly'))}</p>
      </div></div>
      <p class="live-location-notice" role="status" aria-live="polite"></p>
      <div class="live-location-controls">
        <button type="button" class="primary live-location-start">${appIcon('mapPin')}<span>${escapeHtml(t('liveStart'))}</span></button>
        <button type="button" class="primary live-location-stop" hidden>${appIcon('prohibit')}<span>${escapeHtml(t('liveStop'))}</span></button>
        <a class="secondary live-location-ended-link" href="#/bookings" hidden>${escapeHtml(t('bookings'))}${appIcon('arrowRight')}</a>
      </div>
      <a class="secondary" href="tel:112">${appIcon('phone')} ${escapeHtml(policyCopy.emergency)}</a>
      <p class="live-location-route-note" ${displayedRoute.length > 1 ? 'hidden' : ''}>${escapeHtml(t('liveRouteUnavailable'))}</p>
    </div>
  </section>`;

  const root = element.querySelector('.live-location');
  const statusElement = root.querySelector('.live-location-status');
  const noticeElement = root.querySelector('.live-location-notice');
  const ownStatusElement = root.querySelector('.live-location-own-status');
  const startButton = root.querySelector('.live-location-start');
  const stopButton = root.querySelector('.live-location-stop');
  const endedLink = root.querySelector('.live-location-ended-link');
  const mapElement = root.querySelector('.live-location-map');
  const updatedElement = root.querySelector('.live-location-detail-updated');
  const accuracyElement = root.querySelector('.live-location-detail-accuracy');
  const routeNote = root.querySelector('.live-location-route-note');

  let map = null;
  let cleanupBasemap = null;
  let routeLine = null;
  let endpointMarkers = [];
  let locationMarkers = new Map();
  let sharingAllowed = false;
  let terminal = false;
  let cleaned = false;
  let hidden = document.hidden;
  let localSharing = false;
  let starting = false;
  let sharingId = null;
  let viewerSharingId = null;
  let watchId = null;
  let generation = 0;
  let lastSendAt = 0;
  let pollTimer = null;
  let freshnessTimer = null;
  let polling = false;
  let expiredNotified = false;
  let locations = [];
  let lastLocalPosition = null;
  let noticeKey = '';

  if (hasL && (displayedRoute.length > 1 || pickupPoint || dropoffPoint)) {
    map = window.L.map(mapElement, { scrollWheelZoom: false, zoomControl: true, zoomAnimation: false, fadeAnimation: false, markerZoomAnimation: false });
    if (window.RouteShareMapTheme?.enabled === true && window.RouteShareMapTheme?.mountBasemap) {
      cleanupBasemap = window.RouteShareMapTheme.mountBasemap(window.L, map, { lang });
    } else {
      window.L.tileLayer(TILE_URL, {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);
    }
    if (displayedRoute.length > 1) {
      routeLine = window.L.polyline(displayedRoute, { color: '#173d34', weight: 5, opacity: 0.95 }).addTo(map);
    }
    const pickupMarker = makePointMarker(window.L, map, pickup, 'pickup');
    const dropoffMarker = makePointMarker(window.L, map, dropoff, 'dropoff');
    endpointMarkers = [pickupMarker, dropoffMarker].filter(Boolean);
    const bounds = routeLine?.getBounds();
    const markerBounds = window.L.featureGroup(endpointMarkers).getBounds();
    if (bounds?.isValid() && markerBounds?.isValid()) bounds.extend(markerBounds);
    if (bounds?.isValid()) map.fitBounds(bounds.pad(0.12), { maxZoom: 12 });
    else if (markerBounds?.isValid()) map.fitBounds(markerBounds.pad(0.35), { maxZoom: 12 });
    else if (center) map.setView(center, 10);
  } else {
    mapElement.hidden = true;
    routeNote.hidden = false;
  }

  const setNotice = key => {
    noticeKey = key;
    noticeElement.textContent = key ? t(key) : '';
  };

  const setStateClass = () => {
    root.classList.toggle('is-sharing', localSharing);
    ownStatusElement.textContent = localSharing || viewerSharingId ? t('liveSharing') : ''; 
    root.classList.toggle('is-ended', terminal);
    root.classList.toggle('is-stale', locations.some(location => isStale(location)));
    startButton.disabled = cleaned || hidden || terminal || !sharingAllowed || starting || localSharing;
    startButton.querySelector('span').textContent = starting ? t('liveStarting') : t('liveStart');
    startButton.hidden = terminal || localSharing || Boolean(viewerSharingId);
    stopButton.hidden = !localSharing && !starting && !viewerSharingId;
    stopButton.disabled = cleaned || (!localSharing && !starting && !viewerSharingId);
    endedLink.hidden = !terminal;
  };

  function isStale(location) {
    const parsed = Date.parse(location.updated_at || '');
    return !Number.isFinite(parsed) || Date.now() - parsed > FRESH_FOR_MS;
  }

  function visibleLocations() {
    return locations.filter(location => {
      const age = Date.now() - Date.parse(location.updated_at || '');
      return Number.isFinite(age) && age < MAX_RETAIN_MS
        && (!viewerId || String(location.user_id) !== String(viewerId));
    });
  }

  function clearMarkers() {
    for (const marker of locationMarkers.values()) marker.remove();
    locationMarkers.clear();
  }

  function renderLocations() {
    if (cleaned) return;
    const active = visibleLocations();
    const keys = new Set(active.map(location => String(location.user_id)));
    for (const [id, marker] of locationMarkers) {
      if (!keys.has(id)) {
        marker.remove();
        locationMarkers.delete(id);
      }
    }
    for (const location of active) {
      if (!map) continue;
      const lat = Number(location.lat);
      const lon = Number(location.lon);
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) continue;
      const id = String(location.user_id);
      let marker = locationMarkers.get(id);
      if (!marker) {
        marker = makeDeviceMarker(window.L, map, location);
        locationMarkers.set(id, marker);
      }
      marker.setLatLng([lat, lon]);
      marker.setStyle({ fillColor: isStale(location) ? '#77808a' : '#18845b' });
      const tooltip = document.createElement('span');
      tooltip.textContent = String(location.name || '');
      marker.bindTooltip(tooltip, { direction: 'top', offset: [0, -8] });
    }
    if (active.length) {
      const last = active.reduce((latest, item) => Date.parse(item.updated_at || 0) > Date.parse(latest.updated_at || 0) ? item : latest, active[0]);
      const updated = formatTime(last.updated_at, lang);
      const age = Date.now() - Date.parse(last.updated_at || '');
      statusElement.textContent = isStale(last)
        ? `${t('liveStale')}${updated ? ` · ${updated}` : ''}`
        : `${t('liveLastUpdated')}${updated ? ` · ${updated}` : ''}`;
      const accuracy = Number(last.accuracy);
      const locale = lang === 'te' ? 'te-IN' : lang === 'hi' ? 'hi-IN' : 'en-IN';
      const seconds = Number.isFinite(age) ? Math.max(0, Math.floor(age / 1000)) : 0;
      updatedElement.textContent = `${t('liveLastUpdated')} · ${new Intl.NumberFormat(locale).format(seconds)} ${t('liveSecondsAgo')}`;
      accuracyElement.textContent = Number.isFinite(accuracy)
        ? `${t('liveAccuracy')} · ${new Intl.NumberFormat(locale, { style: 'unit', unit: 'meter', unitDisplay: 'short', maximumFractionDigits: 0 }).format(Math.round(accuracy))}`
        : '';
      if (!Number.isFinite(age)) statusElement.textContent = t('liveStale');
    } else {
      statusElement.textContent = terminal ? t(noticeKey || 'liveEnded') : t('liveWaiting');
      updatedElement.textContent = '';
      accuracyElement.textContent = '';
    }
    setStateClass();
  }

  function notifyExpired(error) {
    if (error?.status === 401 && !expiredNotified) {
      expiredNotified = true;
      onExpired();
    }
  }

  async function apiCall(path, method = 'GET', body) {
    let timeout;
    try {
      return await Promise.race([
        api(path, method, body),
        new Promise((_, reject) => {
          timeout = setTimeout(() => reject(new Error('Location request timed out.')), REQUEST_TIMEOUT_MS);
        }),
      ]);
    } catch (error) {
      notifyExpired(error);
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  async function stopRequest(id, keepalive = false) {
    if (!id || !bookingId) return;
    const body = JSON.stringify({ booking_id: bookingId, sharing_id: id });
    if (keepalive && typeof getCsrf === 'function') {
      try {
        await fetch('/api/stop_sharing', {
          method: 'POST',
          credentials: 'same-origin',
          keepalive: true,
          headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': getCsrf() },
          body,
        });
      } catch { /* Server lease expiry remains the fallback if the page is leaving. */ }
      return;
    }
    try {
      await apiCall('/api/stop_sharing', 'POST', { booking_id: bookingId, sharing_id: id });
    } catch { /* The stopped watch stays stopped; the lease expires if revocation cannot arrive. */ }
  }

  function clearDeviceWatch() {
    if (watchId !== null && navigator.geolocation) navigator.geolocation.clearWatch(watchId);
    watchId = null;
    localSharing = false;
    lastLocalPosition = null;
  }

  function stopLocal({ send = true, keepalive = false, notice = 'liveEnded', terminalStop = false } = {}) {
    const id = sharingId;
    sharingId = null;
    viewerSharingId = null;
    generation += 1;
    starting = false;
    clearDeviceWatch();
    if (terminalStop) terminal = true;
    if (send && id) void stopRequest(id, keepalive);
    if (notice) setNotice(notice);
    renderLocations();
  }

  function handleServerEnd(response) {
    const reason = response?.reason || response?.stopped_reason;
    if (reason === 'poor_accuracy') {
      stopLocal({ send: false, notice: 'livePoorAccuracy' });
      return false;
    }
    if (response?.sharing_allowed !== false) return false;
    sharingAllowed = false;
    stopLocal({ send: false, notice: reason === 'arrival' ? 'liveEndedArrival' : 'liveEnded', terminalStop: true });
    locations = [];
    clearMarkers();
    renderLocations();
    return true;
  }

  function handleRequestFailure(error) {
    const ended = ['arrival', 'blocked', 'journey_ended', 'not_participant'].includes(error?.code)
      || [401, 403].includes(error?.status);
    const expired = error?.code === 'sharing_expired';
    sharingAllowed = expired && !terminal;
    locations = [];
    clearMarkers();
    stopLocal({ send: !ended, keepalive: true,
      terminalStop: ended,
      notice: error?.code === 'arrival' ? 'liveEndedArrival'
        : ended ? 'liveEnded' : expired ? 'liveLeaseExpired' : 'liveNetworkError' });
  }

  function refreshEndpoints(response) {
    if (coordinates(response.pickup)) {
      pickup = response.pickup;
      pickupPoint = coordinates(pickup);
    }
    if (coordinates(response.dropoff)) {
      dropoff = response.dropoff;
      dropoffPoint = coordinates(dropoff);
    }
    root.querySelector('.live-pickup-label').textContent = labelPoint(pickup) || t('origin');
    root.querySelector('.live-dropoff-label').textContent = labelPoint(dropoff) || t('destination');
    if (!map) return;
    for (const marker of endpointMarkers) marker.remove();
    endpointMarkers = [makePointMarker(window.L, map, pickup, 'pickup'),
      makePointMarker(window.L, map, dropoff, 'dropoff')].filter(Boolean);
  }

  async function poll() {
    if (cleaned || hidden || document.hidden || polling || starting || terminal || !bookingId) return;
    polling = true;
    const token = generation;
    try {
      const response = await apiCall(`/api/live_location?booking_id=${encodeURIComponent(bookingId)}`);
      if (cleaned || token !== generation || hidden) return;
      if (handleServerEnd(response)) return;
      if (!viewerId && response.viewer_id) viewerId = String(response.viewer_id);
      refreshEndpoints(response);
      const liveRoute = routePoints({ route: response.route });
      if (map && displayedRoute.length < 2 && liveRoute.length > 1) {
        displayedRoute = liveRoute;
        routeLine = window.L.polyline(displayedRoute, { color: '#173d34', weight: 5, opacity: 0.95 }).addTo(map);
        routeNote.hidden = true;
        const bounds = routeLine.getBounds();
        if (bounds.isValid()) map.fitBounds(bounds.pad(0.12), { maxZoom: 12 });
      }
      sharingAllowed = Boolean(response.sharing_allowed) && response.start_allowed !== false;
      const privacy = root.querySelector('.live-location-privacy');
      privacy.textContent = response.recipient_name
        ? `${policyCopy.visible}: ${response.recipient_name} — ${policyCopy.ends}` : t('livePrivacy');
      if (response.start_allowed === false && response.available_from) {
        noticeElement.textContent = `${policyCopy.opens} ${formatTime(response.available_from, lang)}`;
      }
      viewerSharingId = typeof response.viewer_sharing_id === 'string' ? response.viewer_sharing_id : null;
      if (localSharing && response.viewer_sharing === false) {
        stopLocal({ send: false, notice: 'liveLeaseExpired' });
      }
      locations = Array.isArray(response.locations) ? response.locations : [];
      renderLocations();
    } catch (error) {
      if (!cleaned && token === generation) handleRequestFailure(error);
    } finally {
      polling = false;
    }
  }

  function toPositionPromise() {
    return new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true,
        timeout: 12_000,
        maximumAge: 0,
      });
    });
  }

  function handleGpsError(error) {
    if (error?.code === 1) setNotice('liveLocationPermissionDenied');
    else if (error?.code === 2) setNotice('liveLocationUnavailable');
    else setNotice('liveGpsError');
  }

  function isNearDropoff(position) {
    return Boolean(dropoffPoint && haversineMeters([position.coords.latitude, position.coords.longitude], dropoffPoint)
      <= 150 + Number(position.coords.accuracy || 0));
  }

  async function sendPosition(position, force = false, token = generation) {
    if (cleaned || token !== generation || !sharingId || !localSharing) return;
    const accuracy = Number(position.coords.accuracy);
    if (!Number.isFinite(accuracy) || accuracy > MAX_ACCURACY_M) {
      stopLocal({ notice: 'livePoorAccuracy', terminalStop: false });
      return;
    }
    const nearDropoff = isNearDropoff(position);
    // Stop collection on the arrival fix before waiting for network confirmation.
    if (nearDropoff && watchId !== null) {
      navigator.geolocation.clearWatch(watchId);
      watchId = null;
    }
    const now = Date.now();
    if (!force && !nearDropoff && now - lastSendAt < MIN_SEND_INTERVAL_MS) return;
    lastSendAt = now;
    const id = sharingId;
    try {
      const response = await apiCall('/api/share_location', 'POST', {
        booking_id: bookingId,
        sharing_id: id,
        lat: position.coords.latitude,
        lon: position.coords.longitude,
        accuracy,
      });
      if (token !== generation || cleaned) return;
      if (response?.sharing_allowed === false || response?.stopped_reason) {
        handleServerEnd({ ...response, sharing_allowed: false });
      } else if (nearDropoff) {
        // A differing server position must never cause the device to resume collecting.
        stopLocal({ notice: 'liveEnded' });
        await poll();
      }
    } catch (error) {
      if (!cleaned && token === generation) handleRequestFailure(error);
    }
  }

  async function startSharing() {
    if (cleaned || hidden || terminal || !sharingAllowed || starting || localSharing) return;
    if (!navigator.geolocation) {
      setNotice('liveLocationUnavailable');
      return;
    }
    const token = ++generation;
    starting = true;
    setNotice('');
    setStateClass();
    try {
      const position = await toPositionPromise();
      if (cleaned || token !== generation) return;
      if (!Number.isFinite(position.coords.accuracy) || position.coords.accuracy > MAX_ACCURACY_M) {
        starting = false;
        setNotice('livePoorAccuracy');
        setStateClass();
        return;
      }
      const response = await apiCall('/api/start_sharing', 'POST', { booking_id: bookingId });
      const id = response?.sharing_id;
      if (!id) throw new Error('Missing sharing lease.');
      if (cleaned || token !== generation) {
        await stopRequest(id, true);
        return;
      }
      sharingId = String(id);
      localSharing = true;
      starting = false;
      lastSendAt = 0;
      lastLocalPosition = position;
      setNotice('');
      setStateClass();
      await sendPosition(position, true, token);
      if (token !== generation || !sharingId || cleaned) return;
      watchId = navigator.geolocation.watchPosition(
        next => {
          if (token !== generation || !sharingId || cleaned) return;
          lastLocalPosition = next;
          void sendPosition(next, false, token);
        },
        error => {
          if (token !== generation || cleaned) return;
          handleGpsError(error);
          stopLocal({ notice: error?.code === 1 ? 'liveLocationPermissionDenied' : 'liveGpsError' });
        },
        { enableHighAccuracy: true, timeout: 12_000, maximumAge: 0 },
      );
    } catch (error) {
      if (cleaned || token !== generation) return;
      starting = false;
      if (typeof error?.code === 'number' && !error?.status) handleGpsError(error);
      else handleRequestFailure(error);
      setStateClass();
    }
  }

  function onVisibilityChange() {
    hidden = document.hidden;
    if (hidden) {
      clearInterval(pollTimer);
      clearInterval(freshnessTimer);
      pollTimer = null;
      freshnessTimer = null;
      if (sharingId || starting) stopLocal({ keepalive: true, notice: 'liveEnded' });
      locations = [];
      clearMarkers();
      renderLocations();
    } else if (!cleaned) {
      void poll();
      pollTimer = setInterval(() => void poll(), 5_000);
      freshnessTimer = setInterval(renderLocations, 5_000);
    }
    setStateClass();
  }

  function onPageHide() {
    if (sharingId || starting) stopLocal({ keepalive: true, notice: 'liveEnded' });
  }

  startButton.addEventListener('click', startSharing);
  const stopExplicitly = () => {
    // A reload never restarts GPS, but the owner can still revoke their existing lease.
    const remoteId = viewerSharingId;
    const hasLocalLease = Boolean(sharingId);
    stopLocal({ notice: 'liveEnded' });
    if (!hasLocalLease && remoteId) void stopRequest(remoteId);
  };
  stopButton.addEventListener('click', stopExplicitly);
  document.addEventListener('visibilitychange', onVisibilityChange);
  window.addEventListener('pagehide', onPageHide);

  if (bookingId) {
    void poll();
    if (!hidden) pollTimer = setInterval(() => void poll(), 5_000);
  } else {
    setNotice('liveNotAllowed');
  }
  freshnessTimer = hidden ? null : setInterval(renderLocations, 5_000);
  setStateClass();

  return function cleanup() {
    if (cleaned) return;
    cleaned = true;
    clearInterval(pollTimer);
    clearInterval(freshnessTimer);
    pollTimer = null;
    freshnessTimer = null;
    stopLocal({ keepalive: true, notice: '' });
    startButton.removeEventListener('click', startSharing);
    stopButton.removeEventListener('click', stopExplicitly);
    document.removeEventListener('visibilitychange', onVisibilityChange);
    window.removeEventListener('pagehide', onPageHide);
    locations = [];
    map?.stop();
    clearMarkers();
    for (const marker of endpointMarkers) marker.remove();
    endpointMarkers = [];
    routeLine?.remove();
    routeLine = null;
    cleanupBasemap?.();
    cleanupBasemap = null;
    map?.remove();
    map = null;
    element.replaceChildren();
  };
}
