/* Route Share trip, safety, and rating view templates.
 * Event handling stays in app.js; IDs, names and data-action hooks here are API.
 */
export function makeTripViews(ctx) {
  const {
    state, t, icon, esc, escAttr, fmtTime,
  } = ctx;
  const labelOf = ctx.labelOf || (point => point?.label || '');
  const userId = () => state.user?.id;
  const bookings = () => state.data?.bookings || [];
  const getBooking = id => ctx.getBooking?.(id) || bookings().find(row => row.id === id);
  const routeHeader = id => {
    if (ctx.bookingRouteHeader) return ctx.bookingRouteHeader(id);
    if (ctx.bookingRouteMap) return ctx.bookingRouteMap(id);
    return '';
  };
  const back = () => `<button class="back-icon" data-action="back" aria-label="${t('back')}">${icon('back', 24)}</button>`;
  const participant = booking => booking && [booking.driver_id, booking.passenger_id].includes(userId());

  function livePage(id) {
    const booking = getBooking(id);
    if (!booking || booking.status !== 'accepted' || !participant(booking)) {
      return `<section class="trip-access-state"><div class="trip-access-mark">${icon('lock', 26)}</div><h1>${t('liveTitle')}</h1><p>${t('liveRouteUnavailable')}</p><a class="secondary" href="#/bookings">${t('bookings')}</a></section>`;
    }
    // This exact mount and data attribute are consumed by mountLivePage() in app.js.
    return `<section class="page-head live-page-head trip-live-head"><div><button class="back" data-action="back" aria-label="${t('back')}">${icon('back', 22)}<span class="sr-only">${t('back')}</span></button><h1 class="sr-only">${t('liveTitle')}</h1></div></section><div class="live-location-mount trip-live-mount" data-live-booking="${escAttr(id)}"></div>`;
  }

  function safetyPage(id) {
    const booking = getBooking(id);
    if (!participant(booking)) {
      return `<section class="safety-page trip-safety-page">${back()}<div class="trip-access-state"><div class="trip-access-mark">${icon('lock', 26)}</div><h1>${t('safetyTitle')}</h1><p>${t('safetyNotAllowed')}</p><a class="secondary" href="#/bookings">${t('bookings')}</a></div></section>`;
    }
    const own = (state.data?.safety_reports || []).find(row => row.booking_id === id && row.reporter_id === userId());
    const opponent = booking.driver_id === userId() ? booking.passenger_id : booking.driver_id;
    const blocked = (state.data?.blocks || []).some(row => row.blocked_id === opponent);
    const categories = ['unsafe_driving', 'harassment', 'identity_mismatch', 'other'];
    const receipt = own
      ? `<section class="safety-receipt trip-receipt"><div class="trip-receipt-icon">${icon('checkCircle', 22)}</div><div><h2>${t('reportReceipt')}</h2><p>${t('reportStatus')}: ${t(own.status === 'resolved' ? 'reportResolved' : 'reportOpen')}</p><p>${t('reportCategory')}: ${t(`category_${own.category}`)}</p>${own.resolution ? `<p>${t('resolution')}: ${esc(own.resolution)}</p>` : ''}</div></section>`
      : `<form id="safety-form" data-id="${escAttr(id)}" class="safety-form trip-safety-form"><fieldset class="safety-category-fieldset"><legend>${t('reportCategory')}</legend><div class="safety-category-grid">${categories.map((category, index) => {
        const symbols = ['car', 'users', 'user', 'dotsThree'];
        return `<label class="safety-category-option"><input type="radio" name="category" value="${category}" ${index === 0 ? 'checked' : ''} required><span>${icon(symbols[index], 24)}</span><b>${t(`category_${category}`)}</b></label>`;
      }).join('')}</div></fieldset><label class="field">${t('reportDetails')}<textarea name="details" minlength="10" maxlength="1000" required rows="5"></textarea><small>${t('reportDetailsHelp')}</small></label><button class="primary" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('sendReport')}</button></form>`;
    const block = `<section class="block-section trip-block-section"><div class="trip-block-heading"><span class="trip-block-icon">${icon('prohibit', 22)}</span><div><h2>${t('blockTitle')}</h2><p>${t('blockDisclosure')}</p></div></div>${blocked
      ? `<p class="status-tag">${t('personBlocked')}</p>`
      : state.blockConfirm === id
        ? `<p class="alert warning">${t('blockConfirmText')}</p><div class="trip-block-actions"><button class="danger" data-action="confirm-block" data-id="${escAttr(id)}" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('confirmBlock')}</button><button class="secondary" data-action="cancel-block">${t('cancel')}</button></div>`
        : `<button class="secondary danger" data-action="start-block" data-id="${escAttr(id)}">${t('blockPerson')}</button>`}</section>`;
    return `<section class="safety-page trip-safety-page">${back()}<div class="safety-panel trip-safety-panel"><div class="trip-safety-map">${routeHeader(id)}</div><div class="trip-safety-sheet"><header class="trip-view-heading"><span class="trip-view-kicker">${t('bookingSafety')}</span><h1>${t('reportTitle')}</h1><p class="safety-disclosure">${t('safetyDisclosure')}</p></header>${receipt}${block}<section class="safety-emergency trip-emergency"><span class="trip-emergency-icon">${icon('phone', 22)}</span><div><h2>${t('call112')}</h2><p class="muted">${t('reportNotEmergency')}</p><a class="emergency-link" href="tel:112">${t('call112')}</a></div></section></div></div></section>`;
  }

  function ratePage(id) {
    const existing = (state.data?.ratings || []).find(row => row.booking_id === id && row.author_id === userId());
    if (existing) {
      return `<section class="rating-page trip-rating-page">${back()}<div class="trip-rating-map">${routeHeader(id)}</div><section class="rating-panel trip-rating-panel"><div class="trip-rating-success"><span class="trip-rating-success-icon">${icon('checkCircle', 24)}</span><div><span class="trip-view-kicker">${t('ratingSaved')}</span><h1>${t('ratingSaved')}</h1></div></div><p><b>${t('yourRating')}:</b> <span class="trip-rating-value">${Number(existing.stars)}/5 ${icon('star', 18)}</span></p>${existing.comment ? `<blockquote class="trip-comment">${esc(existing.comment)}</blockquote>` : ''}<a class="trip-return-link" href="#/bookings">${t('bookings')} ${icon('arrowRight', 18)}</a></section></section>`;
    }
    const booking = getBooking(id);
    if (!participant(booking) || booking.status !== 'segment_completed' || booking.trip_status !== 'completed') {
      return `<section class="rating-page trip-rating-page">${back()}<div class="trip-rating-sheet"><p class="trip-view-kicker">${t('bookingSafety')}</p><h1>${t('rate')}</h1><p>${t('ratingAfterCompletion')}</p><a class="secondary" href="#/bookings">${t('bookings')}</a></div></section>`;
    }
    return `<section class="rating-page trip-rating-page">${back()}<div class="trip-rating-map">${routeHeader(id)}</div><form id="rate-form" data-id="${escAttr(id)}" class="rating-panel trip-rating-panel"><header class="trip-view-heading"><span class="trip-view-kicker">${t('journeys')}</span><h1>${t('rate')}</h1><p>${t('ratingPrompt')}</p></header><fieldset class="rating-fieldset trip-rating-fieldset"><legend class="sr-only">${t('stars')}</legend><div class="rating-stars">${[1, 2, 3, 4, 5].map(number => `<label class="rating-star"><input type="radio" name="stars" value="${number}" aria-label="${escAttr(`${number} ${t('stars')}`)}" required><span>${icon('star', 38)}</span></label>`).join('')}</div><p class="rating-hint">${t('ratingHint')}</p></fieldset><label class="field">${t('comment')}<textarea name="comment" maxlength="300" rows="4"></textarea></label><button class="primary rating-submit" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('saveRating')} ${icon('arrowRight', 22)}</button></form></section>`;
  }

  function completedTripPage(id) {
    const booking = getBooking(id);
    if (!booking || booking.status !== 'segment_completed' || booking.trip_status !== 'completed' || !participant(booking)) return '';
    const rated = (state.data?.ratings || []).some(row => row.booking_id === id && row.author_id === userId());
    return `<section class="completed-trip-page trip-completed-page">${back()}<div class="completed-trip-panel"><div class="trip-completed-map">${routeHeader(id)}</div><span class="trip-complete-mark">${icon('checkCircle', 28)}</span><span class="trip-view-kicker">${t('trip_completed')}</span><h1>${t('trip_completed')}</h1><p>${esc(labelOf(booking.pickup) || '')} <span aria-hidden="true">→</span> ${esc(labelOf(booking.dropoff) || '')}</p><p>${t('liveEnded')}</p><div class="trip-completed-actions">${rated ? `<span class="status-tag">${t('ratingSaved')}</span>` : `<a class="primary" href="#/rate/${encodeURIComponent(id)}">${t('rate')} ${icon('arrowRight', 20)}</a>`}<a class="secondary" href="#/safety/${encodeURIComponent(id)}">${t('bookingSafety')}</a></div></div></section>`;
  }

  return { livePage, safetyPage, ratePage, completedTripPage, getBooking };
}
