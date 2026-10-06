/* Community profile, chat and notification views. App shell owns navigation. */
export function makeCommunity({ state, t, icon, esc, escAttr, api, refresh, render, navigate }) {
  const profile = { value: null, loading: false, loaded: false, failed: false };
  const chats = { value: [], loading: false, loaded: false, failed: false };
  const notifications = { value: [], loading: false, loaded: false, failed: false };
  const conversations = new Map();
  const contactTimers = new Set();
  const profileDraft = {};
  const messageDrafts = new Map();
  const pendingClientIds = new Map();
  const errors = {};
  let mountedRoot = null;
  let mountedView = '';
  let mountedBookingId = '';
  let timer = null;
  let changedWhileEditing = false;
  let generation = 0;
  let sessionGeneration = 0;

  const fmtCount = value => new Intl.NumberFormat(state.lang === 'te' ? 'te-IN' : state.lang === 'hi' ? 'hi-IN' : 'en-IN').format(Number(value) || 0);
  const fmtDate = value => {
    const date = new Date(value || '');
    if (!Number.isFinite(date.getTime())) return '';
    return new Intl.DateTimeFormat(state.lang === 'te' ? 'te-IN' : state.lang === 'hi' ? 'hi-IN' : 'en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' }).format(date);
  };
  const row = id => (state.data?.bookings || []).find(booking => booking.id === id);
  const isParticipant = booking => booking && [booking.driver_id, booking.passenger_id].includes(state.user?.id);
  const activeStatuses = new Set(['published', 'started']);
  const requestError = key => errors[key] ? `<p class="alert error" role="alert">${t(errors[key])}</p>` : '';
  const loadError = (area, retryKey = 'communityRetry') => `<div class="empty-state"><p>${t('communityError')}</p><button type="button" class="secondary" data-community-action="retry">${t(retryKey)}</button></div>`;

  function loadingState() {
    return `<div class="empty-state" role="status">${icon('chatCircleDots', 22)}<span>${t('communityLoading')}</span></div>`;
  }

  function personSummary(person) {
    if (!person || typeof person !== 'object') return '';
    const ratingCount = Number(person.rating_count) || 0;
    const completed = Number(person.completed_trip_count) || 0;
    const rating = ratingCount > 0 && person.rating_average != null && Number.isFinite(Number(person.rating_average))
      ? `<span><b>${Number(person.rating_average).toFixed(1)}</b><small>${t('communityRatingSummary')} · ${fmtCount(ratingCount)}</small></span>`
      : `<span><b>—</b><small>${t('communityNoRatings')}</small></span>`;
    const verificationValue = person.verification;
    const identityVerified = !person.development && verificationValue && typeof verificationValue === 'object'
      && verificationValue.identity === 'verified';
    const impact = person.shared_route_km != null || person.added_distance_m != null
      ? `<div class="panel"><span>${t('communityImpact')}</span>${person.shared_route_km != null && Number.isFinite(Number(person.shared_route_km)) ? `<small>${fmtCount(Number(person.shared_route_km).toFixed(1))} ${t('communityKm')} · ${t('communitySharedDistance')}</small>` : ''}${person.added_distance_m != null && Number.isFinite(Number(person.added_distance_m)) ? `<small>${fmtCount((Number(person.added_distance_m) / 1000).toFixed(1))} ${t('communityKm')} · ${t('communityAddedDistance')}</small>` : ''}</div>`
      : '';
    return `<article class="person-row"><span class="avatar" aria-hidden="true">${icon('user', 26)}</span><div><h2>${esc(person.name || t('unknown'))}</h2><div class="action-row">${person.development ? `<span class="status-tag">${t('communityDevelopment')}</span>` : ''}<span class="status-tag">${t(identityVerified ? 'communityIdentityVerified' : 'communityNotVerified')}</span></div><div class="stats-strip">${rating}<span><b>${fmtCount(completed)}</b><small>${t('communityCompletedTrips')}</small></span></div>${impact}</div></article>`;
  }

  function profilePage() {
    if (!profile.loaded && (profile.loading || !profile.failed)) return `<section class="panel"><header class="page-head"><span>${t('communityProfile')}</span><h1>${t('communityProfile')}</h1></header>${loadingState()}</section>`;
    if (profile.failed && !profile.loaded) return `<section class="panel"><header class="page-head"><span>${t('communityProfile')}</span><h1>${t('communityProfile')}</h1></header>${loadError('profile')}</section>`;
    const current = profile.value || {};
    const name = profileDraft.name ?? current.name ?? '';
    const phone = profileDraft.phone ?? current.phone ?? '';
    const sharePhone = profileDraft.share_phone ?? Boolean(current.share_phone);
    // Local and hosted beta accounts have not completed identity verification.
    const verified = false;
    return `<section class="panel"><header class="page-head"><span>${t('communityProfile')}</span><h1>${t('communityEditProfile')}</h1></header>${requestError('profile')}<form id="community-profile-form" class="form-grid"><label class="field">${t('communityName')}<input name="name" type="text" value="${escAttr(name)}" maxlength="80" autocomplete="name" required></label><label class="field">${t('communityPhone')}<input name="phone" type="tel" value="${escAttr(phone)}" maxlength="20" autocomplete="tel" inputmode="tel"></label><label class="field"><input name="share_phone" type="checkbox" ${sharePhone ? 'checked' : ''}><span><b>${t('communitySharePhone')}</b><small>${t('communitySharePhoneHelp')}</small></span></label><section class="check-state"><span>${icon('lockKey', 20)}</span><div><b>${t('communityVerification')}</b><small>${t(verified ? 'communityIdentityVerified' : 'communityNotVerified')}</small></div></section><button class="primary" type="submit" ${profile.loading ? 'disabled' : ''}>${profile.loading ? t('communityLoading') : t('communitySaveProfile')}</button></form></section>`;
  }

  function chatsPage() {
    if (!chats.loaded && (chats.loading || !chats.failed)) return `<section class="panel"><header class="page-head"><span>${t('communityChats')}</span><h1>${t('communityChats')}</h1></header>${loadingState()}</section>`;
    if (chats.failed && !chats.loaded) return `<section class="panel"><header class="page-head"><span>${t('communityChats')}</span><h1>${t('communityChats')}</h1></header>${loadError('chats')}</section>`;
    return `<section class="panel"><header class="page-head"><span>${t('communityChats')}</span><h1>${t('communityChats')}</h1></header>${requestError('chats')}${chats.value.length ? `<div class="form-grid">${chats.value.map(chat => {
      const person = chat.counterpart_summary;
      const last = chat.latest_message;
      return `<a class="booking-card" href="#/chat/${encodeURIComponent(chat.booking_id)}"><span class="avatar" aria-hidden="true">${icon('user', 24)}</span><span class="person-row"><b>${esc(person?.name || t('unknown'))}</b><small>${last ? esc(last.text) : t('communityNoMessages')}</small></span>${Number(chat.unread_count) > 0 ? `<span class="status-tag pending" aria-label="${fmtCount(chat.unread_count)} ${t('communityUnread')}">${fmtCount(chat.unread_count)}</span>` : ''}${icon('arrowRight', 20)}</a>`;
    }).join('')}</div>` : `<div class="empty-state"><span>${icon('chatCircleDots', 30)}</span><h2>${t('communityNoChats')}</h2></div>`}</section>`;
  }

  function messagesFor(bookingId) {
    return conversations.get(bookingId) || { value: null, loading: false, loaded: false, failed: false, sendAllowed: false };
  }

  function chatPage(bookingId) {
    const conversation = messagesFor(bookingId);
    const booking = row(bookingId);
    const draft = messageDrafts.get(bookingId) || '';
    if (!conversation.loaded && (conversation.loading || !conversation.failed)) return `<section class="panel"><header class="page-head"><a class="back" href="#/chats">${icon('back', 19)}${t('communityChats')}</a><h1>${t('communityChat')}</h1></header>${loadingState()}</section>`;
    if (conversation.failed && !conversation.loaded) return `<section class="panel"><header class="page-head"><a class="back" href="#/chats">${icon('back', 19)}${t('communityChats')}</a><h1>${t('communityChat')}</h1></header>${loadError('chat')}</section>`;
    if (conversation.unavailable || !booking || !isParticipant(booking)) return `<section class="panel"><header class="page-head"><a class="back" href="#/chats">${icon('back', 19)}${t('communityChats')}</a><h1>${t('communityChat')}</h1></header><div class="empty-state">${t('communityChatUnavailable')}</div></section>`;
    if (!conversation.loaded) return `<section class="panel"><header class="page-head"><a class="back" href="#/chats">${icon('back', 19)}${t('communityChats')}</a><h1>${t('communityChat')}</h1></header>${loadError('chat')}</section>`;
    const messages = conversation.value || [];
    const tripStatus = conversation.trip_status || booking.trip_status;
    const sendAllowed = conversation.sendAllowed === true;
    const summary = booking.counterpart_summary || chats.value.find(item => item.booking_id === bookingId)?.counterpart_summary;
    const shareKm = Number(booking.end_m) > Number(booking.start_m) ? (Number(booking.end_m) - Number(booking.start_m)) / 1000 : null;
    const addedM = booking.match?.added_distance_m ?? booking.match?.incremental_distance_m ?? booking.added_distance_m;
    const impactPerson = summary ? {
      ...summary,
      ...(Number.isFinite(shareKm) ? { shared_route_km: shareKm } : {}),
      ...(addedM != null ? { added_distance_m: addedM } : {}),
    } : null;
    return `<section class="panel"><header class="page-head"><a class="back" href="#/chats">${icon('back', 19)}${t('communityChats')}</a><h1>${t('communityChat')}</h1></header>${conversation.failed ? loadError('chat') : ''}${summary ? personSummary(impactPerson) : ''}<div class="action-row" data-community-contact-slot><button class="secondary" type="button" data-community-action="contact" data-id="${escAttr(bookingId)}" ${!activeStatuses.has(tripStatus) || booking.status !== 'accepted' || booking.can_contact !== true ? 'disabled' : ''}>${icon('phone', 19)}${t('communityContact')}</button><small>${t('communityContactHelp')}</small><span data-community-contact-result aria-live="polite"></span></div><section class="panel" aria-label="${t('communityChat')}"><div class="form-grid" aria-live="polite">${messages.length ? messages.map(message => `<article class="booking-card"><b>${esc(message.sender_name || (message.sender_id === state.user?.id ? state.user.name : summary?.name) || t('unknown'))}</b><p>${esc(message.text)}</p><time>${esc(fmtDate(message.created_at))}</time></article>`).join('') : `<div class="empty-state"><span>${icon('chatCircleDots', 28)}</span><p>${t('communityNoMessages')}</p></div>`}</div></section>${requestError('message')}<form id="community-message-form" data-id="${escAttr(bookingId)}" class="action-row"><label class="sr-only" for="community-message-input">${t('communityMessage')}</label><textarea id="community-message-input" name="text" maxlength="1000" rows="2" placeholder="${escAttr(t('communityMessagePlaceholder'))}" ${sendAllowed ? '' : 'disabled'}>${esc(draft)}</textarea><button class="primary" type="submit" ${!sendAllowed || conversation.sending ? 'disabled' : ''}>${conversation.sending ? t('communityLoading') : t('communitySend')} ${icon('arrowRight', 19)}</button></form>${sendAllowed ? '' : `<p class="muted">${t('communityReadOnly')}</p>`}</section>`;
  }

  const notificationText = type => ({
    message: 'communityNotificationChatMessage', chat_message: 'communityNotificationChatMessage',
    booking_accepted: 'communityNotificationRideAccepted', seat_accepted: 'communityNotificationRideAccepted',
    ride_accepted: 'communityNotificationRideAccepted', ride_request: 'communityNotificationRideRequest',
    booking_declined: 'communityNotificationBookingDeclined', booking_cancelled: 'communityNotificationBookingCancelled',
    segment_completed: 'communityNotificationSegmentCompleted', trip_started: 'communityNotificationTripStarted',
    trip_completed: 'communityNotificationTripCompleted', trip_cancelled: 'communityNotificationTripCancelled',
  })[type] || 'communityNotificationBooking';

  function notificationsPage() {
    if (!notifications.loaded && (notifications.loading || !notifications.failed)) return `<section class="panel"><header class="page-head"><span>${t('communityNotifications')}</span><h1>${t('communityNotifications')}</h1></header>${loadingState()}</section>`;
    if (notifications.failed && !notifications.loaded) return `<section class="panel"><header class="page-head"><span>${t('communityNotifications')}</span><h1>${t('communityNotifications')}</h1></header>${loadError('notifications')}</section>`;
    return `<section class="panel"><header class="page-head"><span>${t('communityNotifications')}</span><h1>${t('communityNotifications')}</h1></header>${requestError('notifications')}${notifications.value.length ? `<div class="form-grid">${notifications.value.map(notification => `<article class="booking-card"><span class="avatar">${icon(['message', 'chat_message'].includes(notification.type) ? 'chatCircleDots' : 'bell', 21)}</span><div class="person-row"><b>${t(notificationText(notification.type))}</b><time>${esc(fmtDate(notification.created_at))}</time><a href="#/bookings" data-community-action="open-notification" data-id="${escAttr(notification.id)}" data-booking-id="${escAttr(notification.booking_id)}">${t('communityOpenTrip')}</a></div>${!notification.read_at ? `<button class="text-button" type="button" data-community-action="mark-notification" data-id="${escAttr(notification.id)}">${t('communityMarkRead')}</button>` : ''}</article>`).join('')}</div>` : `<div class="empty-state"><span>${icon('bell', 30)}</span><h2>${t('communityNoNotifications')}</h2></div>`}</section>`;
  }

  async function loadProfile() {
    if (profile.loading) return;
    const owner = sessionGeneration;
    profile.loading = true;
    try {
      const response = await api('/api/profile');
      if (owner !== sessionGeneration) return;
      profile.value = response.profile; profile.loaded = true; profile.failed = false;
    } catch { if (owner === sessionGeneration) profile.failed = true; }
    finally { if (owner === sessionGeneration) profile.loading = false; }
  }

  async function loadChats() {
    if (chats.loading) return;
    const owner = sessionGeneration;
    chats.loading = true;
    try {
      const response = await api('/api/chats');
      if (owner !== sessionGeneration) return;
      chats.value = response.chats || []; chats.loaded = true; chats.failed = false;
    } catch { if (owner === sessionGeneration) chats.failed = true; }
    finally { if (owner === sessionGeneration) chats.loading = false; }
  }

  async function loadNotifications() {
    if (notifications.loading) return;
    const owner = sessionGeneration;
    notifications.loading = true;
    try {
      const response = await api('/api/notifications');
      if (owner !== sessionGeneration) return;
      notifications.value = response.notifications || []; notifications.loaded = true; notifications.failed = false;
    } catch { if (owner === sessionGeneration) notifications.failed = true; }
    finally { if (owner === sessionGeneration) notifications.loading = false; }
  }

  async function loadConversation(bookingId) {
    const conversation = messagesFor(bookingId);
    if (conversation.loading) return;
    const owner = sessionGeneration;
    const ownerView = generation;
    conversation.loading = true;
    conversations.set(bookingId, conversation);
    try {
      const response = await api(`/api/chat?booking_id=${encodeURIComponent(bookingId)}`);
      if (owner !== sessionGeneration) return;
      conversation.value = response.messages || [];
      conversation.sendAllowed = response.can_send === true;
      conversation.booking_status = response.booking_status;
      conversation.trip_status = response.trip_status;
      conversation.loaded = true;
      conversation.failed = false;
      conversations.set(bookingId, conversation);
      const stillOpenAndVisible = ownerView === generation && mountedView === 'chat'
        && mountedBookingId === bookingId && !document.hidden;
      const incomingUnread = stillOpenAndVisible
        ? conversation.value.filter(message => message.sender_id !== state.user?.id && !message.read_at)
        : [];
      if (incomingUnread.length) {
        const lastUnread = incomingUnread[incomingUnread.length - 1];
        try {
          await api('/api/mark_chat_read', 'POST', { booking_id: bookingId, upto_message_id: lastUnread.id });
          if (owner !== sessionGeneration || ownerView !== generation || mountedView !== 'chat' || mountedBookingId !== bookingId) return;
          const readAt = new Date().toISOString();
          for (const message of incomingUnread) message.read_at = readAt;
        } catch { /* Reading is best effort; opening a chat must still work. */ }
      }
    } catch (error) {
      if (owner === sessionGeneration) {
        conversation.sendAllowed = false;
        if ([403, 404, 409].includes(error?.status)) {
          conversation.value = null;
          conversation.loaded = false;
          conversation.failed = false;
          conversation.unavailable = true;
        } else {
          conversation.failed = true;
        }
        conversations.set(bookingId, conversation);
      }
    }
    finally { if (owner === sessionGeneration) conversation.loading = false; }
  }

  function captureDrafts(root = mountedRoot) {
    const profileForm = root?.querySelector('#community-profile-form');
    if (profileForm) {
      const form = new FormData(profileForm);
      profileDraft.name = String(form.get('name') || '');
      profileDraft.phone = String(form.get('phone') || '');
      profileDraft.share_phone = form.has('share_phone');
    }
    const messageForm = root?.querySelector('#community-message-form');
    if (messageForm) messageDrafts.set(messageForm.dataset.id, String(new FormData(messageForm).get('text') || ''));
  }

  function viewSnapshot() {
    if (mountedView === 'profile') return JSON.stringify({ value: profile.value, loaded: profile.loaded, failed: profile.failed });
    if (mountedView === 'chats') return JSON.stringify({ value: chats.value, loaded: chats.loaded, failed: chats.failed });
    if (mountedView === 'notifications') return JSON.stringify({ value: notifications.value, loaded: notifications.loaded, failed: notifications.failed });
    if (mountedView === 'chat') {
      const conversation = messagesFor(mountedBookingId);
      return JSON.stringify({ value: conversation.value, loaded: conversation.loaded, failed: conversation.failed, sendAllowed: conversation.sendAllowed });
    }
    return '';
  }

  async function refreshView({ silent = false, force = false } = {}) {
    if (!state.user) return;
    const currentGeneration = generation;
    const currentSession = sessionGeneration;
    const before = viewSnapshot();
    let shouldLoad = false;
    if (mountedView === 'profile') { shouldLoad = !profile.loading && (force || (!profile.loaded && !profile.failed)); if (shouldLoad) await loadProfile(); }
    else if (mountedView === 'chats') { shouldLoad = !chats.loading && (force || (!chats.loaded && !chats.failed)); if (shouldLoad) await loadChats(); }
    else if (mountedView === 'notifications') { shouldLoad = !notifications.loading && (force || (!notifications.loaded && !notifications.failed)); if (shouldLoad) await loadNotifications(); }
    else if (mountedView === 'chat' && mountedBookingId) { const conversation = messagesFor(mountedBookingId); shouldLoad = !conversation.loading && (force || (!conversation.loaded && !conversation.failed)); if (shouldLoad) await loadConversation(mountedBookingId); }
    if (!shouldLoad || currentGeneration !== generation || currentSession !== sessionGeneration) return;
    const after = viewSnapshot();
    if (silent && before === after) return;
    const active = mountedRoot?.querySelector('input:focus, textarea:focus');
    if (silent && active) changedWhileEditing = true;
    else render?.();
  }

  async function saveProfile(form) {
    const values = new FormData(form);
    const userAtSubmit = state.user?.id;
    const sessionAtSubmit = sessionGeneration;
    const viewAtSubmit = generation;
    const submittedDraft = {
      name: String(values.get('name') || '').trim(),
      phone: String(values.get('phone') || '').trim(),
      share_phone: values.has('share_phone'),
    };
    Object.assign(profileDraft, submittedDraft);
    errors.profile = null;
    profile.loading = true;
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    try {
      const payload = submittedDraft;
      const response = await api('/api/update_profile', 'POST', payload);
      if (sessionAtSubmit !== sessionGeneration || userAtSubmit !== state.user?.id) return;
      profile.value = response.profile;
      profile.loaded = true;
      profile.failed = false;
      if (String(profileDraft.name ?? '').trim() === submittedDraft.name
        && String(profileDraft.phone ?? '').trim() === submittedDraft.phone
        && profileDraft.share_phone === submittedDraft.share_phone) {
        profileDraft.name = undefined;
        profileDraft.phone = undefined;
        profileDraft.share_phone = undefined;
      }
      if (refresh) await refresh();
      profile.loading = false;
      if (viewAtSubmit === generation && mountedView === 'profile') render?.();
    } catch {
      if (sessionAtSubmit === sessionGeneration && userAtSubmit === state.user?.id) {
        profile.loading = false;
        errors.profile = 'communityError';
        if (viewAtSubmit === generation && mountedView === 'profile') render?.();
      }
    } finally { if (sessionAtSubmit === sessionGeneration) profile.loading = false; }
  }

  async function sendMessage(form) {
    const bookingId = form.dataset.id;
    const conversation = messagesFor(bookingId);
    const userAtSubmit = state.user?.id;
    const sessionAtSubmit = sessionGeneration;
    const viewAtSubmit = generation;
    const originalDraft = String(new FormData(form).get('text') || '');
    const text = originalDraft.trim();
    messageDrafts.set(bookingId, originalDraft);
    errors.message = null;
    if (!text || !conversation.sendAllowed || conversation.sending) return;
    const pending = pendingClientIds.get(bookingId);
    const clientMessageId = pending?.text === text ? pending.id : (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    pendingClientIds.set(bookingId, { id: clientMessageId, text });
    conversation.sending = true;
    try {
      const response = await api('/api/send_message', 'POST', { booking_id: bookingId, text, client_message_id: clientMessageId });
      if (sessionAtSubmit !== sessionGeneration || userAtSubmit !== state.user?.id) return;
      conversation.value = [...(conversation.value || []), response.message].filter((message, index, list) => list.findIndex(other => other.id === message.id) === index).slice(-100);
      pendingClientIds.delete(bookingId);
      if (messageDrafts.get(bookingId) === originalDraft) messageDrafts.set(bookingId, '');
      conversation.sending = false;
      if (refresh) await refresh();
      if (viewAtSubmit === generation && mountedView === 'chat' && mountedBookingId === bookingId) render?.();
    } catch {
      // Retain the draft and the idempotency key if the request may have reached the server.
      if (sessionAtSubmit === sessionGeneration && userAtSubmit === state.user?.id) {
        errors.message = 'communitySendFailed';
        conversation.sending = false;
        if (viewAtSubmit === generation && mountedView === 'chat' && mountedBookingId === bookingId) render?.();
      }
    } finally { if (sessionAtSubmit === sessionGeneration) conversation.sending = false; }
  }

  function contactMarkup(contact, bookingId) {
    const phone = contact?.phone ? String(contact.phone).replace(/[^\d+]/g, '') : '';
    if (!/^\+?\d{8,15}$/.test(phone)) return `<span>${t('communityContactUnavailable')}</span>`;
    return `<a class="secondary" data-community-contact-call="${escAttr(bookingId)}" data-issued-at="${Date.now()}" href="tel:${escAttr(phone)}">${icon('phone', 19)}${t('communityCall')} · ${esc(contact.name || '')}</a>`;
  }

  async function revealContact(bookingId, button) {
    const sessionAtClick = sessionGeneration;
    const viewAtClick = generation;
    const result = button?.closest('[data-community-contact-slot]')?.querySelector('[data-community-contact-result]');
    if (button) button.disabled = true;
    try {
      const response = await api('/api/contact', 'POST', { booking_id: bookingId });
      if (sessionAtClick !== sessionGeneration || viewAtClick !== generation || !mountedRoot?.contains(button)) return;
      const currentSlot = button.closest('[data-community-contact-slot]');
      const currentResult = currentSlot?.querySelector('[data-community-contact-result]') || result;
      if (currentResult) currentResult.innerHTML = contactMarkup(response.contact, bookingId);
      button.hidden = true;
      const timeout = setTimeout(() => {
        contactTimers.delete(timeout);
        const link = currentResult?.querySelector('[data-community-contact-call]');
        if (link) link.remove();
        if (button.isConnected) { button.hidden = false; button.disabled = false; }
      }, 15_000);
      contactTimers.add(timeout);
    } catch {
      if (sessionAtClick === sessionGeneration && viewAtClick === generation) {
        const currentSlot = button?.closest('[data-community-contact-slot]');
        const currentResult = currentSlot?.querySelector('[data-community-contact-result]') || result;
        if (currentResult) currentResult.textContent = t('communityContactUnavailable');
        if (button?.isConnected) { button.disabled = false; button.hidden = false; }
      }
    }
  }

  async function markNotificationRead(notificationId) {
    const sessionAtClick = sessionGeneration;
    const viewAtClick = generation;
    errors.notifications = null;
    try {
      const response = await api('/api/mark_notification_read', 'POST', { notification_id: notificationId });
      if (sessionAtClick !== sessionGeneration || viewAtClick !== generation) return;
      const index = notifications.value.findIndex(item => item.id === notificationId);
      if (index >= 0) notifications.value[index] = response.notification || { ...notifications.value[index], read_at: new Date().toISOString() };
      render?.();
    } catch {
      if (sessionAtClick !== sessionGeneration || viewAtClick !== generation) return;
      errors.notifications = 'communityError';
      render?.();
    }
  }

  async function openNotification(notificationId) {
    const sessionAtClick = sessionGeneration;
    const viewAtClick = generation;
    const item = notifications.value.find(notification => notification.id === notificationId);
    if (item && !item.read_at) {
      try {
        const response = await api('/api/mark_notification_read', 'POST', { notification_id: notificationId });
        if (sessionAtClick !== sessionGeneration || viewAtClick !== generation) return;
        const index = notifications.value.findIndex(notification => notification.id === notificationId);
        if (index >= 0) notifications.value[index] = response.notification || { ...item, read_at: new Date().toISOString() };
      } catch {
        if (sessionAtClick !== sessionGeneration || viewAtClick !== generation) return;
        /* Navigation remains available if the read marker cannot be saved. */
      }
    }
    if (sessionAtClick !== sessionGeneration || viewAtClick !== generation) return;
    if (item && ['message', 'chat_message'].includes(item.type) && item.booking_id) navigate?.(`chat/${encodeURIComponent(item.booking_id)}`);
    else navigate?.('bookings');
  }

  function onInput(event) {
    const target = event.target;
    if (target.form?.id === 'community-profile-form') captureDrafts();
    if (target.form?.id === 'community-message-form') captureDrafts();
  }

  async function onSubmit(event) {
    if (event.target.id === 'community-profile-form') {
      event.preventDefault();
      await saveProfile(event.target);
    } else if (event.target.id === 'community-message-form') {
      event.preventDefault();
      await sendMessage(event.target);
    }
  }

  async function onClick(event) {
    const button = event.target.closest('[data-community-action], [data-community-contact]');
    if (!button || !mountedRoot?.contains(button)) return;
    const action = button.dataset.communityAction || (button.hasAttribute('data-community-contact') ? 'contact' : '');
    const id = button.dataset.id || button.dataset.communityContact;
    if (action === 'contact') await revealContact(id, button);
    else if (action === 'mark-notification') await markNotificationRead(id);
    else if (action === 'open-notification') {
      event.preventDefault();
      await openNotification(id);
    } else if (action === 'retry') {
      profile.failed = chats.failed = notifications.failed = false;
      profile.loaded = chats.loaded = notifications.loaded = false;
      if (mountedView === 'chat' && mountedBookingId) messagesFor(mountedBookingId).failed = false;
      if (mountedView === 'chat' && mountedBookingId) messagesFor(mountedBookingId).loaded = false;
      await refreshView({ force: true });
    }
  }

  function onFocusOut() {
    setTimeout(() => {
      if (changedWhileEditing && !mountedRoot?.querySelector('input:focus, textarea:focus')) {
        changedWhileEditing = false;
        render?.();
      }
    }, 0);
  }

  function clearMount() {
    if (timer) clearInterval(timer);
    timer = null;
    if (mountedRoot) {
      mountedRoot.removeEventListener('input', onInput);
      mountedRoot.removeEventListener('submit', onSubmit);
      mountedRoot.removeEventListener('click', onClick);
      mountedRoot.removeEventListener('focusout', onFocusOut);
    }
    mountedRoot = null;
  }

  function clearContactDisclosure() {
    for (const timeout of contactTimers) clearTimeout(timeout);
    contactTimers.clear();
    mountedRoot?.querySelectorAll('[data-community-contact-result]').forEach(result => { result.textContent = ''; });
    mountedRoot?.querySelectorAll('[data-community-contact], [data-community-action="contact"]').forEach(button => { button.hidden = false; button.disabled = false; });
  }

  function unmount() {
    generation += 1;
    clearContactDisclosure();
    clearMount();
  }

  function mount({ root, view, bookingId = '' }) {
    clearMount();
    if (!root || !state.user) return;
    mountedRoot = root;
    mountedView = view;
    mountedBookingId = bookingId;
    root.addEventListener('input', onInput);
    root.addEventListener('submit', onSubmit);
    root.addEventListener('click', onClick);
    root.addEventListener('focusout', onFocusOut);
    const currentGeneration = ++generation;
    refreshView().then(() => { if (generation !== currentGeneration) return; });
    if (['chats', 'chat', 'notifications'].includes(view)) {
      timer = setInterval(() => {
        if (document.hidden || !state.user) return;
        refreshView({ silent: true, force: true });
      }, 20_000);
    }
  }

  function destroy() {
    generation += 1;
    sessionGeneration += 1;
    clearContactDisclosure();
    clearMount();
    profile.value = null; profile.loaded = false; profile.failed = false; profile.loading = false;
    chats.value = []; chats.loaded = false; chats.failed = false; chats.loading = false;
    notifications.value = []; notifications.loaded = false; notifications.failed = false; notifications.loading = false;
    conversations.clear();
    profileDraft.name = undefined;
    profileDraft.phone = undefined;
    profileDraft.share_phone = undefined;
    messageDrafts.clear();
    pendingClientIds.clear();
    for (const key of Object.keys(errors)) delete errors[key];
  }

  return { profilePage, chatsPage, chatPage, notificationsPage, mount, unmount, destroy };
}
