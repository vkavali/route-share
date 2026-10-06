// @ts-nocheck
/**
 * Reference-led renderers for the saved route-sharing data views.
 *
 * The module is deliberately framework-free so the app shell can keep owning
 * navigation, polling, and mutations. `makeJourneyViews` receives those
 * existing helpers and returns drop-in page renderers.
 */
/** @param {any} context @returns {Record<string, Function>} */
export function makeJourneyViews(context) {
  const {
    state, t, icon, esc, escAttr, fmtTime, inr, minText, labelOf,
    statusName, routeSvg, routeAttribution, roadNote, localizedContribution,
    vehicleText, checks, locale,
  } = context;

  const tripFor = (id) => (state.data.trips || []).find((trip) => trip.id === id);
  const requestFor = (booking) => (state.data.requests || []).find((request) => request.id === booking.request_id);
  const matchFor = (booking) => booking.match || {};
  const routeForTrip = (trip) => trip?.current_route || trip?.route || null;
  const routeForBooking = (booking) => {
    const match = matchFor(booking);
    return booking.route || booking.trip_route || match.route || routeForTrip(tripFor(booking.trip_id));
  };
  const number = (value, digits = 1) => value == null || !Number.isFinite(Number(value))
    ? t('unknown')
    : new Intl.NumberFormat(locale(), { maximumFractionDigits: digits }).format(Number(value));
  const km = (metres) => metres == null ? t('unknown') : `${number(Number(metres) / 1000)} ${t('km')}`;
  const routeBounds = (route) => route?.coordinates?.length ? route : null;
  const pointLabel = (point) => point ? labelOf(point) : t('unknown');
  /** @param {{route:any,tripId:any,points?:any[],label:string,compact?:boolean}} options */
  const mapPanel = ({ route, tripId, points = [], label, compact = false }) => {
    const actualRoute = routeBounds(route);
    const routeJson = actualRoute ? escAttr(JSON.stringify(actualRoute.coordinates)) : '';
    const pointJson = points.length ? escAttr(JSON.stringify(points.filter(Boolean).map((point) => ({ lat: point.lat, lon: point.lon, label: point.label || '' })))) : '';
    return `<div class="rj-map-frame${compact ? ' rj-map-frame--compact' : ''}" aria-label="${escAttr(label)}">
      <div class="journey-map rj-map" data-journey-route-map data-route-trip-id="${escAttr(tripId || '')}"${routeJson ? ` data-route-coordinates="${routeJson}"` : ''}${pointJson ? ` data-route-points="${pointJson}"` : ''} aria-label="${escAttr(label)}"></div>
      ${actualRoute ? `<div class="rj-map-attribution">${routeAttribution()}</div>` : ''}
    </div>`;
  };
  const pointsSummary = (from, to, extra = '') => `<div class="rj-route-line">
    <div class="rj-stop rj-stop--start"><span class="rj-stop-icon" aria-hidden="true">${icon('pin', 20)}</span><div><small>${t('origin')}</small><strong>${esc(pointLabel(from))}</strong></div></div>
    <div class="rj-stop-rule" aria-hidden="true"></div>
    <div class="rj-stop rj-stop--end"><span class="rj-stop-icon" aria-hidden="true">${icon('pin', 20)}</span><div><small>${t('destination')}</small><strong>${esc(pointLabel(to))}</strong></div></div>
    ${extra}
  </div>`;
  const dateLine = (v) => v ? fmtTime(v) : t('unknown');
  const matchRoute = (match) => routeForTrip(tripFor(match.trip_id)) || match.route || null;
  const segmentMeters = (record) => {
    const start = Number(record?.start_m);
    const end = Number(record?.end_m);
    return Number.isFinite(start) && Number.isFinite(end) && end > start ? end - start : null;
  };
  const publicPerson = (person, segmentM = null) => {
    if (!person) return '';
    const count = Number(person.rating_count) || 0;
    const average = Number(person.rating_average);
    const rating = count > 0 && Number.isFinite(average)
      ? number(average, 2)
      : t('communityNoRatings');
    const verified = !person.development && person.verification?.identity === 'verified';
    const distance = segmentM != null
      ? `<div><small>${t('sharedSegmentEstimate')}</small><strong>${km(segmentM)}</strong></div>`
      : '';
    return `<div class="rj-person"><div><small>${person.development ? t('communityDevelopment') : t('communityAccountSummary')}</small><strong>${esc(person.name || t('unknown'))}</strong><small>${t(verified ? 'communityIdentityVerified' : 'communityNotVerified')}</small></div><div><small>${t('communityRatingSummary')}${count ? ` · ${number(count, 0)}` : ''}</small><strong>${esc(rating)}</strong></div><div><small>${t('communityCompletedTrips')}</small><strong>${number(person.completed_trip_count || 0, 0)}</strong></div>${distance}</div>`;
  };

  // Sorting only reorders the rendered real matches; the server's recommended
  // order remains the default and no match is added or removed locally.
  if (typeof document !== 'undefined' && state && !state.__rjSortBound) {
    state.__rjSortBound = true;
    document.addEventListener('change', (event) => {
      const select = event.target?.closest?.('[data-rj-sort]');
      if (!select) return;
      const list = select.closest('.rj-sheet')?.querySelector('.rj-card-list');
      if (!list) return;
      const cards = [...list.querySelectorAll('.rj-match-card')];
      cards.forEach((card,index)=>{if(card.dataset.rjOriginalOrder==null)card.dataset.rjOriginalOrder=String(index)});
      const numeric = (card, key) => {
        const value = Number(card.dataset[key]);
        return Number.isFinite(value) && card.dataset[key] !== '' ? value : null;
      };
      const order = select.value;
      cards.sort((a, b) => {
        if (order === 'soonest') return (numeric(a, 'rjPickup') ?? Infinity) - (numeric(b, 'rjPickup') ?? Infinity);
        if (order === 'least-driving') return (numeric(a, 'rjDetour') ?? Infinity) - (numeric(b, 'rjDetour') ?? Infinity);
        if (order === 'best-rated') {
          const ar = numeric(a, 'rjRating'); const br = numeric(b, 'rjRating');
          if (ar == null || br == null) return ar == null ? (br == null ? 0 : 1) : -1;
          return br - ar || (numeric(b, 'rjRatingCount') ?? 0) - (numeric(a, 'rjRatingCount') ?? 0);
        }
        return Number(a.dataset.rjOriginalOrder)-Number(b.dataset.rjOriginalOrder);
      });
      for (const card of cards) list.append(card);
    });
  }

  function matchCard(match) {
    const trip = tripFor(match.trip_id);
    const route = matchRoute(match);
    const fullRouteKm = route?.distance_m ? km(route.distance_m) : '';
    const total = match.total_driver_detour_minutes;
    const maximum = trip?.max_detour_minutes;
    const driverSummary = match.driver_summary;
    const pickupTimestamp = Date.parse(match.pickup_at || '');
    const ratingAverage = Number(driverSummary?.rating_average);
    const ratingCount = Number(driverSummary?.rating_count) || 0;
    const sortPickup = Number.isFinite(pickupTimestamp) ? pickupTimestamp : '';
    const sortRating = ratingCount > 0 && Number.isFinite(ratingAverage) ? ratingAverage : '';
    return `<article class="rj-card rj-match-card" data-rj-pickup="${sortPickup}" data-rj-detour="${Number.isFinite(Number(match.incremental_detour_minutes)) ? Number(match.incremental_detour_minutes) : ''}" data-rj-rating="${sortRating}" data-rj-rating-count="${ratingCount}">
      <div class="rj-card-topline"><span class="rj-chip rj-chip--quiet">${t('noPayment')}</span><span class="rj-chip rj-chip--accent">${number(match.available_seats, 0)} ${t('available')}</span></div>
      <div class="rj-match-route">
        ${pointsSummary(match.pickup, match.dropoff)}
      </div>
      <div class="rj-match-facts">
        <div><small>${t('pickup')}</small><strong>${dateLine(match.pickup_at)}</strong></div>
        <div><small>${t('dropoff')}</small><strong>${dateLine(match.dropoff_at)}</strong></div>
        <div><small>${t('pickupDetour')}</small><strong>${minText(match.pickup_detour_minutes)}</strong></div>
        <div><small>${t('dropoffDetour')}</small><strong>${minText(match.dropoff_detour_minutes)}</strong></div>
        <div><small>${t('incrementalDetour')}</small><strong>${minText(match.incremental_detour_minutes)}</strong></div>
        <div><small>${t('totalDetour')}</small><strong>${minText(total)}</strong>${maximum != null ? `<small>${t('detourBudget')}: ${number(maximum, 0)} ${t('minutes')}</small>` : ''}</div>
        <div><small>${t('distance')}</small><strong>${fullRouteKm || t('unknown')}</strong></div>
      </div>
      <p class="rj-estimate-note">${t('detourEstimate')}</p>
      ${roadNote('roadPickup', match.routed_pickup, match.pickup_snap_m)}
      ${roadNote('roadDropoff', match.routed_dropoff, match.dropoff_snap_m)}
      <div class="rj-person"><div><small>${t('vehicle')}</small><strong>${esc(vehicleText(match.vehicle))}</strong></div></div>
      ${publicPerson(driverSummary, segmentMeters(match))}
      <details class="rj-checks"><summary>${t('checks')}</summary>${checks(match.verification)}</details>
      ${route || (match.start_m != null && match.end_m != null) ? `<div class="rj-segment-note">${route ? routeSvg(route) : ''}${match.start_m != null && match.end_m != null ? `<span>${km(match.start_m)} – ${km(match.end_m)} ${t('exampleKm')}</span>` : ''}</div>` : ''}
      <button class="primary rj-primary" type="button" data-action="request-seat" data-id="${escAttr(match.id)}" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('requestSeat')} ${icon('arrowRight', 20)}</button>
    </article>`;
  }

  function resultsPage() {
    const results = state.results;
    if (!results) return `<section class="rj-page"><div class="rj-empty"><h1>${t('searchTitle')}</h1><p>${t('noMatches')}</p><a class="primary" href="#/search-form">${t('ride')}</a></div></section>`;
    /** @type {any[]} */
    const matches = results.matches || [];
    const request = results.request || {};
    const first = matches[0];
    const firstRoute = first ? matchRoute(first) : null;
    const firstTripId = first?.trip_id || '';
    const summary = `<div class="rj-search-summary">
        <div><small>${t('origin')}</small><strong>${esc(pointLabel(request.origin))}</strong></div><span aria-hidden="true">${icon('arrowRight', 19)}</span>
      <div><small>${t('destination')}</small><strong>${esc(pointLabel(request.destination))}</strong></div>
      <div class="rj-search-time"><small>${t('date')}</small><strong>${dateLine(request.window_start)}</strong>${request.window_end ? `<small>${t('pickupUntil')}: ${dateLine(request.window_end)}</small>` : ''}${request.seats != null ? `<small>${t('seatsNeeded')}: ${number(request.seats, 0)}</small>` : ''}</div>
    </div>`;
    return `<section class="rj-page rj-results-page">
      ${mapPanel({ route: firstRoute, tripId: firstTripId, points: first ? [first.routed_pickup || first.pickup, first.routed_dropoff || first.dropoff] : [], label: t('routeAria') })}
      <section class="rj-sheet">
        <div class="rj-sheet-handle" aria-hidden="true"></div>
        <header class="rj-page-heading"><div><h1>${new Intl.NumberFormat(locale()).format(matches.length)} ${t('matches')}</h1></div><div><select class="rj-edit-link" data-rj-sort aria-label="${escAttr(t('sortResults'))}"><option value="recommended">${t('sortRecommended')}</option><option value="soonest">${t('sortSoonest')}</option><option value="least-driving">${t('sortLeastDriving')}</option><option value="best-rated">${t('sortBestRated')}</option></select> <a class="rj-edit-link" href="#/search-form">${icon('path', 20)} ${t('rideTitle')}</a></div></header>
        ${summary}
        ${matches.length ? `<div class="rj-card-list">${matches.map(matchCard).join('')}</div>` : `<div class="rj-empty rj-empty--search"><div class="rj-empty-art" aria-hidden="true"><img src="/static/assets/higgsfield-empty-reference.png" alt="" loading="lazy"></div><h2>${t('noMatches')}</h2><p>${t('tryWidenSearch')}</p><div class="rj-empty-actions"><a class="primary" href="#/search-form">${t('searchTitle')}</a></div></div>`}
      </section>
    </section>`;
  }

  function tripCard(trip) {
    const route = routeForTrip(trip);
    return `<article class="rj-card rj-trip-card">
      <div class="rj-card-topline"><span class="rj-chip rj-status--${escAttr(trip.status || 'unknown')}">${statusName(trip.status)}</span></div>
      <div class="rj-trip-layout">${pointsSummary(trip.origin, trip.destination)}<div class="rj-trip-meta"><span>${icon('calendarBlank', 19)} ${dateLine(trip.departure)}</span><span>${icon('users', 19)} ${number(trip.seats, 0)} ${t('seats')}</span><span>${route?.distance_m ? km(route.distance_m) : t('unknown')}</span></div></div>
      ${route ? `<div class="rj-inline-route">${routeSvg(route)}${routeAttribution()}</div>` : ''}
      <a class="primary rj-primary rj-link-button" href="#/trip/${encodeURIComponent(trip.id)}">${t('journeyDetail')} ${icon('arrowRight', 20)}</a>
    </article>`;
  }

  function journeyPage() {
    /** @type {any[]} */
    const trips = state.data.trips || [];
    const upcoming = trips.filter((trip) => trip.status === 'published');
    const started = trips.filter((trip) => trip.status === 'started');
    const completed = trips.filter((trip) => trip.status === 'completed');
    const other = trips.filter((trip) => !['published', 'started', 'completed'].includes(trip.status));
    const mapTrip = upcoming[0] || started[0] || completed[0] || other[0];
    const route = routeForTrip(mapTrip);
    return `<section class="rj-page rj-journeys-page">
      ${mapPanel({ route, tripId: mapTrip?.id, points: mapTrip ? [mapTrip.origin, mapTrip.destination] : [], label: t('routeAria') })}
      <section class="rj-sheet">
        <div class="rj-sheet-handle" aria-hidden="true"></div>
        <header class="rj-page-heading"><div><h1>${t('journeys')}</h1><p>${new Intl.NumberFormat(locale()).format(trips.length)} ${t('trips')}</p></div></header>
        ${upcoming.length ? `<section class="rj-trip-group"><h2>${t('statusPublished')}</h2><div class="rj-card-list">${upcoming.map(tripCard).join('')}</div></section>` : ''}
        ${started.length ? `<section class="rj-trip-group"><h2>${t('statusStarted')}</h2><div class="rj-card-list">${started.map(tripCard).join('')}</div></section>` : ''}
        ${trips.length === 0 ? `<div class="rj-empty rj-empty--compact"><div class="rj-empty-art" aria-hidden="true"><img src="/static/assets/higgsfield-empty-reference.png" alt="" loading="lazy"></div><h2>${t('emptyTrips')}</h2><a class="primary" href="#/drive-form">${t('drive')}</a></div>` : ''}
        ${completed.length ? `<details class="rj-history"><summary>${t('statusCompleted')} · ${completed.length}</summary><div class="rj-card-list">${completed.map(tripCard).join('')}</div></details>` : ''}
        ${other.length ? `<details class="rj-history"><summary>${t('status')}: ${other.length}</summary><div class="rj-card-list">${other.map(tripCard).join('')}</div></details>` : ''}
      </section>
    </section>`;
  }

  function bookingCard(booking) {
    const match = matchFor(booking);
    const isDriver = booking.driver_id === state.user?.id;
    const currentTripStatus = booking.trip_status || match.trip_status;
    const trip = tripFor(booking.trip_id);
    const request = requestFor(booking);
    const route = routeForBooking(booking);
    const counterpart = booking.counterpart_summary || (!isDriver ? match.driver_summary : null);
    const contactAllowed = booking.status === 'accepted' && ['published', 'started'].includes(currentTripStatus);
    const chatAllowed = booking.status === 'accepted' || booking.status === 'segment_completed';
    const ownRating = (state.data.ratings || []).find((rating) => rating.booking_id === booking.id && rating.author_id === state.user?.id);
    const bookedRouteKm = route?.distance_m ? km(route.distance_m) : t('unknown');
    const statusClass = `rj-status--${escAttr(booking.status || 'unknown')}`;
    const requestHeader = isDriver && booking.status === 'pending' ? t('inbox') : t('bookingDetail');
    const segment = booking.start_m != null && booking.end_m != null
      ? `${km(booking.start_m)} – ${km(booking.end_m)} ${t('exampleKm')}`
      : `${esc(labelOf(booking.pickup || match.pickup))} → ${esc(labelOf(booking.dropoff || match.dropoff))}`;
    /** @type {string[]} */
    const controls = [];
    if (isDriver && booking.status === 'pending') {
      controls.push(`<button class="secondary rj-secondary" type="button" data-action="decline" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('decline')}</button>`);
      controls.push(`<button class="primary rj-primary" type="button" data-action="accept" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('accept')}</button>`);
    }
    if (booking.status === 'accepted') {
      controls.push(`<a class="secondary rj-secondary" href="#/live/${encodeURIComponent(booking.id)}">${t('liveTitle')}</a>`);
      if (!isDriver && currentTripStatus === 'started') {
        if (!booking.boarded_at) controls.push(`<button class="secondary rj-secondary" type="button" data-action="board-segment" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('imOnboard')}</button>`);
        controls.push(`<button class="primary rj-primary" type="button" data-action="complete-segment" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('completeSegment')}</button>`);
      }
    }
    if (['published', 'started'].includes(currentTripStatus) && booking.status === 'accepted') controls.push(`<a class="secondary rj-secondary" href="tel:112">${icon('phone', 19)} ${t('call112')}</a>`);
    if (chatAllowed) controls.push(`<a class="secondary rj-secondary" href="#/chat/${encodeURIComponent(booking.id)}">${icon('chatCircleDots', 19)} ${t('communityChat')}</a>`);
      if (contactAllowed) controls.push(`<span data-community-contact-slot><button class="secondary rj-secondary" type="button" data-community-contact="${escAttr(booking.id)}">${icon('phone', 19)} ${t('communityContact')}</button><span data-community-contact-result aria-live="polite"></span></span>`);
    if (['pending', 'accepted'].includes(booking.status) && currentTripStatus === 'published') controls.push(`<button class="secondary rj-secondary" type="button" data-action="cancel-booking" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('cancel')}</button>`);
    if ([booking.driver_id, booking.passenger_id].includes(state.user?.id)) controls.push(`<a class="rj-safety-link" href="#/safety/${encodeURIComponent(booking.id)}">${t('bookingSafety')}</a>`);
    if (booking.status === 'segment_completed' && currentTripStatus === 'completed') controls.push(ownRating
      ? `<span class="rj-chip rj-chip--quiet">${t('yourRating')}: ${Number(ownRating.stars)}/5</span>`
      : `<a class="secondary rj-secondary" href="#/rate/${encodeURIComponent(booking.id)}">${t('rate')}</a>`);
    if (booking.status === 'segment_completed' && currentTripStatus === 'completed') controls.push(`<a class="secondary rj-secondary" href="#/complete/${encodeURIComponent(booking.id)}">${t('journeyDetail')}</a>`);

    return `<article class="rj-card rj-booking-card" data-booking-id="${escAttr(booking.id)}">
      <header class="rj-booking-header"><div><p class="rj-eyebrow">${requestHeader}</p><h2>${esc(labelOf(booking.pickup || match.pickup))} <span aria-hidden="true">→</span> ${esc(labelOf(booking.dropoff || match.dropoff))}</h2></div><span class="rj-chip ${statusClass}">${statusName(booking.status)}</span></header>
      <div class="rj-booking-times"><div><small>${t('tripDeparture')}</small><strong>${dateLine(booking.trip_departure || trip?.departure)}</strong></div><div><small>${t('pickup')}</small><strong>${dateLine(match.pickup_at)}</strong></div><div><small>${t('dropoff')}</small><strong>${dateLine(match.dropoff_at)}</strong></div>${request?.window_start && request?.window_end ? `<div><small>${t('pickupFrom')} – ${t('pickupUntil')}</small><strong>${dateLine(request.window_start)} – ${dateLine(request.window_end)}</strong></div>` : ''}</div>
      <div class="rj-booking-route">${pointsSummary(booking.pickup || match.pickup, booking.dropoff || match.dropoff)}</div>
      ${roadNote('roadPickup', match.routed_pickup, match.pickup_snap_m)}${roadNote('roadDropoff', match.routed_dropoff, match.dropoff_snap_m)}
      ${match.verification ? `<details class="rj-checks"><summary>${t('checks')}</summary>${checks(match.verification)}</details>` : ''}
      <div class="rj-booking-facts"><div><small>${t('seatsNeeded')}</small><strong>${number(booking.seats || 1, 0)}</strong></div><div><small>${t('segmentInventory')}</small><strong>${segment}</strong><small>${t('inventoryPosition')}</small></div><div><small>${t('distance')}</small><strong>${bookedRouteKm}</strong></div><div><small>${t('driver')}</small><strong>${esc(isDriver ? (booking.passenger_name || t('unknown')) : (booking.driver_name || t('unknown')))}</strong></div></div>
      ${counterpart ? `<div class="rj-counterpart-summary">${publicPerson(counterpart, segmentMeters(booking))}</div>` : ''}
      <div class="rj-detour-block"><div><small>${t('incrementalDetour')}</small><strong>${minText(match.incremental_detour_minutes)}</strong></div><div><small>${t('pickupDetour')} · ${t('dropoffDetour')}</small><strong>${minText(match.pickup_detour_minutes)} / ${minText(match.dropoff_detour_minutes)}</strong></div><div><small>${t('totalDetour')}</small><strong>${minText(match.total_driver_detour_minutes)}</strong>${trip?.max_detour_minutes != null ? `<small>${t('detourBudget')}: ${number(trip.max_detour_minutes, 0)} ${t('minutes')}</small>` : ''}</div></div>
      <p class="rj-estimate-note">${t('detourEstimate')}</p>
      <p class="rj-contribution-note">${t('noPayment')}</p>
      ${booking.reason ? `<p class="rj-user-note"><small>${t('reason')}</small>${esc(booking.reason)}</p>` : ''}
      ${contactAllowed && !booking.live_location_ended_reason ? `<div class="trip-share-host" data-trip-sharing data-booking-id="${escAttr(booking.id)}"></div>` : ''}
      ${route ? `<div class="rj-inline-route">${routeSvg(route)}${routeAttribution()}</div>` : ''}
      <div class="rj-booking-actions">${controls.join('')}</div>
    </article>`;
  }

  function bookingsPage({ inbox = false } = {}) {
    /** @type {any[]} */
    const all = state.data.bookings || [];
    const rows = inbox
      ? all.filter((booking) => booking.driver_id === state.user?.id && booking.status === 'pending')
      : all.filter((booking) => [booking.driver_id, booking.passenger_id].includes(state.user?.id));
    const firstBooking = rows[0];
    const route = firstBooking ? routeForBooking(firstBooking) : null;
    const tripId = firstBooking?.trip_id || '';
    const title = inbox ? t('inbox') : t('bookings');
    const empty = inbox ? t('emptyRequests') : t('emptyBookings');
    return `<section class="rj-page ${inbox ? 'rj-inbox-page' : 'rj-bookings-page'}">
      ${mapPanel({ route, tripId, points: firstBooking ? [matchFor(firstBooking).routed_pickup || firstBooking.pickup, matchFor(firstBooking).routed_dropoff || firstBooking.dropoff] : [], label: t('routeAria') })}
      <section class="rj-sheet">
        <div class="rj-sheet-handle" aria-hidden="true"></div>
        <header class="rj-page-heading"><div><h1>${title}</h1><p>${new Intl.NumberFormat(locale()).format(rows.length)} ${inbox ? t('pendingCount') : t('trips')}</p></div><button class="rj-edit-link" type="button" data-action="refresh" ${state.busy ? 'disabled' : ''}>${icon('arrowRight', 20)} ${t('refresh')}</button></header>
        ${rows.length ? `<div class="rj-card-list">${rows.map(bookingCard).join('')}</div>` : `<div class="rj-empty rj-empty--compact"><h2>${empty}</h2>${!inbox ? `<a class="primary" href="#/search-form">${t('ride')}</a>` : ''}</div>`}
      </section>
    </section>`;
  }

  return {
    resultsPage,
    journeyPage,
    bookingPage: () => bookingsPage({ inbox: false }),
    inboxPage: () => bookingsPage({ inbox: true }),
    bookingCard,
  };
}
