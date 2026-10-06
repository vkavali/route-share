const copy = {
  en: {
    brand: 'Route Share', languageLabel: 'Language', loadingTitle: 'Opening shared journey',
    loadingBody: 'Checking whether this journey link is still available…',
    title: 'Journey shared with you', dateLabel: 'Journey date', statusLabel: 'Status',
    pickupLabel: 'Pickup', dropoffLabel: 'Drop-off', driverLabel: 'Driver', vehicleLabel: 'Vehicle',
    aliasLabel: 'Shared with', safetyNotice: 'This is a trip summary, not live location or emergency monitoring. For an emergency in India, call 112.',
    copyLink: 'Copy link', copied: 'Link copied', copyFailed: 'Copy the link from the field below.',
    callEmergency: 'Call 112', retry: 'Try again', unavailableTitle: 'Journey link unavailable',
    unavailableBody: 'This link has expired, was revoked, or the journey is no longer available.',
    networkBody: 'The journey could not be checked right now. Its details are hidden; try again.',
    noTokenTitle: 'Journey link unavailable', noTokenBody: 'This link is missing or incomplete.',
    tripPublished: 'Scheduled', tripStarted: 'In progress', unknownDate: 'Date unavailable',
    notProvided: 'Not provided',
  },
  te: {
    brand: 'రూట్ షేర్', languageLabel: 'భాష', loadingTitle: 'షేర్ చేసిన ప్రయాణాన్ని తెరుస్తున్నాం',
    loadingBody: 'ఈ ప్రయాణ లింక్ ఇంకా అందుబాటులో ఉందో చూస్తున్నాం…',
    title: 'మీతో ప్రయాణ వివరాలు షేర్ చేశారు', dateLabel: 'ప్రయాణ తేదీ', statusLabel: 'స్థితి',
    pickupLabel: 'పికప్', dropoffLabel: 'డ్రాప్-ఆఫ్', driverLabel: 'డ్రైవర్', vehicleLabel: 'వాహనం',
    aliasLabel: 'ఎవరితో షేర్ చేశారు', safetyNotice: 'ఇవి ప్రయాణ వివరాలు మాత్రమే; లైవ్ లొకేషన్ లేదా అత్యవసర పర్యవేక్షణ కాదు. భారతదేశంలో అత్యవసర పరిస్థితికి 112కు కాల్ చేయండి.',
    copyLink: 'లింక్ కాపీ చేయండి', copied: 'లింక్ కాపీ అయింది', copyFailed: 'కింద ఉన్న ఫీల్డ్‌లోని లింక్‌ను కాపీ చేయండి.',
    callEmergency: '112కు కాల్ చేయండి', retry: 'మళ్లీ ప్రయత్నించండి', unavailableTitle: 'ప్రయాణ లింక్ అందుబాటులో లేదు',
    unavailableBody: 'ఈ లింక్ గడువు ముగిసింది, రద్దు చేశారు లేదా ప్రయాణం ఇక అందుబాటులో లేదు.',
    networkBody: 'ఇప్పుడు ప్రయాణాన్ని తనిఖీ చేయలేకపోయాం. వివరాలు దాచాం; మళ్లీ ప్రయత్నించండి.',
    noTokenTitle: 'ప్రయాణ లింక్ అందుబాటులో లేదు', noTokenBody: 'ఈ లింక్ లేదు లేదా పూర్తిగా లేదు.',
    tripPublished: 'షెడ్యూల్ అయింది', tripStarted: 'ప్రయాణంలో ఉంది', unknownDate: 'తేదీ అందుబాటులో లేదు',
    notProvided: 'వివరాలు ఇవ్వలేదు',
  },
};

const page = document.querySelector('#trip-share');
const languageSelect = document.querySelector('#trip-share-language');
const title = document.querySelector('#trip-share-title');
const status = document.querySelector('#trip-share-status');
const details = document.querySelector('#trip-share-data');
const retry = document.querySelector('#trip-share-retry');
const copyButton = document.querySelector('#trip-share-copy');
const copyFallback = document.querySelector('#trip-share-copy-fallback');
const fields = Object.fromEntries([...document.querySelectorAll('[data-field]')].map((node) => [node.dataset.field, node]));
const allowedFields = ['trip_date', 'trip_status', 'pickup', 'dropoff', 'driver_name', 'vehicle_model', 'vehicle_plate'];

let lang = new URLSearchParams(location.search).get('lang') === 'te' ? 'te' : 'en';
let bearer = '';
let csrfToken = '';
let expiryTimer = 0;
let pollTimer = 0;
let inFlight = false;
let isTerminal = false;
let errorKind = 'loading';

const text = (key) => copy[lang][key] || copy.en[key] || key;

function applyLanguage() {
  document.documentElement.lang = lang;
  languageSelect.value = lang;
  document.querySelectorAll('[data-copy]').forEach((node) => {
    const value = text(node.dataset.copy);
    if (node.matches('label[for], [aria-label]')) node.setAttribute('aria-label', value);
    else node.textContent = value;
  });
  if (details.hidden) {
    title.textContent = errorKind === 'loading' ? text('loadingTitle') : text('unavailableTitle');
    if (errorKind === 'network') status.textContent = text('networkBody');
    else if (errorKind === 'missing') status.textContent = text('noTokenBody');
    else if (errorKind === 'terminal') status.textContent = text('unavailableBody');
  }
}

