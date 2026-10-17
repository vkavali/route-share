const TIME_ZONE = 'Asia/Kolkata';
const STORAGE_KEY = 'seatpal-festival-dismissals-v1';

const COPY = {
  en: {
    body: 'Wishing you a peaceful and joyful day. Travel safely with SeatPal.',
    remembrance: 'We remember this day with respect. Wishing you and your loved ones peace.',
    dismiss: 'Dismiss greeting',
  },
  te: {
    body: 'మీకు ప్రశాంతమైన, ఆనందమైన రోజు కావాలని కోరుకుంటున్నాం. SeatPalతో సురక్షితంగా ప్రయాణించండి.',
    remembrance: 'ఈ రోజును గౌరవంతో స్మరించుకుంటున్నాం. మీకు, మీ ఆత్మీయులకు శాంతి కలగాలి.',
    dismiss: 'శుభాకాంక్షను మూసివేయండి',
  },
  hi: {
    body: 'आपका दिन शांतिपूर्ण और आनंदमय हो। SeatPal के साथ सुरक्षित यात्रा करें।',
    remembrance: 'हम इस दिन को सम्मान के साथ स्मरण करते हैं। आपको और आपके प्रियजनों को शांति मिले।',
    dismiss: 'शुभकामना बंद करें',
  },
};

const MOVABLE_2026 = [
  ['sankranti', 1, 14, 'Sankranti', 'సంక్రాంతి', 'मकर संक्रांति', 'cgcaAP'],
  ['maha-shivratri', 2, 15, 'Maha Shivratri', 'మహా శివరాత్రి', 'महाशिवरात्रि', 'cgcaAP'],
  ['holi', 3, 4, 'Holi', 'హోలీ', 'होली', 'cgcaAP'],
  ['ugadi', 3, 19, 'Ugadi', 'ఉగాది', 'उगादि', 'cgcaAP'],
  ['eid-al-fitr', 3, 21, 'Eid al-Fitr', 'ఈద్ అల్-ఫిత్ర్', 'ईद-उल-फ़ित्र', 'india-post'],
  ['mahavir-jayanti', 3, 31, 'Mahavir Jayanti', 'మహావీర్ జయంతి', 'महावीर जयंती', 'india-post'],
  ['good-friday', 4, 3, 'Good Friday', 'గుడ్ ఫ్రైడే', 'गुड फ्राइडे', 'india-post', true],
  ['buddha-purnima', 5, 1, 'Buddha Purnima', 'బుద్ధ పూర్ణిమ', 'बुद्ध पूर्णिमा', 'india-post'],
  ['eid-al-adha', 5, 27, 'Eid al-Adha', 'ఈద్ అల్-అదా', 'ईद-उल-अज़हा', 'india-post'],
  ['muharram', 6, 26, 'Muharram', 'ముహర్రం', 'मुहर्रम', 'india-post', true],
  ['onam', 8, 26, 'Onam', 'ఓణం', 'ओणम', 'cgcaAP'],
  ['eid-e-milad', 8, 26, 'Eid-e-Milad', 'ఈద్-ఎ-మిలాద్', 'ईद-ए-मिलाद', 'india-post'],
  ['raksha-bandhan', 8, 28, 'Raksha Bandhan', 'రక్షా బంధన్', 'रक्षा बंधन', 'cgcaAP'],
  ['janmashtami', 9, 4, 'Janmashtami', 'జన్మాష్టమి', 'जन्माष्टमी', 'cgcaAP'],
  ['ganesh-chaturthi', 9, 14, 'Ganesh Chaturthi', 'గణేష్ చతుర్థి', 'गणेश चतुर्थी', 'cgcaAP'],
  ['bathukamma', 10, 18, 'Bathukamma', 'బతుకమ్మ', 'बथुकम्मा', 'telangana'],
  ['dussehra', 10, 20, 'Dussehra', 'దసరా', 'दशहरा', 'india-post'],
  ['diwali', 11, 8, 'Diwali', 'దీపావళి', 'दीवाली', 'india-post'],
  ['guru-nanak-jayanti', 11, 24, 'Guru Nanak Jayanti', 'గురు నానక్ జయంతి', 'गुरु नानक जयंती', 'india-post'],
].map(([id, month, day, en, te, hi, source, remembrance = false]) => ({
  id, month, day, en, te, hi, source, remembrance, year: 2026, priority: 10,
}));

const ANNUAL = [
  ['new-year', 1, 1, 'New Year', 'నూతన సంవత్సరం', 'नववर्ष'],
  ['republic-day', 1, 26, 'Republic Day', 'గణతంత్ర దినోత్సవం', 'गणतंत्र दिवस'],
  ['independence-day', 8, 15, 'Independence Day', 'స్వాతంత్ర్య దినోత్సవం', 'स्वतंत्रता दिवस'],
  ['gandhi-jayanti', 10, 2, 'Gandhi Jayanti', 'గాంధీ జయంతి', 'गांधी जयंती'],
  ['christmas', 12, 25, 'Christmas', 'క్రిస్మస్', 'क्रिसमस'],
].map(([id, month, day, en, te, hi]) => ({ id, month, day, en, te, hi, priority: 100, source: 'annual-fixed' }));

const SOURCE_URLS = {
  'india-post': 'https://www.indiapost.gov.in/holidays-list',
  cgcaAP: 'https://www.cgca.gov.in/ccaAP/list-of-holiday',
  telangana: 'https://www.telangana.gov.in/Downloads/calendar-2026/',
};

export const FESTIVAL_CATALOG = Object.freeze([
  ...ANNUAL,
  ...MOVABLE_2026,
].map(event => Object.freeze({ ...event, sourceUrl: SOURCE_URLS[event.source] || null })));

