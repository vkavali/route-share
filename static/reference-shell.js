/* Screen shells for the four core journeys. App state, localization, icons,
   validation and event delegation remain owned by app.js. */

export function renderLogin({ state, t, icon, escAttr, hostedBeta, phoneContent, legacyOpen=false, phoneBusy=false }) {
  const accounts = [
    ['driver', 'accountDriver', 'driver'],
    ['passenger', 'accountPassenger', 'passenger'],
    ['passenger2', 'accountPassenger2', 'users'],
    ['admin', 'accountAdmin', 'admin']
  ].filter(([id])=>id==='admin'||state.boot?.flags?.demo_password_enabled===true);
  const selected = state.form?.id === 'login-form'
    ? state.form.values?.account || accounts[0][0]
    : accounts[0][0];
  const password = state.form?.id === 'login-form'
    ? state.form.values?.password ?? (hostedBeta() ? '' : 'local-beta-only')
    : hostedBeta() ? '' : 'local-beta-only';
  const privateBeta = state.boot?.flags?.public_registration_enabled === false;
  const phoneHeading = state.boot?.flags?.public_registration_enabled === true
    ? t('phoneSignIn')
    : t('welcomeToSeatPal');
  const loginCopy = ({
    en: { title: 'A shared route. A better journey.', lead: 'Find your way. Share the journey.', signin: 'Sign in', intro: 'Welcome back. Your next journey starts here.' },
    te: { title: 'అదే దారి. కలిసి ప్రయాణం.', lead: 'మీ దారిలో తోడుగా ప్రయాణిద్దాం.', signin: 'సైన్ ఇన్', intro: 'స్వాగతం. మీ తదుపరి ప్రయాణం ఇక్కడే మొదలు.' },
    hi: { title: 'एक रास्ता। साथ सफ़र।', lead: 'अपना रास्ता चुनें। साथ सफ़र करें।', signin: 'साइन इन', intro: 'स्वागत है। आपका अगला सफ़र यहीं से शुरू होता है।' }
  })[state.lang] || { title: 'A shared route. A better journey.', lead: 'Find your way. Share the journey.', signin: 'Sign in', intro: 'Welcome back. Your next journey starts here.' };

  const passwordForm = `<form id="login-form">
    ${state.boot?.flags?.demo_password_enabled===true?`<fieldset class="account-choice-fieldset">
      <legend>${t('account')}</legend>
      <select class="sr-only" name="account" id="account-choice" tabindex="-1" aria-hidden="true" required>
        ${accounts.map(([key, label]) => `<option value="${key}" ${selected === key ? 'selected' : ''}>${t(label)}</option>`).join('')}
      </select>
      <div class="account-choice-grid">
        ${accounts.map(([key, label, ico]) => `<button type="button" class="account-choice ${selected === key ? 'selected' : ''}" data-account-choice="${key}" aria-pressed="${selected === key}">${icon(ico, 24)}<span>${key === 'admin' && state.lang === 'en' ? 'Admin' : t(label)}</span></button>`).join('')}
      </div>
    </fieldset>`:`<label class="field">${t('phoneStaffAccount')}<input name="account" autocomplete="username" required maxlength="100" value="${escAttr(state.form?.id==='login-form'?state.form.values?.account||'':'')}"></label>`}
    <label class="field password-label">${t('password')}
      <span class="password-control">${icon('lock', 22)}
        <input id="login-password" name="password" type="${state.passwordVisible ? 'text' : 'password'}" value="${escAttr(password)}" autocomplete="current-password" placeholder="${escAttr(t('password'))}" required>
        <button type="button" class="password-toggle" data-action="password-toggle" aria-label="${state.passwordVisible ? t('hidePassword') : t('showPassword')}">${icon(state.passwordVisible ? 'eyeSlash' : 'eye', 24)}</button>
      </span>
      <small>${hostedBeta() ? t('hostedPasswordHint') : `${t('localDefault')}: <code>local-beta-only</code>`}</small>
    </label>
    <button type="submit" class="primary auth-submit" ${state.busy||phoneBusy ? 'disabled' : ''}>${t('signin')} ${icon('arrowRight', 22)}</button>
  </form>`;
  const languageFallback = `<button type="button" class="auth-language-fallback text-button" data-language-choice="hi" lang="hi" aria-pressed="${state.lang==='hi'}">हिन्दी</button>`;
  const accountFootnote = `<p class="auth-footnote">${icon('lock', 20)}<span>${t('developmentAccountsFootnote')}</span></p>`;
  const betaNotice = `<p class="auth-private-note">${t('privateBetaNotice')}</p>`;
  const betaLabel = `<span class="auth-beta-label">${t('privateBetaTitle')}</span>`;
  const authEntry = privateBeta
    ? `<header class="auth-entry-heading">${betaLabel}<h1 class="auth-welcome">${loginCopy.signin}</h1><p class="auth-entry-intro">${loginCopy.intro}</p>${betaNotice}</header>
       <div class="auth-form-wrap">${passwordForm}${languageFallback}${accountFootnote}</div>
       <section class="auth-phone-secondary" aria-label="${phoneHeading}"><h2 class="auth-secondary-title">${phoneHeading}</h2>${phoneContent||''}</section>`
    : `<header class="auth-entry-heading"><h1 class="auth-welcome">${phoneHeading}</h1><p class="auth-entry-intro">${loginCopy.intro}</p></header>
       <div class="auth-phone-primary">${phoneContent||''}</div>
       <details id="phone-legacy-signin" class="phone-legacy" ${legacyOpen?'open':''}><summary>${t('phoneLegacySignIn')}</summary><div class="auth-form-wrap">${betaLabel}${betaNotice}${passwordForm}${languageFallback}${accountFootnote}</div></details>`;

  return `<section class="auth-page ref-login hf-auth ${privateBeta ? 'auth-phone-disabled' : ''}">
    <div class="auth-main">${authEntry}
      <nav class="auth-public-links" aria-label="${state.lang==='te'?'యాప్ గురించి':state.lang==='hi'?'About this beta (English)':'About this beta'}"><a href="/welcome?lang=${state.lang==='te'?'te':'en'}">${state.lang==='te'?'ఇది ఎలా పని చేస్తుంది?':state.lang==='hi'?'How it works (English)':'How it works'}</a><a href="/faq?lang=${state.lang==='te'?'te':'en'}">${state.lang==='te'?'సాధారణ ప్రశ్నలు':state.lang==='hi'?'FAQs (English)':'FAQs'}</a></nav>
    </div>
  </section>`;
}
export function renderHome({ state, t, icon, routeComposer }) {
  const copy = composerCopy[state.lang] || composerCopy.en;
  return `<section class="hf-composer hf-home ref-home">
    <header class="hf-heading"><h1>${copy.title}</h1><p>${copy.lead}</p></header>
    ${composerMap(state, t, icon)}
    <form id="home-route-form" class="hf-form">
      <div class="hf-route-fields">${composerLocations(routeComposer, icon, true)}</div>
      <div class="hf-actions"><button type="button" class="primary hf-action" data-action="home-search">${icon('search', 24)}<span><strong>${t('findRide')}</strong></span>${icon('arrowRight', 22)}</button></div>
      <button type="button" class="hf-owner-link" data-action="home-drive">${icon('car', 21)}<span>${t('offerRide')}</span>${icon('arrowRight', 19)}</button>
      <p class="hf-area-note">${t('pilotServiceAreaHint')}</p>
    </form>
  </section>`;
}

