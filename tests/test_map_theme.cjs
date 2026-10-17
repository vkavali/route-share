/* Isolated basemap contract; synthetic geometry only, no external providers. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const zlib = require('node:zlib');

const source = fs.readFileSync(path.join(__dirname, '..', 'static', 'map-theme.js'), 'utf8');
const publishedStyle = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'static', 'map-style.json'), 'utf8'));
assert(!publishedStyle.layers.some(layer => ['boundary_2', 'boundary_3', 'boundary_disputed', 'label_state', 'label_country_1', 'label_country_2', 'label_country_3'].includes(layer.id)));
const boundaryAssetBytes = fs.readFileSync(path.join(__dirname, '..', 'static', 'maps', 'india-soi-boundaries.geojson'));
const compressedBoundaryBytes = fs.readFileSync(path.join(__dirname, '..', 'static', 'maps', 'india-soi-boundaries.geojson.gz'));
assert.deepEqual(zlib.gunzipSync(compressedBoundaryBytes), boundaryAssetBytes, 'compressed boundary asset must match GeoJSON');

function createHarness({ boundaryResponse, initiallyLoaded = false, visibilityState = 'visible', webglSupported = true } = {}) {
  const requested = [];
  const attributions = new Set();
  const layers = new Set();
  const glHandlers = {};
  const visibilityHandlers = new Set();
  const scheduledDelays = [];
  const timeoutCallbacks = [];
  const loadState = { value: initiallyLoaded };
  let capturedStyle;
  let rasterCalls = 0;
  const gl = {
    once(name, callback) { glHandlers[name] = callback; },
    on(name, callback) { glHandlers[name] = callback; },
    off() {},
    loaded() { return loadState.value; },
  };
  const layer = {
    addTo(map) { map.addLayer(this); return this; },
    getMaplibreMap() { return gl; },
  };
  const L = {
    maplibreGL(options) { capturedStyle = options.style; return layer; },
    geoJSON(data, options) { return { addTo(group) { group.children.push({ data, options }); return this; } }; },
    layerGroup() { return { children: [], addTo(map) { map.addLayer(this); return this; } }; },
    marker() { return { addTo(group) { group.children.push(this); return this; }, setOpacity() {} }; },
    divIcon(options) { return options; },
    tileLayer() { rasterCalls += 1; throw new Error('Raster fallback must never be used'); },
  };
  const map = {
    attributionControl: {
      addAttribution(value) { attributions.add(value); },
      removeAttribution(value) { attributions.delete(value); },
    },
    addLayer(value) { layers.add(value); },
    createPane() { return { style: {} }; },
    getPane() { return null; },
    getZoom() { return 5; },
    on() {},
    off() {},
    hasLayer(value) { return layers.has(value); },
    removeLayer(value) { layers.delete(value); },
  };
  const document = {
    visibilityState,
    createElement: () => ({ style: {}, textContent: '', setAttribute() {} }),
    addEventListener(name, handler) { if (name === 'visibilitychange') visibilityHandlers.add(handler); },
    removeEventListener(name, handler) { if (name === 'visibilitychange') visibilityHandlers.delete(handler); },
    dispatchVisibility() { visibilityHandlers.forEach(handler => handler()); },
  };
  const window = {
    L,
    document,
    maplibregl: { Map: function Map() {}, supported: () => webglSupported },
    WebGLRenderingContext: function WebGLRenderingContext() {},
    location: { href: 'http://localhost/' },
  };
  const context = {
    window,
    globalThis: window,
    structuredClone,
    URL,
    document,
    setTimeout: (handler, delay) => { scheduledDelays.push(delay); timeoutCallbacks.push({ handler, delay }); return timeoutCallbacks.length; },
    clearTimeout: () => {},
    fetch: async url => {
      requested.push(url);
      if (url === '/static/maps/india-soi-boundaries.geojson') {
        return typeof boundaryResponse === 'function' ? boundaryResponse() : boundaryResponse;
      }
      throw new Error(`Unexpected request: ${url}`);
    },
  };
  vm.runInNewContext(source, context);
  return { theme: window.RouteShareMapTheme, L, map, glHandlers, requested, layers, attributions, document, visibilityHandlers, scheduledDelays, timeoutCallbacks, loadState,
    getStyle: () => capturedStyle, getRasterCalls: () => rasterCalls };
}

(async () => {
  const syntheticGeometryFixture = {
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', properties: { kind: 'national', name: 'India', label_point: [0, 0] }, geometry: { type: 'MultiPolygon', coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] } },
      ...Array.from({ length: 36 }, (_, index) => ({
        type: 'Feature', properties: { kind: 'state', name: `Test state ${index}`, state_code: `T${index}`, label_point: [0, 0] },
        geometry: { type: 'MultiPolygon', coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 0]]]] },
      })),
    ],
  };
  const harness = createHarness({ boundaryResponse: { ok: true, json: async () => syntheticGeometryFixture } });
  let unavailable = '';
  const cleanup = harness.theme.mountBasemap(harness.L, harness.map, {
    lang: 'en',
    loadStyle: async () => ({ version: 8, sources: {}, layers: [
      { id: 'boundary_2', type: 'line' }, { id: 'boundary_disputed', type: 'line' },
      { id: 'label_state', type: 'symbol' }, { id: 'label_country_1', type: 'symbol' },
    ] }),
    onFallback: reason => { unavailable = reason; },
  });
  await cleanup.ready;
  await cleanup.boundariesReady;
  assert.equal(cleanup.getMode(), 'vector');
  assert.deepEqual(harness.getStyle().layers.map(layer => layer.id), []);
  assert([...harness.attributions].some(value => value.includes('Survey of India · NWIC')));
  assert.equal(unavailable, '');
  assert.equal(harness.getRasterCalls(), 0);
  assert.deepEqual(harness.requested, ['/static/maps/india-soi-boundaries.geojson']);
  harness.glHandlers.load();
  harness.glHandlers.error({ error: { status: 403, message: 'Synthetic vector tile denied' } });
  assert.equal(cleanup.getMode(), 'boundary-only');
  assert.equal(unavailable, 'Synthetic vector tile denied');
  assert.equal(harness.layers.size, 1, 'official boundaries remain visible when the street basemap fails');
  assert.equal(harness.attributions.size, 1);
  cleanup();
  assert.equal(cleanup.getMode(), 'stopped');
  assert.equal(harness.layers.size, 0);
  assert.equal(harness.attributions.size, 0);

  const tileFailure = createHarness({ boundaryResponse: { ok: true, json: async () => syntheticGeometryFixture } });
  const tileFailureCleanup = tileFailure.theme.mountBasemap(tileFailure.L, tileFailure.map, {
    loadStyle: async () => ({ version: 8, sources: {}, layers: [] }),
  });
  await tileFailureCleanup.ready;
  await tileFailureCleanup.boundariesReady;
  tileFailure.glHandlers.error({ sourceId: 'openmaptiles', error: { message: 'AJAXError: Failed to fetch' } });
  assert.equal(tileFailureCleanup.getMode(), 'boundary-only', 'network tile failure must preserve local official outlines');
  assert.equal(tileFailureCleanup.isBoundariesLoaded(), true);
  assert.equal(tileFailure.layers.size, 1);
  tileFailureCleanup();
  assert.equal(tileFailure.layers.size, 0);

  const loadedTileFailure = createHarness({ boundaryResponse: { ok: true, json: async () => syntheticGeometryFixture } });
  let loadedFallbacks = 0;
  const loadedFailureCleanup = loadedTileFailure.theme.mountBasemap(loadedTileFailure.L, loadedTileFailure.map, {
    loadStyle: async () => ({ version: 8, sources: {}, layers: [] }),
    onFallback: () => { loadedFallbacks += 1; },
  });
  await loadedFailureCleanup.ready;
  await loadedFailureCleanup.boundariesReady;
  loadedTileFailure.glHandlers.load();
  loadedTileFailure.glHandlers.error({ sourceId: 'openmaptiles', error: { message: 'AJAXError: Failed to fetch' } });
  assert.equal(loadedFailureCleanup.getMode(), 'vector', 'late tile failures must not tear down a loaded street map');
  assert.equal(loadedTileFailure.layers.size, 2);
  assert.equal(loadedFallbacks, 0);
  loadedFailureCleanup();

  const cached = createHarness({ initiallyLoaded: true, boundaryResponse: { ok: true, json: async () => syntheticGeometryFixture } });
  let readyAfterCachedLoad = 0;
  const cachedCleanup = cached.theme.mountBasemap(cached.L, cached.map, {
    loadStyle: async () => ({ version: 8, sources: {}, layers: [] }),
    onReady: () => { readyAfterCachedLoad += 1; },
  });
  await cachedCleanup.ready;
  await cachedCleanup.boundariesReady;
  assert.equal(cachedCleanup.isBasemapLoaded(), true);
  assert.equal(readyAfterCachedLoad, 1);
  cached.glHandlers.load();
  assert.equal(readyAfterCachedLoad, 1, 'cached readiness and the later load event must not double-notify');
  cachedCleanup();

  const timedLoad = createHarness({ boundaryResponse: { ok: true, json: async () => syntheticGeometryFixture } });
  let timedLoadFallbacks = 0;
  const timedCleanup = timedLoad.theme.mountBasemap(timedLoad.L, timedLoad.map, {
    loadStyle: async () => ({ version: 8, sources: {}, layers: [] }),
    onFallback: () => { timedLoadFallbacks += 1; },
  });
  await timedCleanup.ready;
  await timedCleanup.boundariesReady;
  timedLoad.loadState.value = true;
  timedLoad.timeoutCallbacks.find(timer => timer.delay === 15000).handler();
  assert.equal(timedCleanup.isBasemapLoaded(), true, 'timeout must reconcile a loaded MapLibre map before failing');
  assert.equal(timedLoadFallbacks, 0);
  timedCleanup();

  const background = createHarness({ visibilityState: 'hidden', boundaryResponse: { ok: true, json: async () => syntheticGeometryFixture } });
  const backgroundCleanup = background.theme.mountBasemap(background.L, background.map, {
    loadStyle: async () => ({ version: 8, sources: {}, layers: [] }),
  });
  await backgroundCleanup.ready;
  assert.equal(background.scheduledDelays.filter(delay => delay === 15000).length, 1, 'only the independent boundary notice may run while hidden');
  background.document.visibilityState = 'visible';
  background.document.dispatchVisibility();
  assert.equal(background.scheduledDelays.filter(delay => delay === 15000).length, 2, 'the style failure timeout resumes when visible');
  backgroundCleanup();
  assert.equal(background.visibilityHandlers.size, 0);

  const officialAsset = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'static', 'maps', 'india-soi-boundaries.geojson'), 'utf8'));
  const official = createHarness({ boundaryResponse: { ok: true, json: async () => officialAsset } });
  const officialCleanup = official.theme.mountBasemap(official.L, official.map, {
    loadStyle: async () => ({ version: 8, sources: {}, layers: [] }),
  });
  await officialCleanup.ready;
  await officialCleanup.boundariesReady;
  assert.equal(officialCleanup.getMode(), 'vector');
  assert.equal(officialAsset.features.filter(feature => feature.properties.kind === 'state').length, 36);
  assert.equal(officialAsset.features.filter(feature => feature.properties.kind === 'national').length, 1);
  officialCleanup();

  const noWebgl = createHarness({ webglSupported: false, boundaryResponse: { ok: true, json: async () => syntheticGeometryFixture } });
  const noWebglCleanup = noWebgl.theme.mountBasemap(noWebgl.L, noWebgl.map, {});
  await noWebglCleanup.boundariesReady;
  assert.equal(noWebglCleanup.getMode(), 'boundary-only');
  assert.equal(noWebgl.layers.size, 1, 'official boundaries still mount when WebGL is unavailable');
  assert.equal(noWebgl.attributions.size, 1);
  noWebglCleanup();
  assert.equal(noWebgl.layers.size, 0);

  let fetches = 0;
  let boundaryFailures = 0;
  const missing = createHarness({ boundaryResponse: { ok: false, status: 404, json: async () => null } });
  const failedCleanup = missing.theme.mountBasemap(missing.L, missing.map, {
    loadStyle: async () => ({ version: 8, sources: {}, layers: [] }),
    onFallback: () => { fetches += 1; },
    onBoundaryUnavailable: () => { boundaryFailures += 1; },
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(fetches, 0);
  assert.equal(boundaryFailures, 1);
  assert.equal(missing.layers.size, 1);
  assert.equal(failedCleanup.getMode(), 'vector-boundary-unavailable');
  assert.equal(missing.getRasterCalls(), 0);
  failedCleanup();

  let attempts = 0;
  const retry = createHarness({ boundaryResponse: () => {
    attempts += 1;
    return attempts === 1
      ? { ok: false, status: 503 }
      : { ok: true, json: async () => syntheticGeometryFixture };
  } });
  const firstAttempt = retry.theme.mountBasemap(retry.L, retry.map, { loadStyle: async () => ({ version: 8, sources: {}, layers: [] }) });
  await firstAttempt.ready;
  await firstAttempt.boundariesReady;
  assert.equal(firstAttempt.getMode(), 'vector-boundary-unavailable');
  firstAttempt();
  const secondAttempt = retry.theme.mountBasemap(retry.L, retry.map, { loadStyle: async () => ({ version: 8, sources: {}, layers: [] }) });
  await secondAttempt.ready;
  await secondAttempt.boundariesReady;
  assert.equal(attempts, 2);
  assert.equal(secondAttempt.getMode(), 'vector');
  secondAttempt();

  let releaseLate;
  const lateResponse = new Promise(resolve => { releaseLate = resolve; });
  const late = createHarness({ boundaryResponse: () => lateResponse });
  const lateCleanup = late.theme.mountBasemap(late.L, late.map, { loadStyle: async () => ({ version: 8, sources: {}, layers: [] }) });
  await lateCleanup.ready;
  lateCleanup();
  releaseLate({ ok: true, json: async () => syntheticGeometryFixture });
  await lateCleanup.boundariesReady;
  assert.equal(late.layers.size, 0);
  assert.equal(late.attributions.size, 0);
  console.log('PASS: official boundary overlay is required, conflicting vector boundaries are removed, teardown is complete, and failure has no raster fallback');
})().catch(error => { console.error(error); process.exitCode = 1; });
