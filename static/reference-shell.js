/* Screen shells for the four core journeys. App state, localization, icons,
   validation and event delegation remain owned by app.js. */

export function renderLogin({ state, t, icon, escAttr, hostedBeta }) {
  const accounts = [
    ['driver', 'accountDriver', 'driver'],
    ['passenger', 'accountPassenger', 'passenger'],
    ['passenger2', 'accountPassenger2', 'users'],
    ['admin', 'accountAdmin', 'admin']
  ];
  const selected = state.form?.id === 'login-form'
    ? state.form.values?.account || 'driver'
    : 'driver';
  const password = state.form?.id === 'login-form'
    ? state.form.values?.password ?? (hostedBeta() ? '' : 'local-beta-only')
    : hostedBeta() ? '' : 'local-beta-only';

  return `<section class="auth-page ref-login">
    <div class="auth-hero">
      <img class="auth-illustration" src="/static/assets/higgsfield-signin-reference.png" alt="">
    </div>
    <div class="auth-card">
      <h1 class="auth-welcome">${t('welcomeTitle')}</h1>
      <p class="auth-subtitle">${t('privateBetaTitle')}</p><p class="auth-introduction">${t('privateBetaNotice')}</p>
      <form id="login-form">
        <fieldset class="account-choice-fieldset">
          <legend>${t('account')}</legend>
          <select class="sr-only" name="account" id="account-choice" tabindex="-1" aria-hidden="true" required>
            ${accounts.map(([key, label]) => `<option value="${key}" ${selected === key ? 'selected' : ''}>${t(label)}</option>`).join('')}
          </select>
          <div class="account-choice-grid">
            ${accounts.map(([key, label, ico]) => `<button type="button" class="account-choice ${selected === key ? 'selected' : ''}" data-account-choice="${key}" aria-pressed="${selected === key}">${icon(ico, 32)}<span>${key === 'admin' && state.lang === 'en' ? 'Admin' : t(label)}</span></button>`).join('')}
          </div>
        </fieldset>
        <label class="field password-label">${t('password')}
          <span class="password-control">${icon('lock', 22)}
            <input id="login-password" name="password" type="${state.passwordVisible ? 'text' : 'password'}" value="${escAttr(password)}" autocomplete="current-password" placeholder="${escAttr(t('password'))}" required>
            <button type="button" class="password-toggle" data-action="password-toggle" aria-label="${state.passwordVisible ? t('hidePassword') : t('showPassword')}">${icon(state.passwordVisible ? 'eyeSlash' : 'eye', 24)}</button>
          </span>
          <small>${hostedBeta() ? t('hostedPasswordHint') : `${t('localDefault')}: <code>local-beta-only</code>`}</small>
        </label>
        <button class="primary auth-submit" ${state.busy ? 'disabled' : ''}>${state.busy ? t('pending') : t('signin')} ${icon('arrowRight', 22)}</button>
      </form>
      <p class="auth-footnote">${icon('lock', 24)}<span>${t('developmentAccountsFootnote')}</span></p>
    </div>
  </section>`;
}