export function renderBecomeDriver({ state, t, icon }) {
  const enabled = state.user?.access?.can_drive === true;
  return `<section class="page-head"><button class="back" type="button" data-action="back">${icon('back', 20)} ${t('back')}</button><div><h1>${t('driverAccessTitle')}</h1><p class="muted">${enabled ? t('driverAccessEnabled') : t('driverAccessNotEnabled')}</p></div></section><section class="panel"><p>${t('driverAccessRequirements')}</p><p class="muted">${t('driverAccessProviderUnavailable')}</p><a class="secondary" href="#/profile">${t('communityProfile')}</a></section>`;
}

const composerCopy = {
  en: { title: 'Where are you going?', lead: 'Share the journey. A kinder way to travel.', find: 'Join a shared trip', offer: 'Share your empty seats', departure: 'Departure · IST', from: 'Pickup from · IST', until: 'Pickup until · IST', detour: 'Extra driving', map: 'Choose your pickup and drop-off' },
  te: { title: 'ఎక్కడికి వెళ్తున్నారు?', lead: 'కలిసి ప్రయాణిద్దాం. దారిలో తోడుగా.', find: 'రైడ్‌లో చేరండి', offer: 'ఖాళీ సీట్లు షేర్ చేయండి', departure: 'బయలుదేరే సమయం · IST', from: 'పికప్ మొదలు · IST', until: 'పికప్ చివర · IST', detour: 'అదనపు డ్రైవింగ్', map: 'పికప్, దిగే చోటు ఎంచుకోండి' },
  hi: { title: 'कहाँ जा रहे हैं?', lead: 'साथ चलें। सफ़र को बेहतर बनाएँ।', find: 'साझा सफ़र में शामिल हों', offer: 'खाली सीटें साझा करें', departure: 'रवानगी · IST', from: 'पिकअप शुरू · IST', until: 'पिकअप अंत · IST', detour: 'अतिरिक्त ड्राइविंग', map: 'पिकअप और उतरने की जगह चुनें' }
};

