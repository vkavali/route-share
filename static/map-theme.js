/**
 * Mount the boundary-correct vector basemap under existing Leaflet controls
 * and overlays. This never falls back to raster tiles: an unavailable basemap
 * leaves the Leaflet map and its manual controls usable over a neutral field.
 */
(function (root) {
  'use strict';

  const STYLE_URL = '/static/map-style.json';
  const MAPLIBRE_MODULE_URL = '/static/vendor/maplibre/maplibre-gl/dist/maplibre-gl.mjs';
  const MAPLIBRE_ADAPTER_URL = '/static/vendor/maplibre/maplibre-gl-leaflet/leaflet-maplibre-gl.js';
  const BOUNDARY_URL = '/static/maps/india-soi-boundaries.geojson';
  const BOUNDARY_ATTRIBUTION = 'Boundaries: <a href="https://nwdp.nwic.gov.in/hi/dataset/state-boundary" target="_blank" rel="noopener noreferrer">Survey of India · NWIC</a> · State and country labels in English';
  let mapLibreAdapterPromise = null;
  let boundaryPromise = null;
  const STYLE_TIMEOUT_MS = 15000;
  const BOUNDARY_NOTICE_MS = 15000;

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
    copy.layers = (copy.layers || []).filter(layer =>
      !['boundary_2', 'boundary_3', 'boundary_disputed', 'label_state', 'label_country_1', 'label_country_2', 'label_country_3'].includes(layer.id));
    for (const layer of copy.layers) {
      const textField = layer.layout?.['text-field'];
      // Preserve road shields and other non-name text while replacing only
      // the style's localized name expressions.
      if (layer.type === 'symbol' && hasNameField(textField)) layer.layout['text-field'] = field;
    }
    return copy;
  }

  function loadBoundaries() {
    if (boundaryPromise) return boundaryPromise;
    boundaryPromise = fetch(BOUNDARY_URL, { credentials: 'same-origin' })
      .then(response => {
        if (!response.ok) throw new Error(`Official boundary data unavailable (${response.status}).`);
        return response.json();
      })
      .then(data => {
        const validPosition = value => Array.isArray(value) && value.length >= 2 &&
          Number.isFinite(value[0]) && Number.isFinite(value[1]) &&
          value[0] >= -180 && value[0] <= 180 && value[1] >= -90 && value[1] <= 90;
        const validMultiPolygon = geometry => geometry?.type === 'MultiPolygon' &&
          Array.isArray(geometry.coordinates) && geometry.coordinates.length > 0 &&
          geometry.coordinates.every(polygon => Array.isArray(polygon) && polygon.length > 0 &&
            polygon.every(ring => Array.isArray(ring) && ring.length >= 4 && ring.every(validPosition) &&
              ring[0][0] === ring.at(-1)[0] && ring[0][1] === ring.at(-1)[1]));
        if (data?.type !== 'FeatureCollection' || !Array.isArray(data.features) || !data.features.length ||
            data.features.some(feature => feature?.type !== 'Feature' || !validMultiPolygon(feature.geometry) ||
              !['state', 'national'].includes(feature.properties?.kind) || typeof feature.properties?.name !== 'string')) {
          throw new Error('Official boundary data is invalid.');
        }
        const states = data.features.filter(feature => feature.properties.kind === 'state');
        const national = data.features.filter(feature => feature.properties.kind === 'national');
        const stateNames = new Set(states.map(feature => feature.properties.name));
        const stateCodes = new Set(states.map(feature => feature.properties.state_code));
        if (states.length !== 36 || national.length !== 1 || stateNames.size !== 36 ||
            national[0].properties.name !== 'India' || stateCodes.size !== 36 ||
            states.some(feature => typeof feature.properties.state_code !== 'string' || !feature.properties.state_code.trim()) ||
            [national[0], ...states].some(feature => !validPosition(feature.properties.label_point))) {
          throw new Error('Official boundary data is incomplete.');
        }
        return data;
      })
      .catch(error => { boundaryPromise = null; throw error; });
    return boundaryPromise;
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
    if (!L?.geoJSON || !L?.layerGroup || !map?.addLayer) {
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
    let mapLoaded = false;
    let boundariesLoaded = false;
    let basemapError = '';
    let boundaryError = '';
    let styleTimeout = null;
    let styleTimeoutStartedAt = 0;
    let styleTimeoutRemaining = STYLE_TIMEOUT_MS;
    let onMapLoad = null;
    let visibilityListener = null;
    let boundaryTimeout = null;
    let glMap = null;
    let officialBoundaries = null;
    let boundaryDataCache = null;
    const basemapDisposers = [];
    const boundaryDisposers = [];

    const clearStyleTimeout = () => {
      if (styleTimeout) clearTimeout(styleTimeout);
      styleTimeout = null;
    };

    const detachBasemapLayer = () => {
      for (const dispose of basemapDisposers.splice(0)) dispose();
      if (activeLayer && map.hasLayer(activeLayer)) map.removeLayer(activeLayer);
      activeLayer = null;
      glMap = null;
      mapLoaded = false;
    };
    const detachBoundaryLayer = () => {
      for (const dispose of boundaryDisposers.splice(0)) dispose();
      if (officialBoundaries && map.hasLayer(officialBoundaries)) map.removeLayer(officialBoundaries);
      officialBoundaries = null;
      map.attributionControl?.removeAttribution(BOUNDARY_ATTRIBUTION);
    };
    const cleanup = function () {
      if (stopped) return;
      stopped = true;
      clearStyleTimeout();
      if (boundaryTimeout) clearTimeout(boundaryTimeout);
      if (visibilityListener) root.document?.removeEventListener?.('visibilitychange', visibilityListener);
      visibilityListener = null;
      detachBasemapLayer();
      detachBoundaryLayer();
    };
    cleanup.ready = Promise.resolve();
    cleanup.boundariesReady = Promise.resolve();
    cleanup.getMode = () => stopped ? 'stopped'
      : basemapError ? boundariesLoaded ? 'boundary-only' : 'unavailable'
        : activeLayer === null ? 'unavailable'
          : boundariesLoaded ? 'vector' : boundaryError ? 'vector-boundary-unavailable' : 'vector-awaiting-boundaries';
    cleanup.getUnavailableReason = () => basemapError || boundaryError;
    cleanup.isBasemapLoaded = () => mapLoaded && !basemapError;
    cleanup.isBoundariesLoaded = () => boundariesLoaded;
    cleanup.getMap = () => glMap;

    const showUnavailable = reason => {
      if (stopped || basemapError) return;
      basemapError = String(reason || 'Map rendering is unavailable.');
      mapLoaded = false;
      clearStyleTimeout();
      if (visibilityListener) root.document?.removeEventListener?.('visibilitychange', visibilityListener);
      visibilityListener = null;
      detachBasemapLayer();
      try { options.onFallback?.(basemapError); } catch (_) { /* callback is optional */ }
    };

    const reportBoundaryUnavailable = reason => {
      if (stopped || boundariesLoaded || basemapError) return;
      boundaryError = String(reason || 'Official boundaries are unavailable.');
      try { (options.onBoundaryUnavailable || options.onFallback)?.(boundaryError); } catch (_) { /* callback is optional */ }
    };

    const scheduleStyleTimeout = () => {
      if (stopped || basemapError || mapLoaded || root.document?.visibilityState === 'hidden' || styleTimeout) return;
      styleTimeoutStartedAt = Date.now();
      styleTimeout = setTimeout(() => {
        styleTimeout = null;
        if (stopped || basemapError || mapLoaded) return;
        if (glMap?.loaded?.()) {
          onMapLoad?.();
          return;
        }
        showUnavailable('The vector map did not finish loading.');
      }, styleTimeoutRemaining);
    };
    const pauseStyleTimeout = () => {
      if (!styleTimeout) return;
      styleTimeoutRemaining = Math.max(0, styleTimeoutRemaining - (Date.now() - styleTimeoutStartedAt));
      clearStyleTimeout();
    };

    const mountBoundaries = boundaryData => {
      if (stopped || boundariesLoaded) return;
      const boundaryPane = map.getPane?.('official-boundaries') || map.createPane('official-boundaries');
      boundaryPane.style.zIndex = '350';
      boundaryPane.style.pointerEvents = 'none';
      officialBoundaries = L.layerGroup().addTo(map);
      L.geoJSON(boundaryData, {
        pane: 'official-boundaries',
        style: feature => ({
          color: feature.properties.kind === 'national' ? '#9D2F0A' : '#735A45',
          weight: feature.properties.kind === 'national' ? 3 : 1.5,
          opacity: 0.95,
          fill: false,
          interactive: false
        })
      }).addTo(officialBoundaries);
      const labels = [];
      for (const feature of boundaryData.features) {
        const point = feature.properties.label_point;
        if (!Array.isArray(point) || point.length !== 2 || !point.every(Number.isFinite)) continue;
        const label = document.createElement('span');
        label.textContent = feature.properties.name;
        label.lang = 'en';
        label.setAttribute('aria-hidden', 'true');
        label.style.cssText = 'display:block;color:#5B5147;font:600 11px/1.2 system-ui,sans-serif;white-space:nowrap;text-shadow:-1px -1px 0 #fff,1px -1px 0 #fff,-1px 1px 0 #fff,1px 1px 0 #fff,0 0 4px #fff';
        const marker = L.marker([point[1], point[0]], {
          pane: 'official-boundaries',
          interactive: false,
          keyboard: false,
          icon: L.divIcon({ className: 'india-state-label', html: label, iconSize: null })
        }).addTo(officialBoundaries);
        labels.push({ marker, kind: feature.properties.kind });
      }
      const updateLabelVisibility = () => {
        const zoom = map.getZoom?.() ?? 0;
        labels.forEach(({ marker, kind }) => {
          const visible = kind === 'national' ? zoom >= 3 && zoom < 5 : zoom >= 6 && zoom < 8;
          marker.setOpacity?.(visible ? 1 : 0);
        });
      };
      map.on?.('zoomend', updateLabelVisibility);
      boundaryDisposers.push(() => map.off?.('zoomend', updateLabelVisibility));
      updateLabelVisibility();
      map.attributionControl?.addAttribution(BOUNDARY_ATTRIBUTION);
      boundariesLoaded = true;
      boundaryError = '';
      if (boundaryTimeout) clearTimeout(boundaryTimeout);
      if (mapLoaded && !basemapError) {
        try { options.onReady?.(glMap); } catch (_) { /* callback is optional */ }
      }
    };

    cleanup.boundariesReady = loadBoundaries()
      .then(data => {
        boundaryDataCache = data;
        mountBoundaries(data);
      })
      .catch(error => reportBoundaryUnavailable(error?.message || 'Official boundaries are unavailable.'));

    if (typeof root.WebGLRenderingContext === 'undefined' || (root.maplibregl?.supported && !root.maplibregl.supported({ failIfMajorPerformanceCaveat: false }))) {
      showUnavailable('WebGL is unavailable in this browser.');
      return cleanup;
    }

    visibilityListener = () => {
      if (root.document?.visibilityState === 'hidden') {
        pauseStyleTimeout();
      } else if (glMap?.loaded?.()) {
        onMapLoad?.();
      } else {
        scheduleStyleTimeout();
      }
    };
    root.document?.addEventListener?.('visibilitychange', visibilityListener);
    scheduleStyleTimeout();
    boundaryTimeout = setTimeout(() => {
      if (!boundariesLoaded) reportBoundaryUnavailable('Official boundaries are taking too long to load.');
    }, BOUNDARY_NOTICE_MS);
    cleanup.ready = ensureMapLibre(L)
      .then(() => styleLoader(styleUrl))
      .then(style => {
        if (stopped || basemapError) return;
        const layer = L.maplibreGL({
          style: localizedStyle(style, lang),
          interactive: false,
          maxZoom: 19
        });
        activeLayer = layer;
        layer.addTo(map);
        glMap = layer.getMaplibreMap?.();
        if (!glMap) throw new Error('MapLibre did not initialize.');
        onMapLoad = () => {
          if (mapLoaded || stopped || basemapError) return;
          mapLoaded = true;
          clearStyleTimeout();
          if (boundariesLoaded) {
            try { options.onReady?.(glMap); } catch (_) { /* callback is optional */ }
          }
        };
        const onError = event => {
          const error = event?.error;
          const status = Number(error?.status || error?.statusCode);
          const message = String(error?.message || '');
          const failedMapResource = Boolean(event?.sourceId || event?.tile) || status === 0 || /ajax|fetch|network|tile|request|http/i.test(message);
          if (status === 401 || status === 403 || (failedMapResource && !mapLoaded) || /style|webgl|shader/i.test(message)) {
            showUnavailable(error?.message || 'Map style failed to load.');
          }
        };
        glMap.once('load', onMapLoad);
        glMap.on('error', onError);
        basemapDisposers.push(() => { glMap?.off('load', onMapLoad); glMap?.off('error', onError); });
        // A cached style can finish loading before this Leaflet adapter exposes
        // its MapLibre instance. Register first, then reconcile the current state
        // so the one-shot load event cannot be missed.
        if (glMap.loaded?.()) onMapLoad();
      })
      .catch(error => showUnavailable(error?.message || 'Vector map is unavailable.'));

    return cleanup;
  }

  root.RouteShareMapTheme = Object.freeze({ mountBasemap });
})(typeof window !== 'undefined' ? window : globalThis);
