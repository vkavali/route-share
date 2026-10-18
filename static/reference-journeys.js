// @ts-nocheck
import { rankedRides, rideOptionCount } from './ride-options.js';
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
  const quotedKm = metres => metres == null ? t('unknown') : `${number(Number(metres)/1000,3)} ${t('km')}`;
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

  const money = paise => Number.isInteger(paise) && paise >= 0
    ? new Intl.NumberFormat(locale(), {style:'currency',currency:'INR',minimumFractionDigits:2,maximumFractionDigits:2}).format(paise/100)
    : t('unknown');
  const isV2Quote = quote => quote?.version===2 && quote?.basis==='passenger_route_per_seat' && Number.isInteger(quote.amount_paise);
  const isLegacyQuote = quote => quote?.version===1 && quote?.basis==='flat_per_seat' && Number.isInteger(quote.amount_paise);
  const hasKnownQuote = quote => isV2Quote(quote) || isLegacyQuote(quote);
  const tripHasKnownFare = trip => (Number.isInteger(trip?.seat_rate_paise_per_km) && trip.seat_rate_paise_per_km>=0) || (Number.isInteger(trip?.seat_price_paise) && trip.seat_price_paise>=0);
  const quoteText = quote => hasKnownQuote(quote) ? money(quote.amount_paise) : t('priceNotListed');
  const fareBreakdown = (quote, {driver=false, match=null}={}) => {
    if (!hasKnownQuote(quote)) return `<section class="rj-fare-breakdown rj-fare-breakdown--unavailable" aria-label="${escAttr(t('fareDetails'))}"><strong>${t('fareUnavailable')}</strong><p>${t('fareUnavailableHelp')}</p></section>`;
    if (isLegacyQuote(quote)) return `<section class="rj-fare-breakdown" aria-label="${escAttr(t('fareDetails'))}"><div class="rj-fare-total"><span>${t('legacyFixedFare')}</span><strong>${money(quote.amount_paise)}</strong></div><p>${t('legacyFareExplanation')}</p><small>${t('noPaymentCollected')}</small></section>`;
    const distanceM = Number.isInteger(quote.distance_m) ? quote.distance_m : (Number.isInteger(match?.passenger_route_distance_m) ? match.passenger_route_distance_m : null);
    const rate = Number.isInteger(quote.rate_paise_per_km) ? quote.rate_paise_per_km : null;
    const kmText = distanceM == null ? t('unknown') : `${new Intl.NumberFormat(locale(), {maximumFractionDigits:3}).format(distanceM/1000)} ${t('km')}`;
    const rateText = rate == null ? t('unknown') : `${money(rate)} / ${t('km')}`;
    const formula = distanceM != null && rate != null ? `${kmText} × ${rateText} = ${money(quote.fare_paise)}` : t('unknown');
    return `<section class="rj-fare-breakdown" aria-label="${escAttr(t('fareDetails'))}"><div class="rj-fare-total"><span>${t('totalPerSeat')}</span><strong>${money(quote.amount_paise)}</strong></div><div class="rj-fare-lines"><div><span>${t('roadDistance')}</span><strong>${kmText}</strong></div><div><span>${t('fareFormula')}</span><strong>${formula}</strong></div><div><span>${t('seatpalFee')}</span><strong>${money(quote.platform_fee_paise)}</strong></div><div><span>${t('additionalTaxes')}</span><strong>${money(quote.tax_paise)}</strong></div>${driver?`<div class="rj-driver-net"><span>${t('driverNet')}</span><strong>${money(quote.driver_net_paise)}</strong></div>`:''}</div><p>${t('tollsAndBagsIncluded')}</p><small>${t('localPreviewNoPayment')}</small></section>`;
  };
  const bagCount = (count, one, many) => Number(count)===1 ? t(one) : t(many).replace('{count}',number(count,0));
  const bagCounts = bags => {
    if (!bags || (!Number(bags.small_bags) && !Number(bags.large_suitcases))) return t('noBagsRequested');
    return [Number(bags.small_bags)>0?bagCount(bags.small_bags,'oneSmallBag','smallBagCount'):'',Number(bags.large_suitcases)>0?bagCount(bags.large_suitcases,'oneLargeSuitcase','largeSuitcaseCount'):''].filter(Boolean).join(' · ');
  };
  const remainingText = remaining => remaining==null ? t('bagCapacityUnknown') : `${t('spaceWhenSearched')}: ${bagCount(remaining.small_bags,'oneSmallBag','smallBagCount')} · ${bagCount(remaining.large_suitcases,'oneLargeSuitcase','largeSuitcaseCount')}`;
  const comfortText = comfort => comfort?.air_conditioning==='yes' ? t('acDeclaredYes') : comfort?.air_conditioning==='no' ? t('acDeclaredNo') : t('acNotSpecified');
  const savedSearchExpired = results => {const saved=Date.parse(results?.saved_at||results?.request?.created_at||'');return Number.isFinite(saved)&&Date.now()-saved>20*60*1000};
  const requestBags = match => match.passenger_baggage || state.results?.request?.baggage || {small_bags:0,large_suitcases:0};
  const driverNotes = match => match.trip_baggage_notes || match.baggage_notes || '';

  function matchCard(match) {
    const trip = tripFor(match.trip_id);
    const driver = match.driver_summary || {name: match.driver_name, verification: match.verification};
    const ratingCount = Number(driver.rating_count) || 0;
    const pickupTimestamp = Date.parse(match.pickup_at || '');
    const blocked = state.busy || state.results?.metrics?.complete === false || savedSearchExpired(state.results);
    const quote = match.price_quote;
    const quoteAvailable = hasKnownQuote(quote);
    const bags = requestBags(match);
    const remaining = match.baggage_remaining;
    const notes = driverNotes(match);
    return `<article class="rj-card rj-match-card" data-rj-pickup="${Number.isFinite(pickupTimestamp) ? pickupTimestamp : ''}" data-rj-detour="${match.incremental_detour_minutes == null ? '' : Number(match.incremental_detour_minutes)}" data-rj-rating="${ratingCount && Number.isFinite(Number(driver.rating_average)) ? Number(driver.rating_average) : ''}" data-rj-rating-count="${ratingCount}">
      <div class="rj-card-topline"><h2 class="rj-departure">${dateLine(match.pickup_at)}</h2><span class="rj-chip rj-chip--accent">${number(match.available_seats, 0)} ${t('available')}</span></div>
      <div class="rj-booking-times rj-match-times">${fact('dropoff',dateLine(match.dropoff_at))}${state.results?.request?.arrive_by?fact('arrivalDeadline',dateLine(state.results.request.arrive_by)):''}</div>
      <div class="rj-offer-facts"><div><small>${isV2Quote(quote)?t('totalPerSeat'):isLegacyQuote(quote)?t('legacyFixedFare'):t('priceSnapshot')}</small><strong>${esc(quoteText(quote))}</strong>${isV2Quote(quote)?`<small>${quote.distance_m==null?t('unknown'):`${number(quote.distance_m/1000,3)} ${t('km')}`} · ${t('passengerRoute')}</small>`:''}</div><div><small>${t('airConditioning')}</small><strong>${esc(comfortText(match.comfort))}</strong></div><div><small>${t('baggageDetails')}</small><strong>${esc(remainingText(remaining))}</strong></div></div>
      ${publicPerson(driver)}${match.driver_id?`<a class="af-driver-link" href="#/driver/${encodeURIComponent(match.driver_id)}">${t('afViewDriver')} ${icon('arrowRight',18)}</a>`:''}
      <div class="rj-match-route">${pointsSummary(match.routed_pickup || match.pickup, match.routed_dropoff || match.dropoff)}<div class="rj-route-stat">${fact(isV2Quote(quote)?'quotedRoadDistance':'sharedSegmentEstimate', isV2Quote(quote)?quotedKm(quote.distance_m):km(segmentMeters(match)))}${fact('incrementalDetour', minutes(match.incremental_detour_minutes))}</div></div>
      <details class="rj-review" data-fare-review="${escAttr(match.id)}" ${state.fareReviewId===match.id?'open':''}><summary class="rj-primary rj-review-trigger">${t('reviewFareAndRide')} ${icon('arrowRight', 20)}</summary><div class="rj-review-content">
        <header class="rj-review-heading"><p class="rj-eyebrow">${t('bookingReviewTitle')}</p><h3>${esc(pointLabel(match.pickup))} → ${esc(pointLabel(match.dropoff))}</h3></header>
        <div class="rj-booking-times">${fact('pickup', dateLine(match.pickup_at))}${fact('dropoff', dateLine(match.dropoff_at))}${fact('seatsNeeded', number(state.results?.request?.seats || 1, 0))}${state.results?.request?.arrive_by ? fact('arrivalDeadline',dateLine(state.results.request.arrive_by)) : ''}</div>
        <div class="rj-bag-facts">${fact('requestedBags',esc(bagCounts(bags)))}${match.passenger_baggage_notes?fact('passengerBaggageNotesLabel',esc(match.passenger_baggage_notes)):''}${notes?fact('tripBaggageNotes',esc(notes)):''}<small>${t('searchedSnapshot')}</small></div>
        ${fareBreakdown(quote,{match})}
        <div class="rj-meeting-points">${roadNote('roadPickup', match.routed_pickup, match.pickup_snap_m)}${roadNote('roadDropoff', match.routed_dropoff, match.dropoff_snap_m)}</div>
        <p class="rj-vehicle">${icon('car', 20)} ${esc(vehicleText(match.vehicle))}</p>
        <details class="rj-more"><summary>${t('totalDetour')}: ${minutes(match.total_driver_detour_minutes)} ${icon('arrowRight',18)}</summary><div class="rj-detour-block">${fact('pickupDetour', minutes(match.pickup_detour_minutes))}${fact('dropoffDetour', minutes(match.dropoff_detour_minutes))}${fact('totalDetour', minutes(match.total_driver_detour_minutes))}${trip?.max_detour_minutes != null ? fact('detourBudget', minutes(trip.max_detour_minutes)) : ''}</div>
        <p class="rj-estimate-note">${t('detourEstimate')}</p></details>
        <details class="rj-checks"><summary>${t('checks')}</summary>${checks(match.verification)}</details>
        ${quoteAvailable?`<p class="rj-contribution-note">${t('localPreviewNoPayment')}</p>`:''}
        ${!quoteAvailable?`<p class="rj-expiry-note">${t('fareUnavailableHelp')}</p>`:''}
        ${blocked&&savedSearchExpired(state.results)?`<p class="rj-expiry-note">${t('requestExpired')}</p>`:''}
        <button class="primary rj-primary" type="button" data-action="request-seat" data-id="${escAttr(match.id)}" ${blocked || !quoteAvailable ? 'disabled' : ''}>${t('sendSeatRequest')} ${icon('arrowRight', 20)}</button>
      </div></details>
    </article>`;
  }

  function resultsPage() {
    const results = state.results;
    if (!results) return `<section class="rj-page"><div class="rj-empty"><h1>${t('searchTitle')}</h1><p>${t('noMatches')}</p><a class="primary" href="#/search-form">${t('ride')}</a></div></section>`;
    /** @type {any[]} */
    const matches = results.matches || [];
    const mode = ['best','fastest','cheapest','comfort'].includes(state.resultsMode) ? state.resultsMode : 'best';
    const ranked = rankedRides(matches, mode);
    const visibleMatches = ranked.items;
    const incomplete = results.metrics?.complete === false;
    const request = results.request || {};
    const first = visibleMatches[0];
    const firstRoute = first ? matchRoute(first) : null;
    const firstTripId = first?.trip_id || '';
    const summary = `<div class="rj-search-summary">
        <div><small>${t('origin')}</small><strong>${esc(pointLabel(request.origin))}</strong></div><span aria-hidden="true">${icon('arrowRight', 19)}</span>
      <div><small>${t('destination')}</small><strong>${esc(pointLabel(request.destination))}</strong></div>
      <button class="rj-search-edit" type="button" data-results-action="edit-search" aria-label="${escAttr(t('editSearch'))}">${icon('path', 20)}</button><div class="rj-search-time"><small>${t('date')}</small><strong>${dateLine(request.window_start)}</strong>${request.window_end ? `<small>${t('pickupUntil')}: ${dateLine(request.window_end)}</small>` : ''}${request.arrive_by ? `<small>${t('arrivalDeadline')}: ${dateLine(request.arrive_by)}</small>` : ''}${request.seats != null ? `<small>${t('seatsNeeded')}: ${number(request.seats, 0)}</small>` : ''}<small>${t('requestedBags')}: ${esc(bagCounts(request.baggage))}</small>${request.baggage_notes?`<small>${t('passengerBaggageNotesLabel')}: ${esc(request.baggage_notes)}</small>`:''}</div>
    </div>`;
    return `<section class="rj-page rj-results-page">
      ${summary}
      ${state.user?.development===true?`<div class="rj-saved-search rj-sample-notice" role="status">${t('localSampleRides')}</div>`:''}
      <section class="rj-sheet">
        <div class="rj-sheet-handle" aria-hidden="true"></div>
        <header class="rj-page-heading"><div><h1>${t('tripsAlongRoute')}</h1><p>${number(matches.length, 0)} ${t('matches')}</p></div><div class="rj-search-actions"><small>${t('lastSearched')}: ${dateLine(results.saved_at||request.created_at)}</small><button type="button" class="rj-edit-link" data-results-action="search-again" ${state.busy?'disabled':''}>${t('refreshSearch')}</button></div></header>
        <nav class="rj-option-tabs" aria-label="${escAttr(t('rideOptions'))}" role="group">${[['best','rideOptionBest'],['fastest','rideOptionFastest'],['cheapest','rideOptionCheapest'],['comfort','rideOptionComfort']].map(([key,label])=>`<button type="button" class="rj-option-button ${mode===key?'is-selected':''}" data-ride-option="${key}" aria-pressed="${mode===key}"><span>${t(label)}</span><small class="rj-option-count">${number(rideOptionCount(matches,key),0)}</small></button>`).join('')}</nav>
        <p class="rj-option-explanation" role="status" aria-live="polite">${ranked.legacyFallback?t('legacyRankFallback'):t(mode==='best'?(results.ranking_context?.best_basis==='lowest_price_before_deadline'?'bestBasisPrice':'bestBasisArrival'):mode==='fastest'?'fastestBasis':mode==='cheapest'?'cheapestBasis':'comfortBasis')}</p>
        ${savedSearchExpired(results)?`<div class="alert warning" role="status"><p>${t('savedSearchExpired')}</p><button type="button" class="secondary" data-results-action="search-again">${t('searchAgain')}</button></div>`:''}
        ${incomplete ? `<div class="alert warning" role="status"><p>${t('incomplete')}</p><a class="secondary" href="#/search-form">${t('retry')}</a></div>` : ''}
        ${visibleMatches.length ? `<div class="rj-card-list">${visibleMatches.map(matchCard).join('')}</div>` : matches.length ? `<div class="rj-empty-option" role="status"><p>${t(mode==='cheapest'?'emptyPriceOption':'emptyComfortOption')}</p><button type="button" class="secondary" data-ride-option="best">${t('viewAllRides')}</button></div>` : incomplete ? '' : `<div class="rj-empty rj-empty--search">${emptyArt()}<h2>${t('noMatches')}</h2><p>${t('noMatchesGuidance')}</p><div class="rj-empty-actions"><a class="primary" href="#/search-form">${t('editSearch')}</a></div></div>`}
        ${mapPanel({ route: firstRoute, tripId: firstTripId, points: first ? [first.routed_pickup || first.pickup, first.routed_dropoff || first.dropoff] : [request.origin, request.destination].filter(Boolean), label: t('routeAria'), caption: firstRoute ? `${t('estimatedRoutePreview')} · ${first.driver_summary?.name || first.driver_name || t('unknown')}` : '' })}
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
      ${trip.driver_id===state.user?.id&&state.user?.access?.can_drive===true&&!tripHasKnownFare(trip)?`<a class="secondary rj-secondary rj-link-button" href="#/trip-budget/${encodeURIComponent(trip.id)}">${t('afTripBudget')} ${icon('arrowRight',20)}</a>`:''}
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
    const bookedBags = booking.baggage || match.passenger_baggage || request?.baggage || {small_bags:0,large_suitcases:0};
    const bookedQuote = Object.prototype.hasOwnProperty.call(booking,'price_quote') ? booking.price_quote : (match.price_quote ?? null);
    const bookingBagNotes = booking.baggage_notes || match.passenger_baggage_notes || request?.baggage_notes || '';
    const bookingTripNotes = booking.trip_baggage_notes || match.trip_baggage_notes || match.baggage_notes || '';
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
    if (['pending', 'accepted'].includes(booking.status) && ['published', 'started'].includes(currentTripStatus)) controls.push(`<button class="secondary rj-secondary" type="button" data-action="cancel-booking" data-id="${escAttr(booking.id)}" ${state.busy ? 'disabled' : ''}>${t('cancel')}</button>`);
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
      <div class="rj-bag-facts rj-booking-snapshot">${fact('requestedBags',esc(bagCounts(bookedBags)))}</div>
      ${fareBreakdown(bookedQuote,{driver:isDriver,match})}
      <div class="rj-booking-route">${pointsSummary(match.routed_pickup || booking.pickup || match.pickup,match.routed_dropoff || booking.dropoff || match.dropoff)}</div>
      <div class="rj-meeting-points">${roadNote('roadPickup', match.routed_pickup, match.pickup_snap_m)}${roadNote('roadDropoff', match.routed_dropoff, match.dropoff_snap_m)}</div>
      ${isDriver ? `<div class="rj-detour-block">${fact('incrementalDetour',minutes(match.incremental_detour_minutes))}${fact('totalDetour',minutes(match.total_driver_detour_minutes))}</div><p class="rj-estimate-note">${t('detourEstimate')}</p>` : ''}
      ${hasKnownQuote(bookedQuote)?`<p class="rj-contribution-note">${t('localPreviewNoPayment')}</p>`:`<p class="rj-contribution-note">${state.boot?.flags?.direct_upi_enabled===true?t('afDirectPaymentHelp'):t('afPaymentDisabled')}</p>`}
      ${booking.reason ? `<p class="rj-user-note"><small>${t('reason')}</small>${esc(booking.reason)}</p>` : ''}
      <div class="rj-booking-actions">${controls.join('')}${hasKnownQuote(bookedQuote)?'':`<a class="secondary rj-secondary" href="#/payment/${encodeURIComponent(booking.id)}">${t('afContribution')}</a>`}</div>
      <details class="rj-more"><summary>${t('journeyDetail')} ${icon('arrowRight',18)}</summary><div class="rj-booking-facts">${fact(isV2Quote(bookedQuote)?'quotedRoadDistance':'sharedSegmentEstimate',isV2Quote(bookedQuote)?quotedKm(bookedQuote.distance_m):km(segmentMeters(booking)))}${fact('tripDeparture',dateLine(booking.trip_departure || trip?.departure))}${fact('pickupDetour',minutes(match.pickup_detour_minutes))}${fact('dropoffDetour',minutes(match.dropoff_detour_minutes))}${booking.arrive_by||request?.arrive_by?fact('arrivalDeadline',dateLine(booking.arrive_by||request.arrive_by)):''}</div><div class="rj-bag-facts">${fact('requestedBags',esc(bagCounts(bookedBags)))}${bookingBagNotes?fact('passengerBaggageNotesLabel',esc(bookingBagNotes)):''}${fact('priceSnapshot',esc(quoteText(bookedQuote)))}${bookingTripNotes?fact('tripBaggageNotes',esc(bookingTripNotes)):''}<small>${t('searchedSnapshot')}</small></div>${match.verification ? `<details class="rj-checks"><summary>${t('checks')}</summary>${checks(match.verification)}</details>` : ''}</details>
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
