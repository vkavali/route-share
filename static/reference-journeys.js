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
  const mapPanel = ({ route, tripId, points = [], label, compact = false, caption = '' }) => {
    const actualRoute = routeBounds(route);
    const routeJson = actualRoute ? escAttr(JSON.stringify(actualRoute.coordinates)) : '';
    const pointJson = points.length ? escAttr(JSON.stringify(points.filter(Boolean).map((point) => ({ lat: point.lat, lon: point.lon, label: point.label || '' })))) : '';
    return `<div class="rj-map-frame${compact ? ' rj-map-frame--compact' : ''}" aria-label="${escAttr(label)}">
      ${caption ? `<div class="rj-map-caption">${esc(caption)}</div>` : ''}
      <div class="journey-map rj-map" data-journey-route-map data-route-trip-id="${escAttr(tripId || '')}"${routeJson ? ` data-route-coordinates="${routeJson}"` : ''}${pointJson ? ` data-route-points="${pointJson}"` : ''} aria-label="${escAttr(label)}"></div>
    </div>`;
  };
  const pointsSummary = (from, to, extra = '') => `<div class="rj-route-line">
    <div class="rj-stop rj-stop--start"><span class="rj-stop-icon" aria-hidden="true">${icon('pin', 20)}</span><div><small>${t('origin')}</small><strong>${esc(pointLabel(from))}</strong></div></div>
    <div class="rj-stop-rule" aria-hidden="true"></div>
    <div class="rj-stop rj-stop--end"><span class="rj-stop-icon" aria-hidden="true">${icon('pin', 20)}</span><div><small>${t('destination')}</small><strong>${esc(pointLabel(to))}</strong></div></div>
    ${extra}
  </div>`;
  const dateLine = (v) => v ? fmtTime(v) : t('unknown');
  const matchRoute = (match) => match.preview_route || null;
  const segmentMeters = (record) => {
    const start = Number(record?.start_m);
    const end = Number(record?.end_m);
    return Number.isFinite(start) && Number.isFinite(end) && end > start ? end - start : null;
  };
  const publicPerson = (person, segmentM = null) => {
    if (!person) return '';
    const count = Number(person.rating_count) || 0;
    const average = Number(person.rating_average);
    const verified = !person.development && person.verification?.identity === 'verified';
    return `<div class="rj-person"><span class="rj-person-icon" aria-hidden="true">${icon('user', 26)}</span><div class="rj-person-main"><strong>${esc(person.name || t('unknown'))}</strong><small>${t(person.development ? 'communityDevelopment' : verified ? 'communityIdentityVerified' : 'communityNotVerified')}</small></div><div class="rj-person-rating">${count > 0 && Number.isFinite(average) ? `<strong>${icon('star', 15)} ${number(average, 1)}</strong><small>${number(count, 0)} ${t('communityRatingSummary')}</small>` : `<small>${t('communityNoRatings')}</small>`}</div></div>`;
  };
  const fact = (label, value) => `<div><small>${t(label)}</small><strong>${value}</strong></div>`;
  const minutes = value => value == null || !Number.isFinite(Number(value)) ? t('unknown') : minText(value);
  const emptyArt = () => `<img class="rj-empty-illustration" src="/static/assets/higgsfield/empty-journeys.webp" alt="" width="960" height="576">`;

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
    const driver = match.driver_summary || {name: match.driver_name, verification: match.verification};
    const ratingCount = Number(driver.rating_count) || 0;
    const pickupTimestamp = Date.parse(match.pickup_at || '');
    const blocked = state.busy || state.results?.metrics?.complete === false;
    return `<article class="rj-card rj-match-card" data-rj-pickup="${Number.isFinite(pickupTimestamp) ? pickupTimestamp : ''}" data-rj-detour="${match.incremental_detour_minutes == null ? '' : Number(match.incremental_detour_minutes)}" data-rj-rating="${ratingCount && Number.isFinite(Number(driver.rating_average)) ? Number(driver.rating_average) : ''}" data-rj-rating-count="${ratingCount}">
      <div class="rj-card-topline"><h2 class="rj-departure">${dateLine(match.pickup_at)}</h2><span class="rj-chip rj-chip--accent">${number(match.available_seats, 0)} ${t('available')}</span></div>
      ${publicPerson(driver)}${match.driver_id?`<a class="af-driver-link" href="#/driver/${encodeURIComponent(match.driver_id)}">${t('afViewDriver')} ${icon('arrowRight',18)}</a>`:''}
      <div class="rj-match-route">${pointsSummary(match.routed_pickup || match.pickup, match.routed_dropoff || match.dropoff)}<div class="rj-route-stat">${fact('sharedSegmentEstimate', km(segmentMeters(match)))}${fact('incrementalDetour', minutes(match.incremental_detour_minutes))}</div></div>
      <details class="rj-review"><summary class="rj-primary rj-review-trigger">${t('reviewRide')} ${icon('arrowRight', 20)}</summary><div class="rj-review-content">
        <header class="rj-review-heading"><p class="rj-eyebrow">${t('bookingReviewTitle')}</p><h3>${esc(pointLabel(match.pickup))} → ${esc(pointLabel(match.dropoff))}</h3></header>
        <div class="rj-booking-times">${fact('pickup', dateLine(match.pickup_at))}${fact('dropoff', dateLine(match.dropoff_at))}${fact('seatsNeeded', number(state.results?.request?.seats || 1, 0))}</div>
        <div class="rj-meeting-points">${roadNote('roadPickup', match.routed_pickup, match.pickup_snap_m)}${roadNote('roadDropoff', match.routed_dropoff, match.dropoff_snap_m)}</div>
        <p class="rj-vehicle">${icon('car', 20)} ${esc(vehicleText(match.vehicle))}</p>
        <details class="rj-more"><summary>${t('totalDetour')}: ${minutes(match.total_driver_detour_minutes)} ${icon('arrowRight',18)}</summary><div class="rj-detour-block">${fact('pickupDetour', minutes(match.pickup_detour_minutes))}${fact('dropoffDetour', minutes(match.dropoff_detour_minutes))}${fact('totalDetour', minutes(match.total_driver_detour_minutes))}${trip?.max_detour_minutes != null ? fact('detourBudget', minutes(trip.max_detour_minutes)) : ''}</div>
        <p class="rj-estimate-note">${t('detourEstimate')}</p></details>
        <details class="rj-checks"><summary>${t('checks')}</summary>${checks(match.verification)}</details>
        <p class="rj-contribution-note">${t('noPayment')}</p>
        <button class="primary rj-primary" type="button" data-action="request-seat" data-id="${escAttr(match.id)}" ${blocked ? 'disabled' : ''}>${t('requestSeat')} ${icon('arrowRight', 20)}</button>
      </div></details>
    </article>`;
  }

  function resultsPage() {
    const results = state.results;
    if (!results) return `<section class="rj-page"><div class="rj-empty"><h1>${t('searchTitle')}</h1><p>${t('noMatches')}</p><a class="primary" href="#/search-form">${t('ride')}</a></div></section>`;
    /** @type {any[]} */
    const matches = results.matches || [];
    const incomplete = results.metrics?.complete === false;
    const request = results.request || {};
    const first = matches[0];
    const firstRoute = first ? matchRoute(first) : null;
    const firstTripId = first?.trip_id || '';
    const summary = `<div class="rj-search-summary">
        <div><small>${t('origin')}</small><strong>${esc(pointLabel(request.origin))}</strong></div><span aria-hidden="true">${icon('arrowRight', 19)}</span>
      <div><small>${t('destination')}</small><strong>${esc(pointLabel(request.destination))}</strong></div>
      <a class="rj-search-edit" href="#/search-form" aria-label="${escAttr(t('rideTitle'))}">${icon('path', 20)}</a><div class="rj-search-time"><small>${t('date')}</small><strong>${dateLine(request.window_start)}</strong>${request.window_end ? `<small>${t('pickupUntil')}: ${dateLine(request.window_end)}</small>` : ''}${request.seats != null ? `<small>${t('seatsNeeded')}: ${number(request.seats, 0)}</small>` : ''}</div>
    </div>`;
    return `<section class="rj-page rj-results-page">
      ${summary}
      ${mapPanel({ route: firstRoute, tripId: firstTripId, points: first ? [first.routed_pickup || first.pickup, first.routed_dropoff || first.dropoff] : [request.origin, request.destination].filter(Boolean), label: t('routeAria'), caption: firstRoute ? `${t('estimatedRoutePreview')} · ${first.driver_summary?.name || first.driver_name || t('unknown')}` : '' })}
      <section class="rj-sheet">
        <div class="rj-sheet-handle" aria-hidden="true"></div>
        <header class="rj-page-heading"><div><h1>${t('tripsAlongRoute')}</h1><p>${number(matches.length, 0)} ${t('matches')}</p></div><select class="rj-edit-link" data-rj-sort aria-label="${escAttr(t('sortResults'))}"><option value="recommended">${t('sortRecommended')}</option><option value="soonest">${t('sortSoonest')}</option><option value="least-driving">${t('sortLeastDriving')}</option><option value="best-rated">${t('sortBestRated')}</option></select></header>
        ${incomplete ? `<div class="alert warning" role="status"><p>${t('incomplete')}</p><a class="secondary" href="#/search-form">${t('retry')}</a></div>` : ''}
        ${matches.length ? `<div class="rj-card-list">${matches.map(matchCard).join('')}</div>` : incomplete ? '' : `<div class="rj-empty rj-empty--search">${emptyArt()}<h2>${t('noMatches')}</h2><p>${t('tryWidenSearch')}</p><div class="rj-empty-actions"><a class="primary" href="#/search-form">${t('searchTitle')}</a></div></div>`}
      </section>
    </section>`;
  }

  function tripCard(trip) {
    const route = routeForTrip(trip);
    const bookings = (state.data.bookings || []).filter(row => row.trip_id === trip.id);
    const pending = bookings.filter(row => row.status === 'pending').length;
    const accepted = bookings.filter(row => ['accepted','segment_completed'].includes(row.status)).length;
    return `<article class="rj-card rj-trip-card">
      <div class="rj-card-topline"><h2 class="rj-departure">${icon('calendarBlank', 21)} ${dateLine(trip.departure)}</h2><span class="rj-chip rj-status--${escAttr(trip.status)}">${statusName(trip.status)}</span></div>
      ${pointsSummary(trip.origin, trip.destination)}
      <div class="rj-trip-stats">${fact('seats', number(trip.seats, 0))}${fact('accepted', number(accepted, 0))}${fact('pendingCount', number(pending, 0))}</div>
      ${pending ? `<a class="primary rj-primary rj-link-button" href="#/inbox">${t('reviewRideRequest')} · ${number(pending, 0)} ${icon('arrowRight', 20)}</a>` : ''}
      <a class="secondary rj-secondary rj-link-button" href="#/trip/${encodeURIComponent(trip.id)}">${t('journeyDetail')} ${icon('arrowRight', 20)}</a>
      ${trip.driver_id===state.user?.id&&state.user?.access?.can_drive===true?`<a class="secondary rj-secondary rj-link-button" href="#/trip-budget/${encodeURIComponent(trip.id)}">${t('afTripBudget')} ${icon('arrowRight',20)}</a>`:''}
    </article>`;
  }

  function journeyPage() {
    const trips = state.data.trips || [];
    const upcoming = trips.filter(trip => ['published','started'].includes(trip.status));
    const history = trips.filter(trip => !['published','started'].includes(trip.status));
    const mapTrip = upcoming[0] || history[0];
    const pending = (state.data.bookings || []).filter(row => row.driver_id === state.user?.id && row.status === 'pending').length;
    return `<section class="rj-page rj-journeys-page">
      <header class="rj-dashboard-heading"><div><h1>${t('yourSharedTrips')}</h1><p>${number(trips.length, 0)} ${t('trips')}</p></div><a class="rj-edit-link" href="#/drive-form">${icon('plus', 20)} ${t('offerRide')}</a></header>
      ${mapPanel({route:routeForTrip(mapTrip),tripId:mapTrip?.id,points:mapTrip?[mapTrip.origin,mapTrip.destination]:[],label:t('routeAria')})}
      <section class="rj-sheet"><div class="rj-sheet-handle" aria-hidden="true"></div>
        ${pending ? `<a class="rj-pending-callout" href="#/inbox">${icon('users', 22)} <strong>${number(pending, 0)} ${t('pendingCount')}</strong><span>${t('reviewRideRequest')}</span>${icon('arrowRight', 20)}</a>` : ''}
        ${upcoming.length ? `<section class="rj-trip-group"><h2>${t('upcomingTrips')}</h2><div class="rj-card-list">${upcoming.map(tripCard).join('')}</div></section>` : ''}
        ${trips.length ? '' : `<div class="rj-empty">${emptyArt()}<h2>${t('emptyTrips')}</h2><a class="primary" href="#/drive-form">${t('offerRide')}</a></div>`}
        ${history.length ? `<details class="rj-history"><summary>${t('pastTrips')} · ${number(history.length, 0)}</summary><div class="rj-card-list">${history.map(tripCard).join('')}</div></details>` : ''}
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
      controls.push(`<button class="secondary rj-secondary" type="button" data-action="decline" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${t('decline')}</button>`);
      controls.push(`<button class="primary rj-primary" type="button" data-action="accept" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${t('accept')}</button>`);
    }
    if (booking.status === 'accepted') {
      controls.push(`<a class="secondary rj-secondary" href="#/live/${encodeURIComponent(booking.id)}">${t('liveTitle')}</a>`);
      if (!isDriver && currentTripStatus === 'started') {
        if (!booking.boarded_at) controls.push(`<button class="secondary rj-secondary" type="button" data-action="board-segment" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${t('imOnboard')}</button>`);
        controls.push(`<button class="primary rj-primary" type="button" data-action="complete-segment" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${t('completeSegment')}</button>`);
      }
    }
    if (['published', 'started'].includes(currentTripStatus) && booking.status === 'accepted') controls.push(`<a class="secondary rj-secondary" href="tel:112">${icon('phone', 19)} ${t('call112')}</a>`);
    if (chatAllowed) controls.push(`<a class="secondary rj-secondary" href="#/chat/${encodeURIComponent(booking.id)}">${icon('chatCircleDots', 19)} ${t('communityChat')}</a>`);
      if (contactAllowed) controls.push(`<span data-community-contact-slot><button class="secondary rj-secondary" type="button" data-community-contact="${escAttr(booking.id)}">${icon('phone', 19)} ${t('communityContact')}</button><span data-community-contact-result aria-live="polite"></span></span>`);
    if (['pending', 'accepted'].includes(booking.status) && currentTripStatus === 'published') controls.push(`<button class="secondary rj-secondary" type="button" data-action="cancel-booking" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${t('cancel')}</button>`);
    if ([booking.driver_id, booking.passenger_id].includes(state.user?.id)) controls.push(`<a class="rj-safety-link" href="#/safety/${encodeURIComponent(booking.id)}">${t('bookingSafety')}</a>`);
    if (booking.status === 'segment_completed' && currentTripStatus === 'completed') controls.push(ownRating
      ? `<span class="rj-chip rj-chip--quiet">${t('yourRating')}: ${Number(ownRating.stars)}/5</span>`
      : `<a class="secondary rj-secondary" href="#/rate/${encodeURIComponent(booking.id)}">${t('rate')}</a>`);
    if (booking.status === 'segment_completed' && currentTripStatus === 'completed') controls.push(`<a class="secondary rj-secondary" href="#/complete/${encodeURIComponent(booking.id)}">${t('journeyDetail')}</a>`);

    return `<article class="rj-card rj-booking-card" data-booking-id="${escAttr(booking.id)}">
      ${booking.status === 'pending' && !isDriver ? `<div class="rj-pending-state"><span>${icon('clock', 28)}</span><div><h2>${t('requestSent')}</h2><strong>${t('waitingForOwner')}</strong><p>${t('seatRequestPendingHelp')}</p></div></div>` : ''}
      <header class="rj-booking-header"><div><p class="rj-eyebrow">${isDriver && booking.status === 'pending' ? t('reviewRideRequest') : requestHeader}</p><h2>${esc(pointLabel(booking.pickup || match.pickup))} → ${esc(pointLabel(booking.dropoff || match.dropoff))}</h2></div><span class="rj-chip ${statusClass}">${statusName(booking.status)}</span></header>
      ${publicPerson(counterpart || {name:isDriver ? booking.passenger_name : booking.driver_name})}${!isDriver?`<a class="af-driver-link" href="#/driver/${encodeURIComponent(booking.driver_id)}">${t('afViewDriver')} ${icon('arrowRight',18)}</a>`:''}
      <div class="rj-booking-times">${fact('pickup',dateLine(match.pickup_at || booking.trip_departure || trip?.departure))}${fact('dropoff',dateLine(match.dropoff_at))}${fact('seatsNeeded',number(booking.seats || 1,0))}</div>
      <div class="rj-booking-route">${pointsSummary(match.routed_pickup || booking.pickup || match.pickup,match.routed_dropoff || booking.dropoff || match.dropoff)}</div>
      <div class="rj-meeting-points">${roadNote('roadPickup', match.routed_pickup, match.pickup_snap_m)}${roadNote('roadDropoff', match.routed_dropoff, match.dropoff_snap_m)}</div>
      ${isDriver ? `<div class="rj-detour-block">${fact('incrementalDetour',minutes(match.incremental_detour_minutes))}${fact('totalDetour',minutes(match.total_driver_detour_minutes))}</div><p class="rj-estimate-note">${t('detourEstimate')}</p>` : ''}
      <p class="rj-contribution-note">${t('afDirectPaymentHelp')}</p>
      ${booking.reason ? `<p class="rj-user-note"><small>${t('reason')}</small>${esc(booking.reason)}</p>` : ''}
      <div class="rj-booking-actions">${controls.join('')}<a class="secondary rj-secondary" href="#/payment/${encodeURIComponent(booking.id)}">${t('afContribution')}</a></div>
      <details class="rj-more"><summary>${t('journeyDetail')} ${icon('arrowRight',18)}</summary><div class="rj-booking-facts">${fact('sharedSegmentEstimate',km(segmentMeters(booking)))}${fact('tripDeparture',dateLine(booking.trip_departure || trip?.departure))}${fact('pickupDetour',minutes(match.pickup_detour_minutes))}${fact('dropoffDetour',minutes(match.dropoff_detour_minutes))}</div>${match.verification ? `<details class="rj-checks"><summary>${t('checks')}</summary>${checks(match.verification)}</details>` : ''}</details>
      ${contactAllowed && !booking.live_location_ended_reason ? `<div class="trip-share-host" data-trip-sharing data-booking-id="${escAttr(booking.id)}"></div>` : ''}
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
        ${rows.length ? `<div class="rj-card-list">${rows.map(row => inbox || (rows.length === 1 && row.status === 'pending') ? bookingCard(row) : `<details class="rj-booking-review"><summary><span class="rj-list-date">${icon('calendarBlank',20)} ${dateLine(matchFor(row).pickup_at || row.trip_departure)}</span><strong>${esc(pointLabel(row.pickup || matchFor(row).pickup))} → ${esc(pointLabel(row.dropoff || matchFor(row).dropoff))}</strong><span class="rj-chip rj-status--${escAttr(row.status)}">${statusName(row.status)}</span><span class="rj-list-more">${t('reviewRide')} ${icon('arrowRight',18)}</span></summary>${bookingCard(row)}</details>`).join('')}</div>` : `<div class="rj-empty rj-empty--compact">${emptyArt()}<h2>${empty}</h2>${!inbox ? `<a class="primary" href="#/search-form">${t('ride')}</a>` : ''}</div>`}
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