export function renderHome({ t, icon, routeComposer }) {
  return `<section class="home-map-page ref-home">
    <div class="journey-map-shell home-map-shell"><div class="journey-map" id="journey-map"></div></div>
    <div class="home-map-content">
      <div class="home-heading"><h1>${t('home')}</h1><p>${t('homeLead')}</p></div>
      <form id="home-route-form" class="home-route-composer">
        ${routeComposer({ swap: true })}
        <div class="home-actions">
          <button type="button" class="home-action search-action" data-action="home-search">${icon('search', 23)}<span>${t('findRide')}</span>${icon('arrowRight', 21)}</button>
          <button type="button" class="home-action offer-action" data-action="home-drive">${icon('users', 23)}<span>${t('offerRide')}</span>${icon('arrowRight', 21)}</button>
        </div>
      </form>
      <img class="home-landscape" src="/static/assets/journey-landscape.webp" alt="">
    </div>
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

function composerLocations(routeComposer, icon) {
  return routeComposer().replaceAll('<span class="route-stop-arrow" aria-hidden="true">›</span>', `<span class="route-stop-arrow" aria-hidden="true">${icon('pin', 23)}</span>`);
}

function composerMap(state, t, icon) {
  const values = state.form?.values || {};
  const empty = !values.origin_lat && !values.destination_lat;
  const copy = composerCopy[state.lang] || composerCopy.en;
  return `<div class="journey-map-shell hf-map"><div class="journey-map" id="journey-map"></div>${empty ? `<div class="hf-map-caption">${icon('pin', 16)} ${copy.map}</div>` : ''}</div>`;
}

export function renderSearchForm({ state, t, icon, routeComposer, seatStepper, escAttr }) {
  const copy = composerCopy[state.lang] || composerCopy.en;
  return `<section class="hf-composer hf-search ref-search-form">
    ${composerHeading(state, t, icon)}
    <form id="search-form" class="hf-form" novalidate>
      <div class="hf-route-fields">${composerLocations(routeComposer, icon)}</div>
      <div class="hf-dates hf-date-window">
        <label class="field hf-date"><span>${icon('calendarBlank', 21)} ${copy.from}</span><input type="datetime-local" name="window_start" value="${escAttr(state.form?.values?.window_start || '')}" required></label>
        <label class="field hf-date"><span>${icon('calendarBlank', 21)} ${copy.until}</span><input type="datetime-local" name="window_end" value="${escAttr(state.form?.values?.window_end || '')}" required></label>
      </div>
      ${composerMap(state, t, icon)}
      <label class="hf-passenger-seat">${icon('passenger', 17)}<span>${t('seatsNeeded')}</span><input type="number" name="seats" min="1" max="1" value="1" readonly aria-label="${t('seatsNeeded')}"></label>
      <div class="hf-actions">
        <button class="primary hf-action journey-submit" ${state.busy ? 'disabled' : ''}>${icon('search', 28)}<span><strong>${state.busy ? t('pending') : t('search')}</strong><small>${copy.find}</small></span></button>
        <button type="button" class="hf-action hf-lime" data-action="home-drive">${icon('car', 28)}<span><strong>${t('offerRide')}</strong><small>${copy.offer}</small></span></button>
      </div>
    </form>
  </section>`;
}

export function renderDriveForm({ state, t, icon, routeComposer, seatStepper, escAttr, previewCard }) {
  const copy = composerCopy[state.lang] || composerCopy.en;
  return `<section class="hf-composer hf-drive ref-drive-form">
    ${composerHeading(state, t, icon)}
    <form id="drive-form" class="hf-form" novalidate>
      <div class="hf-route-fields">${composerLocations(routeComposer, icon)}</div>
      <div class="hf-dates">
        <label class="field hf-date"><span>${icon('calendarBlank', 21)} ${copy.departure}</span><input type="datetime-local" name="departure" value="${escAttr(state.form?.values?.departure || '')}" required></label>
      </div>
      ${composerMap(state, t, icon)}
      <div class="hf-driver-options">
        ${seatStepper('seats', 'seats', 3, 1, 6)}
        <label class="field hf-detour"><span>${copy.detour}</span><select name="max_detour_minutes" required><option value="0" ${state.form?.values?.max_detour_minutes === '0' ? 'selected' : ''}>0 ${t('minutes')}</option><option value="5" ${state.form?.values?.max_detour_minutes === '5' ? 'selected' : ''}>5 ${t('minutes')}</option><option value="10" ${!state.form?.values?.max_detour_minutes || state.form?.values?.max_detour_minutes === '10' ? 'selected' : ''}>10 ${t('minutes')}</option><option value="15" ${state.form?.values?.max_detour_minutes === '15' ? 'selected' : ''}>15 ${t('minutes')}</option></select></label>
      </div>
      <div class="hf-actions">
        <button class="primary hf-action journey-submit" ${state.busy ? 'disabled' : ''}>${icon('path', 27)}<span><strong>${state.busy ? t('pending') : t('preview')}</strong><small>${copy.offer}</small></span></button>
        <button type="button" class="hf-action hf-lime" data-action="home-search">${icon('search', 27)}<span><strong>${t('findRide')}</strong><small>${copy.find}</small></span></button>
      </div>
    </form>
  </section>${previewCard(state.preview)}`;
}
