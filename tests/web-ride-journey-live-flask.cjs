/* Real Chrome journey against an isolated Flask process and temporary SQLite. */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const python = process.env.PYTHON || 'python';
const password = 'local-ui-fixture-only';
const labels = { origin: 'Kondapur', destination: 'Vijayawada' };
const points = {
  origin: { lat: '17.460', lon: '78.357' },
  destination: { lat: '16.506', lon: '80.648' },
};

function startFixture() {
  const server = spawn(python, ['tests/ride-live-fixture.py'], {
    cwd: root, stdio: ['ignore', 'pipe', 'inherit'],
  });
  let pending = '';
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('ride fixture startup timed out')), 20000);
    server.stdout.on('data', chunk => {
      pending += chunk.toString();
      const line = pending.split(/\r?\n/)[0];
      try { const data = JSON.parse(line); clearTimeout(timer); resolve(data); } catch {}
    });
    server.once('error', reject);
    server.once('exit', code => reject(new Error(`ride fixture exited ${code}`)));
  });
  return { server, ready };
}

async function setPoint(page, name) {
  await page.locator(`#drive-form [name="${name}_label"]`).evaluate((element, value) => { element.value = value; }, labels[name]);
  await page.locator(`#drive-form [name="${name}_lat"]`).evaluate((element, value) => { element.value = value; }, points[name].lat);
  await page.locator(`#drive-form [name="${name}_lon"]`).evaluate((element, value) => { element.value = value; }, points[name].lon);
}

async function setSearchPoint(page, name) {
  await page.locator(`#search-form [name="${name}_label"]`).evaluate((element, value) => { element.value = value; }, labels[name]);
  await page.locator(`#search-form [name="${name}_lat"]`).evaluate((element, value) => { element.value = value; }, points[name].lat);
  await page.locator(`#search-form [name="${name}_lon"]`).evaluate((element, value) => { element.value = value; }, points[name].lon);
}

async function ensureDetailsOpen(page, selector) {
  await page.locator(selector).evaluate(details => {
    if (!details.open) details.querySelector('summary').click();
  });
}