function composerHeading(state, t, icon) {
  const copy = composerCopy[state.lang] || composerCopy.en;
  return `<header class="hf-heading"><h1>${copy.title}</h1><p>${copy.lead}</p><button class="back-icon" type="button" data-action="back" aria-label="${t('back')}">${icon('back', 22)}</button></header>`;
}

function composerLocations(routeComposer, icon, swap = false) {
  return routeComposer({ swap }).replaceAll('<span class="route-stop-arrow" aria-hidden="true">›</span>', `<span class="route-stop-arrow" aria-hidden="true">${icon('pin', 23)}</span>`);
}

function composerMap(state, t, icon) {
  const values = state.form?.values || {};
  const empty = !values.origin_lat && !values.destination_lat;
  const copy = composerCopy[state.lang] || composerCopy.en;
  return `<div class="journey-map-shell hf-map"><div class="journey-map" id="journey-map"></div>${empty ? `<div class="hf-map-caption">${icon('pin', 16)} ${copy.map}</div>` : ''}</div>`;
}

export function renderSearchForm({ state, t, icon, routeComposer, seatStepper, escAttr }) {
  const copy = composerCopy[state.lang] || composerCopy.en;
  const windowCopy = ({ en: { title: 'Pickup window', from: 'From', until: 'Until', seat: 'seat' }, te: { title: 'పికప్ సమయం', from: 'నుంచి', until: 'వరకు', seat: 'సీటు' }, hi: { title: 'पिकअप का समय', from: 'शुरू', until: 'तक', seat: 'सीट' } })[state.lang] || { title: 'Pickup window', from: 'From', until: 'Until', seat: 'seat' };
  const values=state.form?.values||{};
  const baggageOpen=Number(values.baggage_small_bags||0)>0||Number(values.baggage_large_suitcases||0)>0||Boolean(values.baggage_notes);
  return `<section class="hf-composer hf-search ref-search-form">
    ${composerHeading(state, t, icon)}
    ${composerMap(state, t, icon)}
    <form id="search-form" class="hf-form" novalidate>
      <div class="hf-route-fields">${composerLocations(routeComposer, icon, true)}</div>
      <div class="hf-dates hf-date-window">
        <div class="hf-window-heading"><span>${icon('calendarBlank', 19)} ${windowCopy.title} · IST</span><label class="hf-passenger-seat"><input type="number" name="seats" min="1" max="1" value="1" readonly aria-label="${t('seatsNeeded')}"><span>${windowCopy.seat}</span></label></div>
        <label class="field hf-date"><span>${windowCopy.from}</span><input type="datetime-local" name="window_start" aria-label="${escAttr(copy.from)}" value="${escAttr(state.form?.values?.window_start || '')}" required></label>
        <label class="field hf-date"><span>${windowCopy.until}</span><input type="datetime-local" name="window_end" aria-label="${escAttr(copy.until)}" value="${escAttr(state.form?.values?.window_end || '')}" required></label>
      </div>
      <label class="field hf-date hf-arrive-by"><span>${t('arriveByOptional')}</span><input type="datetime-local" name="arrive_by" value="${escAttr(state.form?.values?.arrive_by || '')}" aria-describedby="arrive-by-help"><small id="arrive-by-help">${t('arriveByHelp')}</small><small class="field-error" id="arrive_by-error" aria-live="polite"></small></label>
      <details class="hf-extra-details hf-baggage-details" ${baggageOpen?'open':''}>
        <summary>${t('baggageDetails')}</summary>
        <div class="hf-extra-grid">
          <label class="field"><span>${t('smallBags')}</span><input type="number" name="baggage_small_bags" min="0" max="12" step="1" value="${escAttr(state.form?.values?.baggage_small_bags ?? '0')}" inputmode="numeric" required></label>
          <label class="field"><span>${t('largeSuitcases')}</span><input type="number" name="baggage_large_suitcases" min="0" max="12" step="1" value="${escAttr(state.form?.values?.baggage_large_suitcases ?? '0')}" inputmode="numeric" required></label>
          <label class="field hf-notes-field"><span>${t('baggageNotesOptional')}</span><textarea name="baggage_notes" rows="2" maxlength="300" placeholder="${escAttr(t('baggageNotesHint'))}">${escAttr(state.form?.values?.baggage_notes || '')}</textarea></label>
        </div>
      </details>
      <div class="hf-actions"><button class="primary hf-action journey-submit" ${state.busy ? 'disabled' : ''}>${icon('search', 24)}<span><strong>${t('findRide')}</strong></span>${icon('arrowRight', 22)}</button></div>
      <button type="button" class="hf-owner-link" data-action="home-drive">${icon('car', 21)}<span>${t('offerRide')}</span>${icon('arrowRight', 19)}</button>
      <p class="hf-area-note">${t('pilotServiceAreaHint')}</p>
    </form>
  </section>`;
}