export function indiaDateParts(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const value = type => Number(parts.find(part => part.type === type)?.value);
  return { year: value('year'), month: value('month'), day: value('day') };
}

export function selectFestivalGreeting(now = new Date()) {
  const date = indiaDateParts(now);
  const matching = FESTIVAL_CATALOG.filter(event => event.month === date.month
    && event.day === date.day
    && (!event.year || event.year === date.year))
    .sort((a, b) => b.priority - a.priority || a.id.localeCompare(b.id));
  if (!matching.length) return null;
  const top = matching[0];
  // Fixed national observances intentionally take precedence over other events.
  const samePriority = top.priority >= 100 ? [top] : matching.filter(event => event.priority === top.priority);
  const grouped = [...samePriority].sort((a, b) => a.id.localeCompare(b.id));
  const ids = grouped.map(event => event.id);
  const sources = [...new Set(grouped.map(event => event.source))];
  const titles = Object.fromEntries(['en', 'te', 'hi'].map(language => [
    language, grouped.map(event => event[language]).join(' · '),
  ]));
  return {
    ...top,
    ...titles,
    id: ids.join('+'),
    ids,
    events: grouped,
    sources,
    sourceUrls: [...new Set(grouped.map(event => event.sourceUrl).filter(Boolean))],
    remembrance: grouped.some(event => event.remembrance),
    date,
  };
}

export function festivalDismissalKey(event, date) {
  return `${event.id}:${date.year}-${String(date.month).padStart(2, '0')}-${String(date.day).padStart(2, '0')}`;
}

function safeRead(storage) {
  try {
    const parsed = JSON.parse(storage?.getItem(STORAGE_KEY) || '{}');
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch { return {}; }
}

function safeWrite(storage, values) {
  try { storage?.setItem(STORAGE_KEY, JSON.stringify(values)); } catch { /* memory state remains usable */ }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function createFestivalGreeting({ storage, now = () => new Date() } = {}) {
  if (storage === undefined) {
    try { storage = globalThis.localStorage; } catch { storage = null; }
  }
  let memoryDismissals = {};
  const dismissals = () => ({ ...safeRead(storage), ...memoryDismissals });
  const model = (lang = 'en', visible = true, at = now()) => {
    if (!visible) return null;
    const event = selectFestivalGreeting(at);
    if (!event || dismissals()[festivalDismissalKey(event, event.date)]) return null;
    const language = COPY[lang] ? lang : 'en';
    return {
      ...event,
      title: event[language],
      body: COPY[language][event.remembrance ? 'remembrance' : 'body'],
      dismissLabel: COPY[language].dismiss,
      language,
      dismissalKey: festivalDismissalKey(event, event.date),
    };
  };
  return {
    model,
    dismiss(eventId, at = now()) {
      const event = selectFestivalGreeting(at);
      if (!event || event.id !== eventId) return false;
      const key = festivalDismissalKey(event, event.date);
      memoryDismissals[key] = true;
      safeWrite(storage, { ...dismissals(), [key]: true });
      return true;
    },
    html(lang = 'en', visible = true, at = now()) {
      const greeting = model(lang, visible, at);
      if (!greeting) return '';
      return `<aside class="festival-greeting${greeting.remembrance ? ' festival-greeting--remembrance' : ''}" data-festival-greeting data-event-id="${escapeHtml(greeting.id)}" lang="${greeting.language}" role="status"><div class="festival-greeting__copy"><strong>${escapeHtml(greeting.title)}</strong><span>${escapeHtml(greeting.body)}</span></div><button type="button" class="festival-greeting__dismiss" data-action="festival-dismiss" data-id="${escapeHtml(greeting.id)}" data-festival-dismiss="${escapeHtml(greeting.id)}" aria-label="${escapeHtml(greeting.dismissLabel)}">×</button></aside>`;
    },
  };
}

export function startFestivalGreetingUpdates({
  onChange,
  intervalMs = 60_000,
  target = globalThis.document,
  windowTarget = globalThis,
  now = () => new Date(),
  setIntervalFn = globalThis.setInterval,
  clearIntervalFn = globalThis.clearInterval,
} = {}) {
  if (!target || typeof onChange !== 'function') return () => {};
  const initialDate = indiaDateParts(now());
  let lastDate = `${initialDate.year}-${initialDate.month}-${initialDate.day}`;
  let timer = null;
  let disposed = false;
  const refresh = () => {
    const date = indiaDateParts(now());
    const dateKey = `${date.year}-${date.month}-${date.day}`;
    if (dateKey !== lastDate && target.visibilityState !== 'hidden') {
      lastDate = dateKey;
      onChange();
    }
  };
  const startTimer = () => { if (!disposed && timer === null) timer = setIntervalFn(refresh, intervalMs); };
  const stopTimer = () => { if (timer !== null) { clearIntervalFn(timer); timer = null; } };
  target.addEventListener('visibilitychange', refresh);
  const storageHandler = event => { if (!event.key || event.key === STORAGE_KEY) onChange(); };
  windowTarget.addEventListener?.('storage', storageHandler);
  const pageHide = () => stopTimer();
  const pageShow = event => {
    if (event?.persisted) {
      const date = indiaDateParts(now());
      lastDate = `${date.year}-${date.month}-${date.day}`;
      onChange();
      startTimer();
    }
  };
  windowTarget.addEventListener?.('pagehide', pageHide);
  windowTarget.addEventListener?.('pageshow', pageShow);
  startTimer();
  return () => {
    disposed = true;
    stopTimer();
    target.removeEventListener('visibilitychange', refresh);
    windowTarget.removeEventListener?.('storage', storageHandler);
    windowTarget.removeEventListener?.('pagehide', pageHide);
    windowTarget.removeEventListener?.('pageshow', pageShow);
  };
}
