/**
 * Mount the OpenFreeMap-derived vector basemap under the existing Leaflet
 * controls and overlays. Call the returned function to remove every layer and
 * listener owned here. No location data is requested or sent by this module.
 */
(function (root) {
  'use strict';

  const STYLE_URL = '/static/map-style.json';
  const MAPLIBRE_MODULE_URL = '/static/vendor/maplibre/maplibre-gl/dist/maplibre-gl.mjs';
  const MAPLIBRE_ADAPTER_URL = '/static/vendor/maplibre/maplibre-gl-leaflet/leaflet-maplibre-gl.js';
  let mapLibreAdapterPromise = null;
  const OSM_FALLBACK_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
  const STYLE_TIMEOUT_MS = 15000;
  const OSM_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>';

  function safeLanguage(value) {
    return ['en', 'te', 'hi'].includes(value) ? value : 'en';
  }

  function languageField(lang) {
    const explicit = lang === 'te' ? 'name:te' : lang === 'hi' ? 'name:hi' : 'name:en';
    return ['coalesce', ['get', explicit], ['get', 'name:nonlatin'], ['get', 'name:latin'], ['get', 'name']];
  }

  function hasNameField(expression) {
    if (!Array.isArray(expression)) return false;
    if (expression[0] === 'get' && typeof expression[1] === 'string' && /^name(?::|$)/.test(expression[1])) return true;
    return expression.some(hasNameField);
  }

  function localizedStyle(style, lang) {
    const copy = structuredClone(style);
    const field = languageField(lang);
    for (const layer of copy.layers || []) {
      const textField = layer.layout?.['text-field'];
      // Preserve road shields and other non-name text while replacing only
      // the style's localized name expressions.
      if (layer.type === 'symbol' && hasNameField(textField)) layer.layout['text-field'] = field;
    }
    return copy;
  }

  function ensureMapLibre(L) {
    if (L.maplibreGL && root.maplibregl?.Map) return Promise.resolve();
    if (mapLibreAdapterPromise) return mapLibreAdapterPromise;
    mapLibreAdapterPromise = import(MAPLIBRE_MODULE_URL)
      .then(module => {
        root.maplibregl = module;
        if (typeof module.setWorkerUrl === 'function') {
          const moduleUrl = new URL(MAPLIBRE_MODULE_URL, root.location.href);
          module.setWorkerUrl(new URL('./maplibre-gl-worker.mjs', moduleUrl).href);
        }
        if (L.maplibreGL) return;
        return new Promise((resolve, reject) => {
          const script = document.createElement('script');
          script.src = MAPLIBRE_ADAPTER_URL;
          script.async = true;
          script.onload = () => L.maplibreGL ? resolve() : reject(new Error('Leaflet map adapter did not initialize.'));
          script.onerror = () => reject(new Error('Leaflet map adapter could not be loaded.'));
          document.head.appendChild(script);
        });
      })
      .catch(error => { mapLibreAdapterPromise = null; throw error; });
    return mapLibreAdapterPromise;
  }

  function mountBasemap(L, map, options = {}) {
    if (!L?.tileLayer || !map?.addLayer) {
      throw new TypeError('Map theme needs Leaflet.');
    }

    const lang = safeLanguage(options.lang);
    const styleUrl = options.styleUrl || STYLE_URL;
    const styleLoader = options.loadStyle || (url => fetch(url, { credentials: 'same-origin' }).then(response => {
      if (!response.ok) throw new Error(`Map style could not be loaded (${response.status}).`);
      return response.json();
    }));
    let activeLayer = null;
    let stopped = false;
    let loaded = false;
    let timeout = null;
    let fallbackReason = '';
    let glMap = null;
    const disposers = [];

    const detachActiveLayer = () => {
      for (const dispose of disposers.splice(0)) dispose();
      if (activeLayer && map.hasLayer(activeLayer)) map.removeLayer(activeLayer);
      activeLayer = null;
      glMap = null;
    };
    const cleanup = function () {
      if (stopped) return;
      stopped = true;
      if (timeout) clearTimeout(timeout);
      detachActiveLayer();
    };
    cleanup.ready = Promise.resolve();
    cleanup.getMode = () => activeLayer === null ? 'stopped' : activeLayer._routeShareRasterFallback ? 'raster-fallback' : 'vector';
    cleanup.getFallbackReason = () => fallbackReason;
    cleanup.getMap = () => glMap;

    const showFallback = reason => {
      if (stopped || activeLayer?._routeShareRasterFallback) return;
      fallbackReason = String(reason || 'Map rendering is unavailable.');
      if (timeout) clearTimeout(timeout);
      detachActiveLayer();
      const fallback = L.tileLayer(OSM_FALLBACK_URL, {
        maxZoom: 19,
        attribution: OSM_ATTRIBUTION,
        className: 'route-share-raster-fallback'
      });
      fallback._routeShareRasterFallback = true;
      activeLayer = fallback.addTo(map);
      try { options.onFallback?.(fallbackReason); } catch (_) { /* callback is optional */ }
    };

    if (typeof root.WebGLRenderingContext === 'undefined' || (root.maplibregl?.supported && !root.maplibregl.supported({ failIfMajorPerformanceCaveat: false }))) {
      showFallback('WebGL is unavailable in this browser.');
      return cleanup;
    }

    timeout = setTimeout(() => {
      if (!loaded) showFallback('The vector map did not finish loading.');
    }, STYLE_TIMEOUT_MS);
    cleanup.ready = ensureMapLibre(L)
      .then(() => styleLoader(styleUrl))
      .then(style => {
        if (stopped) return;
        const layer = L.maplibreGL({
          style: localizedStyle(style, lang),
          interactive: false,
          maxZoom: 19
        });
        activeLayer = layer;
        layer.addTo(map);
        glMap = layer.getMaplibreMap?.();
        if (!glMap) throw new Error('MapLibre did not initialize.');
        const onLoad = () => {
          loaded = true;
          if (timeout) clearTimeout(timeout);
          try { options.onReady?.(glMap); } catch (_) { /* callback is optional */ }
        };
        const onError = event => {
          const error = event?.error;
          const status = Number(error?.status || error?.statusCode);
          if (!loaded && (status === 401 || status === 403 || status === 404 || /style|webgl|shader/i.test(String(error?.message || '')))) {
            showFallback(error?.message || 'Map style failed to load.');
          }
        };
        glMap.once('load', onLoad);
        glMap.on('error', onError);
        disposers.push(() => { glMap?.off('load', onLoad); glMap?.off('error', onError); });
      })
      .catch(error => showFallback(error?.message || 'Vector map is unavailable.'));

    return cleanup;
  }

  root.RouteShareMapTheme = Object.freeze({ mountBasemap });
})(typeof window !== 'undefined' ? window : globalThis);