export function renderDriveForm({ state, t, icon, routeComposer, seatStepper, escAttr, previewCard }) {
  const copy = composerCopy[state.lang] || composerCopy.en;
  const values=state.form?.values||{};
  const offerOpen=Boolean(values.seat_rate_rupees_per_km)||Boolean(values.seat_rate_rupees_per_km==='0')||Boolean(values.baggage_capacity_known)||Boolean(values.baggage_notes)||(values.air_conditioning&&values.air_conditioning!=='unknown');
  const money=paise=>paise==null?t('unknown'):new Intl.NumberFormat(state.lang==='te'?'te-IN':state.lang==='hi'?'hi-IN':'en-IN',{style:'currency',currency:'INR',minimumFractionDigits:2,maximumFractionDigits:2}).format(paise/100);
  const previewOptions=p=>{if(!p)return '';const legacy=Number.isInteger(p.seat_price_paise)&&p.seat_rate_paise_per_km==null;const rate=Number.isInteger(p.seat_rate_paise_per_km)?money(p.seat_rate_paise_per_km):legacy?money(p.seat_price_paise):t('priceNotListed');const capacity=p.baggage_capacity?`${p.baggage_capacity.small_bags===1?t('oneSmallBag'):t('smallBagCount').replace('{count}',p.baggage_capacity.small_bags)} · ${p.baggage_capacity.large_suitcases===1?t('oneLargeSuitcase'):t('largeSuitcaseCount').replace('{count}',p.baggage_capacity.large_suitcases)}`:t('bagCapacityUnknown');const ac=p.comfort?.air_conditioning==='yes'?t('acDeclaredYes'):p.comfort?.air_conditioning==='no'?t('acDeclaredNo'):t('notSpecified');return `<section class="panel hf-preview-options"><h2>${t('publishedOfferDetails')}</h2><div class="stats-strip"><span><b>${escAttr(rate)}${legacy?'':` / ${t('km')}`}</b><small>${legacy?t('legacyFixedFare'):t('ratePerPassengerRouteKm')}</small></span><span><b>${escAttr(ac)}</b><small>${t('airConditioning')} · ${t('driverDeclared')}</small></span><span><b>${escAttr(capacity)}</b><small>${t('spaceAfterDriverBags')}</small></span></div>${legacy?'':`<p>${t('rateIncludes')}</p>`}${p.baggage_notes?`<p><b>${t('driverBaggageNotesOptional')}:</b> ${escAttr(p.baggage_notes)}</p>`:''}<small>${t('noPaymentCollected')}</small></section>`};
  return `<section class="hf-composer hf-drive ref-drive-form">
    ${composerHeading(state, t, icon)}
    <form id="drive-form" class="hf-form" novalidate>
      <div class="hf-route-fields">${composerLocations(routeComposer, icon)}<p class="form-note">${t('pilotServiceAreaHint')}</p></div>
      <div class="hf-dates">
        <label class="field hf-date"><span>${icon('calendarBlank', 21)} ${copy.departure}</span><input type="datetime-local" name="departure" value="${escAttr(state.form?.values?.departure || '')}" required></label>
      </div>
      ${composerMap(state, t, icon)}
      <div class="hf-driver-options">
        ${seatStepper('seats', 'seats', 3, 1, 6)}
        <label class="field hf-detour"><span>${copy.detour}</span><select name="max_detour_minutes" required><option value="0" ${state.form?.values?.max_detour_minutes === '0' ? 'selected' : ''}>0 ${t('minutes')}</option><option value="5" ${state.form?.values?.max_detour_minutes === '5' ? 'selected' : ''}>5 ${t('minutes')}</option><option value="10" ${!state.form?.values?.max_detour_minutes || state.form?.values?.max_detour_minutes === '10' ? 'selected' : ''}>10 ${t('minutes')}</option><option value="15" ${state.form?.values?.max_detour_minutes === '15' ? 'selected' : ''}>15 ${t('minutes')}</option></select></label>
      </div>
      <details class="hf-extra-details hf-offer-details" ${offerOpen?'open':''}>
        <summary>${t('rideOptionsOptional')}</summary>
        <div class="hf-extra-grid">
          <label class="field hf-price-field"><span>${t('ratePerSeatKm')}</span><input type="number" name="seat_rate_rupees_per_km" min="0" max="100000" step="0.01" value="${escAttr(values.seat_rate_rupees_per_km ?? '')}" inputmode="decimal" aria-describedby="seat-price-help"><small id="seat-price-help">${t('rateIncludes')} ${t('localPreviewNoPayment')}</small></label>
          <label class="field"><span>${t('airConditioning')}</span><select name="air_conditioning"><option value="unknown" ${!state.form?.values?.air_conditioning || state.form?.values?.air_conditioning === 'unknown' ? 'selected' : ''}>${t('notSpecified')}</option><option value="yes" ${state.form?.values?.air_conditioning === 'yes' ? 'selected' : ''}>${t('acDeclaredYes')}</option><option value="no" ${state.form?.values?.air_conditioning === 'no' ? 'selected' : ''}>${t('acDeclaredNo')}</option></select></label>
          <div class="hf-capacity-entry">
            <label class="hf-check-line"><input type="checkbox" name="baggage_capacity_known" value="1" data-baggage-capacity-toggle ${state.form?.values?.baggage_capacity_known === '1' ? 'checked' : ''}><span>${t('baggageCapacityKnown')}</span></label>
            <fieldset class="hf-capacity-fields" data-baggage-capacity-fields ${state.form?.values?.baggage_capacity_known === '1' ? '' : 'hidden disabled'}>
              <legend>${t('spaceAfterDriverBags')}</legend>
              <label class="field"><span>${t('smallBags')}</span><input type="number" name="capacity_small_bags" min="0" max="12" step="1" value="${escAttr(state.form?.values?.capacity_small_bags ?? '')}" inputmode="numeric" required></label>
              <label class="field"><span>${t('largeSuitcases')}</span><input type="number" name="capacity_large_suitcases" min="0" max="12" step="1" value="${escAttr(state.form?.values?.capacity_large_suitcases ?? '')}" inputmode="numeric" required></label>
            </fieldset>
          </div>
          <label class="field hf-notes-field"><span>${t('driverBaggageNotesOptional')}</span><textarea name="baggage_notes" rows="2" maxlength="300" placeholder="${escAttr(t('driverBaggageNotesHint'))}">${escAttr(state.form?.values?.baggage_notes || '')}</textarea></label>
        </div>
      </details>
      <div class="hf-actions">
        <button class="primary hf-action journey-submit" ${state.busy ? 'disabled' : ''}>${icon('path', 27)}<span><strong>${t('preview')}</strong><small>${copy.offer}</small></span></button>
        <button type="button" class="hf-action hf-lime" data-action="home-search">${icon('search', 27)}<span><strong>${t('findRide')}</strong><small>${copy.find}</small></span></button>
      </div>
    </form>
  </section>${previewCard(state.preview)}${previewOptions(state.preview)}`;
}