async function runJourney(browser, iteration) {
  const { server, ready } = startFixture();
  const { port } = await ready;
  const baseURL = `http://127.0.0.1:${port}`;
  const driverContext = await browser.newContext();
  const passengerContext = await browser.newContext();
  const driver = await driverContext.newPage();
  const passenger = await passengerContext.newPage();
  const api = [];
  const pageErrors = [];
  for (const page of [driver, passenger]) {
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.pathname.startsWith('/api/')) api.push({ path: url.pathname, status: response.status() });
    });
  }
  try {
    console.log(`START iteration ${iteration} on ${baseURL}`);
    await driver.goto(`${baseURL}/?app=1`);
    try { await driver.locator('#login-form').waitFor({ timeout: 10000 }); }
    catch { throw new Error(`login form unavailable on iteration ${iteration}: ${await driver.locator('body').innerText()}`); }
    await driver.locator('[data-account-choice="driver"]').click();
    await driver.locator('#login-password').fill(password);
    await driver.locator('#login-form button[type=submit]').click();
    await driver.locator('[data-action="menu-toggle"]').waitFor({ timeout: 10000 });
    await driver.evaluate(() => { location.hash = '#/inbox'; });
    await driver.getByText('No seat requests are waiting.').waitFor({ timeout: 10000 });
    await driver.evaluate(() => { location.hash = '#/drive-form'; });
    await driver.locator('#drive-form').waitFor();

    const depart = new Date(Date.now() + 3 * 60 * 60 * 1000);
    depart.setMinutes(0, 0, 0);
    const localDateTime = date => {
      return new Date(date.getTime() + 330 * 60000).toISOString().slice(0, 16);
    };
    await setPoint(driver, 'origin');
    await setPoint(driver, 'destination');
    await driver.locator('#drive-form [name="departure"]').fill(localDateTime(depart));
    await driver.locator('#drive-form .hf-offer-details > summary').click();
    await driver.locator('#drive-form [name="seat_rate_rupees_per_km"]').fill('1.25');
    await driver.locator('#drive-form [name="baggage_capacity_known"]').check();
    await driver.locator('#drive-form [name="capacity_small_bags"]').fill('2');
    await driver.locator('#drive-form [name="capacity_large_suitcases"]').fill('1');
    const previewResponse = driver.waitForResponse(response => new URL(response.url()).pathname === '/api/preview');
    await driver.locator('#drive-form .journey-submit').click();
    const previewResult = await Promise.race([previewResponse, driver.waitForTimeout(2500).then(() => null)]);
    if (!previewResult) throw new Error(`preview did not submit; visible errors: ${await driver.locator('[role="alert"]').allInnerTexts()}; page errors: ${pageErrors}; validity: ${JSON.stringify(await driver.locator('#drive-form').evaluate(form => ({valid:form.checkValidity(),invalid:[...form.elements].filter(input=>!input.checkValidity()).map(input=>({name:input.name,value:input.value,message:input.validationMessage,validity:input.validity}))}))) }; values: ${JSON.stringify(await driver.locator('#drive-form').evaluate(form => Object.fromEntries(new FormData(form))))}`);
    if (!previewResult.ok()) throw new Error(`preview failed ${previewResult.status()}: ${await previewResult.text()}`);
    await driver.locator('.preview-panel [data-action="publish"]').waitFor({ timeout: 10000 });
    assert.match(await driver.locator('.preview-panel').innerText(), /FIXTURE ONLY/);
    await driver.locator('.preview-panel [data-action="publish"]').click();
    await driver.locator('.rj-trip-card, [data-trip-id]').first().waitFor({ timeout: 10000 });

    await passenger.goto(`${baseURL}/?app=1`);
    await passenger.locator('#login-form').waitFor();
    await passenger.locator('[data-account-choice="passenger"]').click();
    await passenger.locator('#login-password').fill(password);
    await passenger.locator('#login-form button[type=submit]').click();
    await passenger.locator('[data-action="menu-toggle"]').waitFor({ timeout: 10000 });
    await passenger.evaluate(() => { location.hash = '#/bookings'; });
    await passenger.getByText('No bookings yet. Search for a compatible ride.').waitFor({ timeout: 10000 });
    await passenger.evaluate(() => { location.hash = '#/search-form'; });
    await passenger.locator('#search-form').waitFor();
    await setSearchPoint(passenger, 'origin');
    await setSearchPoint(passenger, 'destination');
    const start = new Date(depart.getTime() - 30 * 60 * 1000);
    const end = new Date(depart.getTime() + 8 * 60 * 60 * 1000);
    await passenger.locator('#search-form [name="window_start"]').fill(localDateTime(start));
    await passenger.locator('#search-form [name="window_end"]').fill(localDateTime(end));
    await ensureDetailsOpen(passenger, '#search-form .hf-baggage-details');
    await passenger.locator('#search-form [name="baggage_small_bags"]').fill('1');
    await passenger.locator('#search-form [name="baggage_large_suitcases"]').fill('1');
    const searchResponsePromise = passenger.waitForResponse(response => new URL(response.url()).pathname === '/api/search');
    await passenger.locator('#search-form .journey-submit').click();
    const searchResponse = await searchResponsePromise;
    const searchResult = await searchResponse.json();
    if (!searchResult.matches?.length) throw new Error(`search returned no matches: ${JSON.stringify(searchResult)}`);
    await passenger.locator('[data-fare-review]').first().waitFor({ timeout: 10000 });
    const matchCard = passenger.locator('.rj-match-card').first();
    await passenger.locator('[data-fare-review]').first().evaluate(el => { el.open = true; el.dispatchEvent(new Event('toggle')); });
    assert.match(await matchCard.innerText(), /₹/);
    assert.match(await matchCard.innerText(), /1 small bag/i);
    const requestButton = passenger.locator('[data-action="request-seat"]').first();
    await requestButton.waitFor();

    // A fresh search creates a distinct request identity. The duplicate trip
    // guard must return a useful, localized error while the first is pending.
    await requestButton.click();
    const passengerBooking = passenger.locator('.rj-booking-card').first();
    await passengerBooking.waitFor({ timeout: 10000 });
    assert.match(await passengerBooking.innerText(), /Awaiting driver|Waiting for the owner/i);

    // Start another search on the same trip so its request has a new identity.
    await passenger.evaluate(() => { location.hash = '#/search-form'; });
    await passenger.locator('#search-form').waitFor();
    await setSearchPoint(passenger, 'origin');
    await setSearchPoint(passenger, 'destination');
    await passenger.locator('#search-form [name="window_start"]').fill(localDateTime(start));
    await passenger.locator('#search-form [name="window_end"]').fill(localDateTime(end));
    await ensureDetailsOpen(passenger, '#search-form .hf-baggage-details');
    await passenger.locator('#search-form [name="baggage_small_bags"]').fill('1');
    await passenger.locator('#search-form [name="baggage_large_suitcases"]').fill('1');
    await passenger.locator('#search-form .journey-submit').click();
    await passenger.locator('[data-fare-review]').first().waitFor({ timeout: 10000 });
    await passenger.locator('[data-fare-review]').first().evaluate(el => { el.open = true; el.dispatchEvent(new Event('toggle')); });
    await passenger.locator('[data-action="request-seat"]').first().click();
    const duplicateMessage = passenger.getByRole('alert');
    await duplicateMessage.getByText('You already have a request for this ride. Open your bookings to review or cancel it.').waitFor({ timeout: 10000 });
    await passenger.locator('#language').selectOption('te');
    await duplicateMessage.getByText('ఈ రైడ్‌కు మీరు ఇప్పటికే అభ్యర్థన పంపారు. దాన్ని చూడటానికి లేదా రద్దు చేయడానికి మీ బుకింగ్‌లు తెరవండి.').waitFor();
    await passenger.locator('#language').selectOption('hi');
    await duplicateMessage.getByText('आपने इस सवारी के लिए पहले ही अनुरोध भेजा है। उसे देखने या रद्द करने के लिए अपनी बुकिंग खोलें।').waitFor();
    await passenger.locator('#language').selectOption('en');
    assert(api.some(item => item.path === '/api/request' && item.status === 409));
    await passenger.evaluate(() => { location.hash = '#/bookings'; });
    await passenger.locator('.rj-booking-card').first().waitFor({ timeout: 10000 });
    await passenger.reload();
    await passenger.locator('.rj-booking-card').first().waitFor({ timeout: 10000 });
    const bookingId = await passenger.locator('.rj-booking-card').first().getAttribute('data-booking-id');
    assert(bookingId);

    await driver.evaluate(() => { location.hash = '#/inbox'; });
    await driver.locator('.rj-booking-card').first().waitFor({ timeout: 10000 });
    const accept = driver.locator(`[data-action="accept"][data-id="${bookingId}"]`);
    await accept.click();
    await driver.evaluate(() => { location.hash = '#/bookings'; });
    const driverBookingSummary = driver.locator('.rj-booking-review > summary').first();
    await driverBookingSummary.waitFor({ timeout: 10000 });
    assert.match(await driverBookingSummary.innerText(), /accepted/i);
    await passenger.reload();
    const passengerBookingSummary = passenger.locator('.rj-booking-review > summary').first();
    await passengerBookingSummary.waitFor({ timeout: 10000 });
    assert.match(await passengerBookingSummary.innerText(), /accepted/i);
    await passengerBookingSummary.click();

    await passenger.locator(`[data-action="cancel-booking"][data-id="${bookingId}"]`).click();
    await passenger.waitForFunction(id => {
      const card = document.querySelector(`[data-booking-id="${id}"]`);
      return card && /Cancelled/.test(card.textContent);
    }, bookingId, { timeout: 10000 });
    await passenger.reload();
    await passenger.waitForFunction(id => {
      const card = document.querySelector(`[data-booking-id="${id}"]`);
      return card && /Cancelled/.test(card.textContent);
    }, bookingId, { timeout: 10000 });

    assert(api.some(item => item.path === '/api/publish' && item.status === 200));
    assert(api.some(item => item.path === '/api/search' && item.status === 200));
    assert(api.some(item => item.path === '/api/request' && item.status === 200));
    assert(api.some(item => item.path === '/api/accept' && item.status === 200));
    assert(api.some(item => item.path === '/api/cancel_booking' && item.status === 200));
    const provenCalls = api.filter(item => ['/api/preview', '/api/publish', '/api/search', '/api/request', '/api/accept', '/api/cancel_booking'].includes(item.path));
    console.log(`PASS iteration ${iteration}: synthetic driver published; passenger searched with quote+baggage, requested, driver accepted, passenger cancelled; reload retained terminal state`, JSON.stringify(provenCalls));
  } finally {
    await driverContext.close();
    await passengerContext.close();
    server.kill();
  }
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  try {
    // A cold, empty account is part of the normal path: both roles start with
    // no journeys or bookings in each newly created SQLite fixture.
    await runJourney(browser, 1);
    await runJourney(browser, 2);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
