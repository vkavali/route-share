import { appIcon } from './icons.js';

const HYDERABAD = [17.385, 78.4867];
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const API_LOCALES = new Set(['en', 'te', 'hi']);

const EN = {
  mapPickTitle: 'Choose a meeting point',
  mapSearchLabel: 'Search for a place',
  mapSearch: 'Search',
  mapSearchHelp: 'Search for a landmark or place name, then choose a result.',
  mapMyLocation: 'Use my current location',
  mapUsePoint: 'Use this location',
  mapCancel: 'Cancel',
  mapClose: 'Close map picker',
  mapSearchEmpty: 'No places found. Try a nearby landmark or a different name.',
  mapSearchError: 'Place search failed. Check your connection and try again.',
  mapLocationDenied: 'Location access was denied. Allow it in your browser settings or choose a point on the map.',
  mapLocationUnavailable: 'Your current location is unavailable. Choose a point on the map or try again.',
  mapLocationTimeout: 'Could not get your location within 12 seconds. Try again or choose a point on the map.',
  mapLocationError: 'Could not get your location. Choose a point on the map or try again.',
  mapLocationBusy: 'Finding your location…',
  mapTilesError: 'Some map tiles could not be loaded. Search and map selection are still available.',
  mapPinnedLocation: 'Pinned map location',
  mapCurrentLocation: 'Current location',
  mapMeetingPointNote: 'Choose a clear, public meeting point such as a main entrance.',
  mapSearchLoading: 'Searching places…',
  mapSearchRequired: 'Enter a place name to search.',
  mapSearchResult: 'Search results',
  mapSelectedPoint: 'Selected location',
  mapAccuracy: 'Approximate location accuracy'
};

let nextPickerId = 1;
let pickerIsOpen = false;

function validPoint(value) {
  if (!value || value.lat === '' || value.lon === '') return false;
  const lat = Number(value.lat);
  const lon = Number(value.lon);
  return Number.isFinite(lat) && Number.isFinite(lon) && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;
}

function pointLabel(value, fallback) {
  return String(value?.label || value?.name || value?.display_name || fallback);
}

function translation(t, key) {
  const value = typeof t === 'function' ? t(key) : '';
  return value && value !== key ? value : EN[key] || key;
}

function placesFromResponse(response) {
  if (Array.isArray(response)) return response;
  if (Array.isArray(response?.places)) return response.places;
  if (Array.isArray(response?.results)) return response.results;
  if (Array.isArray(response?.data)) return response.data;
  return [];
}

/**
 * Opens an accessible, in-app location picker. Resolves to a selected
 * {lat, lon, label}, or null when the picker is dismissed.
 */
