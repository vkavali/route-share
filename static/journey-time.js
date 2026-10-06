const IST_OFFSET_MINUTES = 330;
const FIFTEEN_MINUTES = 15 * 60 * 1000;
const DEFAULT_LEAD_MINUTES = 30;
const DEFAULT_WINDOW_HOURS = 2;
const MAX_WINDOW_HOURS = 12;
const MAX_DAYS = 90;

function asDate(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) throw new TypeError('A valid current date is required.');
  return date;
}

function pad(value) { return String(value).padStart(2, '0'); }

/** Format a wall-clock value for datetime-local fields as India Standard Time. */
export function formatIstInput(value) {
  const shifted = new Date(asDate(value).getTime() + IST_OFFSET_MINUTES * 60_000);
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}T${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}`;
}

function localValueToEpoch(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return NaN;
  const epoch = Date.parse(`${value}:00+05:30`);
  if (!Number.isFinite(epoch)) return NaN;
  // Date.parse normalizes impossible dates (for example Feb 31); reject those.
  return formatIstInput(new Date(epoch)) === value ? epoch : NaN;
}

export function seedJourneyTimes(value = new Date()) {
  const now = asDate(value);
  const lead = now.getTime() + DEFAULT_LEAD_MINUTES * 60_000;
  const startMs = Math.ceil(lead / FIFTEEN_MINUTES) * FIFTEEN_MINUTES;
  const endMs = startMs + DEFAULT_WINDOW_HOURS * 60 * 60_000;
  return {
    start: formatIstInput(new Date(startMs)),
    end: formatIstInput(new Date(endMs)),
    departure: formatIstInput(new Date(startMs)),
    min: formatIstInput(now),
    max: formatIstInput(new Date(now.getTime() + MAX_DAYS * 24 * 60 * 60_000)),
  };
}

export function seedBlankJourneyTimes({ start, end, departure }, value = new Date()) {
  const seeded = seedJourneyTimes(value);
  if (start && !start.value) start.value = seeded.start;
  const startMs = start ? localValueToEpoch(start.value) : NaN;
  const startValue = Number.isFinite(startMs) ? start.value : seeded.start;
  if (end && !end.value) {
    end.value = Number.isFinite(startMs)
      ? formatIstInput(new Date(startMs + DEFAULT_WINDOW_HOURS * 60 * 60_000))
      : seeded.end;
  }
  if (departure && !departure.value) departure.value = startValue;
  return seeded;
}

export function validateJourneyTime(inputValue, value = new Date()) {
  const now = asDate(value).getTime();
  const timestamp = localValueToEpoch(inputValue);
  if (!Number.isFinite(timestamp)) return { valid: false, errorKey: 'invalidDate' };
  const limit = now + MAX_DAYS * 24 * 60 * 60_000;
  if (timestamp > limit) return { valid: false, errorKey: 'timeTooFar' };
  if (timestamp < now) return { valid: false, errorKey: 'timePast' };
  return { valid: true, errorKey: null };
}

export function validatePickupWindow(startValue, endValue, value = new Date()) {
  const startCheck = validateJourneyTime(startValue, value);
  if (!startCheck.valid) return { ...startCheck, field: 'start' };
  const endCheck = validateJourneyTime(endValue, value);
  if (!endCheck.valid) return { ...endCheck, field: 'end' };
  const start = localValueToEpoch(startValue);
  const end = localValueToEpoch(endValue);
  if (end <= start) return { valid: false, errorKey: 'timeEndBeforeStart', field: 'end' };
  if (end - start > MAX_WINDOW_HOURS * 60 * 60_000) return { valid: false, errorKey: 'timeWindowTooWide', field: 'end' };
  return { valid: true, errorKey: null, field: null };
}

/** Keep native date limits current and expose localized field-specific errors. */
export function bindPickupWindow(startInput, endInput, { t, now = () => new Date() } = {}) {
  if (!startInput || !endInput || typeof t !== 'function') throw new TypeError('Start, end, and translator are required.');
  let disposed = false;
  const refresh = () => {
    if (disposed) return;
    const seeded = seedJourneyTimes(now());
    startInput.min = seeded.min;
    startInput.max = seeded.max;
    const startMs = localValueToEpoch(startInput.value);
    const endMin = Number.isFinite(startMs) ? Math.max(Date.parse(`${seeded.min}:00+05:30`), startMs) : Date.parse(`${seeded.min}:00+05:30`);
    endInput.min = formatIstInput(new Date(endMin));
    const endMax = Number.isFinite(startMs) ? Math.min(startMs + MAX_WINDOW_HOURS * 60 * 60_000, Date.parse(`${seeded.max}:00+05:30`)) : Date.parse(`${seeded.max}:00+05:30`);
    endInput.max = formatIstInput(new Date(Math.max(endMin, endMax)));
    const current = now();
    const startResult = validateJourneyTime(startInput.value, current);
    const endResult = validateJourneyTime(endInput.value, current);
    const result = validatePickupWindow(startInput.value, endInput.value, current);
    startInput.setCustomValidity(startResult.valid ? '' : t(startResult.errorKey));
    const endError = endResult.valid
      ? (result.field === 'end' && !result.valid ? result.errorKey : null)
      : endResult.errorKey;
    endInput.setCustomValidity(endError ? t(endError) : '');
    return result;
  };
  const events = ['focus', 'input', 'change'];
  for (const input of [startInput, endInput]) for (const type of events) input.addEventListener(type, refresh);
  refresh();
  return {
    refresh,
    validate: () => refresh(),
    cleanup() {
      disposed = true;
      for (const input of [startInput, endInput]) for (const type of events) input.removeEventListener(type, refresh);
    },
  };
}