function setUnavailable({ transient = false, missing = false } = {}) {
  clearTimeout(expiryTimer);
  details.hidden = true;
  for (const node of Object.values(fields)) node.textContent = '';
  document.querySelector('[data-plate-wrap]').hidden = true;
  document.querySelector('[data-alias-wrap]').hidden = true;
  copyFallback.hidden = true;
  copyFallback.value = '';
  copyButton.textContent = text('copyLink');
  title.textContent = text(missing ? 'noTokenTitle' : 'unavailableTitle');
  status.textContent = text(transient ? 'networkBody' : missing ? 'noTokenBody' : 'unavailableBody');
  retry.hidden = !transient || !bearer;
  isTerminal = !transient;
  errorKind = transient ? 'network' : missing ? 'missing' : 'terminal';
  if (isTerminal) bearer = '';
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return text('unknownDate');
  try {
    return new Intl.DateTimeFormat(lang === 'te' ? 'te-IN' : 'en-IN', {
      dateStyle: 'full', timeStyle: 'short', timeZone: 'Asia/Kolkata',
    }).format(date);
  } catch {
    return text('unknownDate');
  }
}

function validSnapshot(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  if (!allowedFields.every((key) => typeof value[key] === 'string')) return false;
  if (!['published', 'started'].includes(value.trip_status)) return false;
  if (!value.pickup || !value.dropoff || !value.driver_name) return false;
  const expiry = Date.parse(value.expires_at);
  return Number.isFinite(expiry) && expiry > Date.now() && Number.isFinite(Date.parse(value.trip_date));
}

function renderSnapshot(value) {
  fields.trip_date.textContent = formatDate(value.trip_date);
  fields.trip_status.textContent = value.trip_status === 'started' ? text('tripStarted') : text('tripPublished');
  fields.pickup.textContent = value.pickup;
  fields.dropoff.textContent = value.dropoff;
  fields.driver_name.textContent = value.driver_name;
  fields.vehicle_model.textContent = value.vehicle_model || text('notProvided');
  fields.vehicle_plate.textContent = value.vehicle_plate || text('notProvided');
  document.querySelector('[data-plate-wrap]').hidden = false;
  fields.alias.textContent = typeof value.alias === 'string' ? value.alias : '';
  document.querySelector('[data-alias-wrap]').hidden = !fields.alias.textContent;
  title.textContent = text('title');
  status.textContent = `${text('statusLabel')}: ${fields.trip_status.textContent}`;
  details.hidden = false;
  retry.hidden = true;
  isTerminal = false;
  errorKind = 'loaded';
  const remaining = Date.parse(value.expires_at) - Date.now();
  clearTimeout(expiryTimer);
  expiryTimer = window.setTimeout(() => setUnavailable(), Math.max(0, remaining));
}

async function getCsrfToken() {
  if (csrfToken) return csrfToken;
  const response = await fetch('/api/bootstrap', {
    method: 'GET', credentials: 'same-origin', cache: 'no-store',
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error('bootstrap unavailable');
  const payload = await response.json();
  if (typeof payload.csrf_token !== 'string' || !payload.csrf_token) throw new Error('csrf unavailable');
  csrfToken = payload.csrf_token;
  return csrfToken;
}

async function refresh() {
  if (!bearer || isTerminal || inFlight || document.visibilityState !== 'visible') return;
  inFlight = true;
  try {
    const csrf = await getCsrfToken();
    const response = await fetch('/api/shared_trip', {
      method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify({ token: bearer }),
    });
    if (!response.ok) {
      if (response.status >= 500 || response.status === 429) setUnavailable({ transient: true });
      else setUnavailable();
      return;
    }
    const snapshot = await response.json();
    if (!validSnapshot(snapshot)) {
      setUnavailable();
      return;
    }
    renderSnapshot(snapshot);
  } catch {
    setUnavailable({ transient: true });
  } finally {
    inFlight = false;
  }
}

function originalShareUrl() {
  const params = new URLSearchParams(location.search);
  params.set('lang', lang);
  return `${location.origin}${location.pathname}?${params.toString()}#${bearer}`;
}

languageSelect.addEventListener('change', () => {
  lang = languageSelect.value === 'te' ? 'te' : 'en';
  const params = new URLSearchParams(location.search);
  params.set('lang', lang);
  history.replaceState(history.state, '', `${location.pathname}?${params.toString()}`);
  applyLanguage();
  if (!details.hidden && bearer) refresh();
});

copyButton.addEventListener('click', async () => {
  if (!bearer) return;
  const url = originalShareUrl();
  try {
    await navigator.clipboard.writeText(url);
    copyButton.textContent = text('copied');
  } catch {
    copyFallback.value = url;
    copyFallback.hidden = false;
    copyFallback.focus();
    copyFallback.select();
    status.textContent = text('copyFailed');
  }
});

retry.addEventListener('click', () => refresh());
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') refresh();
});
window.addEventListener('pagehide', () => {
  clearTimeout(expiryTimer);
  clearInterval(pollTimer);
  bearer = '';
});

applyLanguage();
try {
  bearer = decodeURIComponent(location.hash.slice(1));
} catch {
  bearer = '';
}
// Keep the bearer out of the address bar/history after capturing it in memory.
history.replaceState(history.state, '', `${location.pathname}${location.search}`);
if (!bearer || bearer.length > 4096) {
  setUnavailable({ missing: true });
} else {
  refresh();
  pollTimer = window.setInterval(refresh, 30_000);
}
