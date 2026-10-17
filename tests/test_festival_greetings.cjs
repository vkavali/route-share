const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const moduleUrl = pathToFileURL(path.resolve(__dirname, '../static/festival-greetings.js')).href;
  const { createFestivalGreeting, indiaDateParts, selectFestivalGreeting, startFestivalGreetingUpdates } = await import(moduleUrl);

  const indiaMidnight = new Date('2026-01-25T18:30:00.000Z');
  assert.deepEqual(indiaDateParts(new Date('2026-01-25T18:29:59.000Z')), { year: 2026, month: 1, day: 25 });
  assert.deepEqual(indiaDateParts(indiaMidnight), { year: 2026, month: 1, day: 26 });
  assert.equal(selectFestivalGreeting(indiaMidnight).id, 'republic-day', 'IST midnight selects the new India date');
  assert.equal(selectFestivalGreeting(new Date('2026-02-14T18:30:00.000Z')).id, 'maha-shivratri');
  assert.equal(selectFestivalGreeting(new Date('2027-02-15T12:00:00.000Z')), null, 'movable 2026 dates are not extrapolated');
  assert.equal(selectFestivalGreeting(new Date('2027-01-26T12:00:00.000Z')).id, 'republic-day', 'fixed annual dates repeat');
  assert.equal(selectFestivalGreeting(new Date('2026-06-01T12:00:00.000Z')), null, 'non-event dates have no greeting');
  const eidOnam = selectFestivalGreeting(new Date('2026-08-26T12:00:00.000Z'));
  assert.equal(eidOnam.id, 'eid-e-milad+onam', 'overlapping movable events have a stable combined id');
  assert.equal(eidOnam.en, 'Eid-e-Milad · Onam', 'overlapping event names are combined');
  assert.equal(eidOnam.sourceUrls.length, 2, 'combined event retains both source records');

  const values = new Map();
  const storage = {
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, value); },
  };
  const greeting = createFestivalGreeting({ storage });
  assert.match(greeting.html('te', true, indiaMidnight), /గణతంత్ర దినోత్సవం/);
  assert.equal(greeting.html('fr', true, indiaMidnight).includes('Republic Day'), true, 'unknown languages fall back to English');
  assert.equal(greeting.html('en', false, indiaMidnight), '', 'route visibility suppresses the banner');
  assert.equal(greeting.html('en', true, new Date('2026-06-01T12:00:00.000Z')), '', 'no event produces no blank banner');
  assert.equal(greeting.dismiss('republic-day', indiaMidnight), true);
  assert.equal(greeting.html('en', true, indiaMidnight), '', 'dismissal removes the banner');
  assert.equal(createFestivalGreeting({ storage }).html('en', true, indiaMidnight), '', 'dismissal survives remount through shared storage');

  const combinedGreeting = createFestivalGreeting({ storage });
  const eidOnamDate = new Date('2026-08-26T12:00:00.000Z');
  assert.match(combinedGreeting.html('en', true, eidOnamDate), /Eid-e-Milad · Onam/);
  assert.equal(combinedGreeting.dismiss('eid-e-milad+onam', eidOnamDate), true);
  assert.equal(createFestivalGreeting({ storage }).html('en', true, eidOnamDate), '', 'combined dismissal survives remount');

  const blockedStorage = {
    getItem() { throw new Error('blocked'); },
    setItem() { throw new Error('blocked'); },
  };
  const memoryOnly = createFestivalGreeting({ storage: blockedStorage });
  assert.match(memoryOnly.html('en', true, indiaMidnight), /Republic Day/);
  assert.equal(memoryOnly.dismiss('republic-day', indiaMidnight), true);
  assert.equal(memoryOnly.html('en', true, indiaMidnight), '', 'storage failures fall back to in-memory dismissal');

  const muharram = createFestivalGreeting({ storage }).model('en', true, new Date('2026-06-26T12:00:00.000Z'));
  assert.match(muharram.body, /respect/);
  const goodFriday = createFestivalGreeting({ storage }).model('en', true, new Date('2026-04-02T18:30:00.000Z'));
  assert.match(goodFriday.body, /remember.*respect/i, 'Good Friday uses respectful copy');

  function eventTarget() {
    const listeners = new Map();
    return {
      visibilityState: 'visible', listeners,
      addEventListener(type, listener) {
        if (!listeners.has(type)) listeners.set(type, new Set());
        listeners.get(type).add(listener);
      },
      removeEventListener(type, listener) { listeners.get(type)?.delete(listener); },
      emit(type, event = {}) { for (const listener of [...(listeners.get(type) || [])]) listener(event); },
    };
  }
  const documentTarget = eventTarget();
  const windowTarget = eventTarget();
  const activeTimers = new Set();
  let nextTimer = 0;
  let callbackCount = 0;
  let lifecycleNow = new Date('2026-04-02T18:30:00.000Z');
  const stopUpdates = startFestivalGreetingUpdates({
    onChange() { callbackCount++; },
    target: documentTarget,
    windowTarget,
    now: () => lifecycleNow,
    setIntervalFn() { const id = ++nextTimer; activeTimers.add(id); return id; },
    clearIntervalFn(id) { activeTimers.delete(id); },
  });
  assert.equal(activeTimers.size, 1, 'one date-check timer is active');
  assert.equal(windowTarget.listeners.get('pageshow').size, 1, 'one BFCache restore listener is installed');
  assert.equal(documentTarget.listeners.get('visibilitychange').size, 1, 'one visibility listener is installed');
  windowTarget.emit('storage', { key: 'seatpal-festival-dismissals-v1' });
  assert.equal(callbackCount, 1, 'cross-tab dismissal changes trigger a redraw');
  windowTarget.emit('storage', { key: 'unrelated-setting' });
  assert.equal(callbackCount, 1, 'unrelated storage changes do not trigger a redraw');
  windowTarget.emit('pagehide', { persisted: true });
  assert.equal(activeTimers.size, 0, 'pagehide suspends the timer before BFCache');
  lifecycleNow = new Date('2026-04-03T18:30:00.000Z');
  windowTarget.emit('pageshow', { persisted: true });
  assert.equal(callbackCount, 2, 'BFCache restore rerenders for the current India date');
  assert.equal(activeTimers.size, 1, 'BFCache restore resumes exactly one timer');
  windowTarget.emit('pageshow', { persisted: true });
  assert.equal(activeTimers.size, 1, 'repeated restore events do not duplicate timers');
  stopUpdates();
  assert.equal(activeTimers.size, 0, 'cleanup clears the resumed timer');
  assert.equal(documentTarget.listeners.get('visibilitychange').size, 0, 'cleanup removes visibility listeners');
  assert.equal(windowTarget.listeners.get('storage').size, 0, 'cleanup removes storage listeners');
  assert.equal(windowTarget.listeners.get('pagehide').size, 0, 'cleanup removes pagehide listeners');
  assert.equal(windowTarget.listeners.get('pageshow').size, 0, 'cleanup removes lifecycle listeners');
  console.log('festival-greetings contract tests passed');
})();