export function pickLocation({ title, initial, lang = 'en', t, api } = {}) {
  if (pickerIsOpen) return Promise.resolve(null);
  pickerIsOpen = true;
  return new Promise(resolve => {
    const id = nextPickerId++;
    const dialogId = `route-map-picker-${id}`;
    const titleId = `${dialogId}-title`;
    const searchLabelId = `${dialogId}-search-label`;
    const statusId = `${dialogId}-status`;
    const resultsId = `${dialogId}-results`;
    const previousFocus = document.activeElement;
    const oldOverflow = document.body.style.overflow;
    const token = `__route_map_picker_${id}`;
    const historyState = history.state && typeof history.state === 'object' ? history.state : {};

    const backdrop = document.createElement('div');
    backdrop.className = 'map-picker-backdrop';
    backdrop.innerHTML = `
      <section class="map-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="${titleId}" aria-describedby="${dialogId}-note" id="${dialogId}" tabindex="-1">
        <header class="map-picker-header">
          <h2 id="${titleId}"></h2>
          <button class="map-picker-close" type="button" data-map-close aria-label="${translation(t, 'mapClose')}">${appIcon('arrowLeft', { size: 22, className: 'ui-icon' })}</button>
        </header>
        <div class="map-picker-body">
          <div class="map-picker-tools">
            <label class="map-picker-search-label" id="${searchLabelId}" for="${dialogId}-query"></label>
            <div class="map-picker-search-row">
              <input id="${dialogId}-query" type="search" autocomplete="off" enterkeyhint="search" aria-describedby="${dialogId}-search-help">
              <button class="secondary map-picker-search-button" type="button" data-map-search></button>
              <button class="secondary map-picker-gps" type="button" data-map-gps></button>
            </div>
            <p class="map-picker-help" id="${dialogId}-search-help"></p>
            <p class="map-picker-note" id="${dialogId}-note"></p>
            <div class="map-picker-status" id="${statusId}" role="status" aria-live="polite" hidden></div>
            <div class="map-picker-results" id="${resultsId}" role="region" aria-label="${translation(t, 'mapSearchResult')}" hidden></div>
          </div>
          <div class="map-picker-map-wrap">
            <div class="map-picker-map" aria-label="${translation(t, 'mapPickTitle')}" role="application"></div>
            <div class="map-picker-map-error" role="status" hidden></div>
          </div>
        </div>
        <footer class="map-picker-footer">
          <p class="map-provider-notice"></p>
          <div class="map-picker-selected" aria-live="polite"></div>
          <div class="map-picker-actions">
            <button class="secondary" type="button" data-map-cancel></button>
            <button class="primary" type="button" data-map-confirm disabled></button>
          </div>
        </footer>
      </section>`;
    const dialog = backdrop.querySelector('.map-picker-dialog');
    const mapElement = backdrop.querySelector('.map-picker-map');
    const query = backdrop.querySelector('input[type="search"]');
    const status = backdrop.querySelector('.map-picker-status');
    const results = backdrop.querySelector('.map-picker-results');
    const gpsButton = backdrop.querySelector('[data-map-gps]');
    const searchButton = backdrop.querySelector('[data-map-search]');
    const confirmButton = backdrop.querySelector('[data-map-confirm]');
    const selectedText = backdrop.querySelector('.map-picker-selected');
    const mapError = backdrop.querySelector('.map-picker-map-error');
    const searchRow = backdrop.querySelector('.map-picker-search-row');
    searchRow.append(gpsButton);
    let map = null;
    let marker = null;
    let accuracyCircle = null;
    let selected = null;
    let finished = false;
    let busy = false;
    let searchSequence = 0;
    let tileFailed = false;

    dialog.querySelector('h2').textContent = title || translation(t, 'mapPickTitle');
    query.setAttribute('aria-label', translation(t, 'mapSearchLabel'));
    query.placeholder = translation(t, 'mapSearchLabel');
    dialog.querySelector('.map-picker-search-label').textContent = translation(t, 'mapSearchLabel');
    searchButton.setAttribute('aria-label', translation(t, 'mapSearch'));
    searchButton.innerHTML = `${appIcon('magnifyingGlass', { size: 22, className: 'ui-icon' })}<span class="sr-only">${translation(t, 'mapSearch')}</span>`;
    dialog.querySelector('.map-picker-help').textContent = translation(t, 'mapSearchHelp');
    const providerNotice = dialog.querySelector('.map-provider-notice');
    providerNotice.append(document.createTextNode(`${translation(t, 'mapProviderNotice')} `));
    const providerPolicy = document.createElement('a');
    providerPolicy.href = 'https://operations.osmfoundation.org/policies/nominatim/';
    providerPolicy.target = '_blank';
    providerPolicy.rel = 'noopener noreferrer';
    providerPolicy.textContent = translation(t, 'mapProviderPolicy');
    providerNotice.append(providerPolicy);
    gpsButton.setAttribute('aria-label', translation(t, 'mapMyLocation'));
    gpsButton.innerHTML = `${appIcon('crosshair', { size: 22, className: 'ui-icon' })}<span class="sr-only">${translation(t, 'mapMyLocation')}</span>`;
    dialog.querySelector('.map-picker-note').textContent = translation(t, 'mapMeetingPointNote');
    dialog.querySelector('[data-map-cancel]').textContent = translation(t, 'mapCancel');
    confirmButton.textContent = translation(t, 'mapUsePoint');
    const initialPoint = validPoint(initial) ? {
      lat: Number(initial.lat),
      lon: Number(initial.lon),
      label: pointLabel(initial, translation(t, 'mapPinnedLocation'))
    } : null;

    const showStatus = (message, kind = '') => {
      status.textContent = message || '';
      status.className = `map-picker-status${kind ? ` is-${kind}` : ''}`;
      status.hidden = !message;
    };
    const updateSelection = (point, source = 'map') => {
      if (!validPoint(point)) return;
      selected = {
        lat: Number(point.lat),
        lon: Number(point.lon),
        label: pointLabel(point, translation(t, source === 'gps' ? 'mapCurrentLocation' : 'mapPinnedLocation'))
      };
      if (map) {
        if (!marker) {
          marker = window.L.marker([selected.lat, selected.lon], {
            draggable: true,
            keyboard: true,
            icon: window.L.divIcon({
              className: 'route-picker-marker',
              html: '',
              iconSize: [20, 22],
              iconAnchor: [10, 21]
            })
          });
          marker.addTo(map);
          marker.on('dragend', () => {
            const at = marker.getLatLng();
            updateSelection({ lat: at.lat, lon: at.lng }, 'map');
          });
        } else marker.setLatLng([selected.lat, selected.lon]);
      }
      confirmButton.disabled = false;
      selectedText.textContent = `${translation(t, 'mapSelectedPoint')}: ${selected.label}`;
      if (source !== 'gps' && accuracyCircle && map) {
        map.removeLayer(accuracyCircle);
        accuracyCircle = null;
      }
    };
    const fitMobileMap = () => {
      if (!map) return;
      requestAnimationFrame(() => {
        if (!finished && map) map.invalidateSize({ pan: false });
      });
    };
    const cleanup = () => {
      if (map) {
        map.stop?.();
        map.off();
        map.remove();
        map = null;
      }
      backdrop.remove();
      pickerIsOpen = false;
      document.body.style.overflow = oldOverflow;
      window.removeEventListener('popstate', onPopState);
      document.removeEventListener('keydown', onKeyDown);
      if (previousFocus?.isConnected && typeof previousFocus.focus === 'function') previousFocus.focus();
    };
    const finish = (value, fromPopState = false) => {
      if (finished) return;
      finished = true;
      cleanup();
      resolve(value);
      if (!fromPopState && history.state?.[token]) history.back();
    };
    const onPopState = () => finish(null, true);
    const onKeyDown = event => {
      if (!backdrop.isConnected) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        finish(null);
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = [...dialog.querySelectorAll('button:not(:disabled),input:not(:disabled),a[href],select:not(:disabled),textarea:not(:disabled),[tabindex]:not([tabindex="-1"])')]
        .filter(el => !el.hidden && el.getAttribute('aria-hidden') !== 'true');
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
      } else if (event.shiftKey && document.activeElement === focusable[0]) {
        event.preventDefault();
        focusable.at(-1).focus();
      } else if (!event.shiftKey && document.activeElement === focusable.at(-1)) {
        event.preventDefault();
        focusable[0].focus();
      }
    };
    const setBusy = value => {
      busy = value;
      searchButton.disabled = value;
      gpsButton.disabled = value;
      query.setAttribute('aria-busy', String(value));
    };
    const renderResults = entries => {
      results.replaceChildren();
      results.hidden = false;
      if (!entries.length) {
        const empty = document.createElement('p');
        empty.className = 'map-picker-empty';
        empty.textContent = translation(t, 'mapSearchEmpty');
        results.append(empty);
        return;
      }
      for (const entry of entries) {
        const lat = Number(entry?.lat ?? entry?.latitude);
        const lon = Number(entry?.lon ?? entry?.lng ?? entry?.longitude);
        if (!validPoint({ lat, lon })) continue;
        const label = pointLabel(entry, '');
        if (!label.trim()) continue;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'map-picker-result';
        button.textContent = label;
        button.addEventListener('click', () => {
          updateSelection({ lat, lon, label }, 'search');
          map?.setView([lat, lon], Math.max(map.getZoom(), 15));
          showStatus('');
          fitMobileMap();
        });
        results.append(button);
      }
      if (!results.childElementCount) {
        const empty = document.createElement('p');
        empty.className = 'map-picker-empty';
        empty.textContent = translation(t, 'mapSearchEmpty');
        results.append(empty);
      }
    };
    const runSearch = async () => {
      const term = query.value.trim();
      if (!term) {
        showStatus(translation(t, 'mapSearchRequired'), 'error');
        query.focus();
        return;
      }
      if (typeof api !== 'function') {
        showStatus(translation(t, 'mapSearchError'), 'error');
        return;
      }
      const sequence = ++searchSequence;
      setBusy(true);
      results.hidden = true;
      results.replaceChildren();
      showStatus(translation(t, 'mapSearchLoading'));
      try {
        const url = `/api/places?q=${encodeURIComponent(term)}&lang=${encodeURIComponent(lang || 'en')}`;
        const response = await api(url);
        if (finished || sequence !== searchSequence) return;
        renderResults(placesFromResponse(response));
        showStatus('');
      } catch {
        if (finished || sequence !== searchSequence) return;
        showStatus(translation(t, 'mapSearchError'), 'error');
      } finally {
        if (!finished && sequence === searchSequence) setBusy(false);
      }
    };
    const gpsError = error => {
      if (finished) return;
      const key = error?.code === 1 ? 'mapLocationDenied'
        : error?.code === 2 ? 'mapLocationUnavailable'
        : error?.code === 3 ? 'mapLocationTimeout'
        : 'mapLocationError';
      showStatus(translation(t, key), 'error');
    };
    const findCurrentLocation = () => {
      if (busy) return;
      if (!navigator.geolocation) {
        showStatus(translation(t, 'mapLocationUnavailable'), 'error');
        return;
      }
      setBusy(true);
      showStatus(translation(t, 'mapLocationBusy'));
      navigator.geolocation.getCurrentPosition(position => {
        if (finished) return;
        const { latitude: lat, longitude: lon, accuracy } = position.coords;
        if (!validPoint({ lat, lon })) {
          setBusy(false);
          showStatus(translation(t, 'mapLocationError'), 'error');
          return;
        }
        updateSelection({ lat, lon, label: translation(t, 'mapCurrentLocation') }, 'gps');
        if (map) {
          if (accuracyCircle) map.removeLayer(accuracyCircle);
          accuracyCircle = window.L.circle([lat, lon], {
            radius: Math.max(accuracy || 0, 1),
            color: '#173d34',
            weight: 2,
            fillColor: '#d6ee7a',
            fillOpacity: .16
          }).addTo(map);
          map.setView([lat, lon], Math.max(map.getZoom(), 15));
          fitMobileMap();
        }
        setBusy(false);
        showStatus('');
      }, error => {
        if (finished) return;
        setBusy(false);
        gpsError(error);
      }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 });
    };

    backdrop.addEventListener('click', event => {
      if (event.target === backdrop) finish(null);
    });
    dialog.querySelector('[data-map-close]').addEventListener('click', () => finish(null));
    dialog.querySelector('[data-map-cancel]').addEventListener('click', () => finish(null));
    confirmButton.addEventListener('click', () => selected && finish(selected));
    searchButton.addEventListener('click', runSearch);
    query.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        runSearch();
      }
    });
    gpsButton.addEventListener('click', findCurrentLocation);

    document.body.append(backdrop);
    document.body.style.overflow = 'hidden';
    history.pushState({ ...historyState, [token]: true }, '', location.href);
    window.addEventListener('popstate', onPopState);
    document.addEventListener('keydown', onKeyDown);
    query.focus();
    if (initialPoint) updateSelection(initialPoint, 'initial');

    const Leaflet = window.L;
    if (!Leaflet?.map || !Leaflet?.tileLayer) {
      mapElement.textContent = '';
      mapError.textContent = translation(t, 'mapTilesError');
      mapError.hidden = false;
    } else {
      try {
        map = Leaflet.map(mapElement, {
          zoomControl: true,
          attributionControl: true,
          scrollWheelZoom: true,
          keyboard: true,
          tap: true,
          zoomAnimation: false,
          fadeAnimation: false,
          markerZoomAnimation: false
        }).setView(initialPoint ? [initialPoint.lat, initialPoint.lon] : HYDERABAD, initialPoint ? 15 : 12);
        const tiles = Leaflet.tileLayer(TILE_URL, {
          maxZoom: 19,
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
        }).addTo(map);
        tiles.on('tileerror', () => {
          if (tileFailed || finished) return;
          tileFailed = true;
          mapError.textContent = translation(t, 'mapTilesError');
          mapError.hidden = false;
        });
        map.on('click', event => updateSelection({
          lat: event.latlng.lat,
          lon: event.latlng.lng,
          label: translation(t, 'mapPinnedLocation')
        }, 'map'));
        fitMobileMap();
      } catch {
        map = null;
        mapError.textContent = translation(t, 'mapTilesError');
        mapError.hidden = false;
      }
    }
  });
}



/** Mount the localized vector basemap under factual journey markers and route geometry. */
export function mountJourneyMap(element, { points = [], route, lang = 'en', t } = {}) {
  if (!element) return () => {};
  const L = window.L;
  const fallback = translation(t, 'mapTilesError');
  const shell = element.closest('.journey-map-shell') || element.parentElement;
  let status = shell?.querySelector('.journey-map-status');
  if (!status && shell) {
    status = document.createElement('p');
    status.className = 'journey-map-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    status.hidden = true;
    shell.append(status);
  }
  const showStatus = message => {
    if (!status) return;
    status.textContent = message || '';
    status.hidden = !message;
  };
  if (!L?.map || !L?.tileLayer) {
    showStatus(fallback);
    return () => {};
  }

  let map;
  try {
    const isHomeMap = Boolean(element.closest('.home-map-shell'));
    map = L.map(element, {
      zoomControl: true,
      attributionControl: true,
      scrollWheelZoom: true,
      keyboard: true,
      zoomAnimation: false,
      fadeAnimation: false,
      markerZoomAnimation: false
    });
    const tiles = L.tileLayer(TILE_URL, {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors'
    }).addTo(map);
    let tileFailed = false;
    tiles.on('tileerror', () => {
      if (tileFailed) return;
      tileFailed = true;
      showStatus(fallback);
    });

    const visiblePoints = points.filter(validPoint).map((point, index) => ({
      lat: Number(point.lat),
      lon: Number(point.lon),
      label: pointLabel(point, ''),
      kind: point.kind || point.type || (index === 0 ? 'pickup' : 'dropoff')
    }));
    const bounds = [];
    visiblePoints.forEach(point => {
      const isPickup = /origin|pickup|start/i.test(point.kind);
      L.circleMarker([point.lat, point.lon], {
        radius: 8,
        color: '#ffffff',
        weight: 3,
        fillColor: isPickup ? '#173d34' : '#d6ee7a',
        fillOpacity: 1,
        className: isPickup ? 'journey-map-marker journey-map-marker-pickup' : 'journey-map-marker journey-map-marker-dropoff'
      }).addTo(map);
      bounds.push([point.lat, point.lon]);
    });

    const coordinates = Array.isArray(route?.coordinates) ? route.coordinates : [];
    const line = coordinates.filter(pair => Array.isArray(pair) && pair.length >= 2)
      .map(pair => ({ lat: Number(pair[1]), lon: Number(pair[0]) }))
      .filter(validPoint);
    if (line.length >= 2) {
      const routeLine = L.polyline(line.map(point => [point.lat, point.lon]), {
        color: '#173d34',
        weight: 5,
        opacity: .94,
        lineCap: 'round',
        lineJoin: 'round',
        className: 'journey-map-route'
      }).addTo(map);
      bounds.push(...routeLine.getLatLngs().map(point => [point.lat, point.lng]));
    }

    if (bounds.length > 1) map.fitBounds(bounds, { padding: [36, 36], maxZoom: 15 });
    else if (bounds.length === 1) map.setView(bounds[0], 15);
    else map.setView([17.1, 80], 7);

    requestAnimationFrame(() => map?.invalidateSize({ pan: false }));
    return () => {
      map?.stop?.();
      map?.off();
      map?.remove();
      map = null;
    };
  } catch {
    map?.remove();
    showStatus(fallback);
    return () => {};
  }
}
