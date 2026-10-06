import React, {useCallback, useEffect, useRef, useState} from 'react';
import {ActivityIndicator, AppState, Pressable, ScrollView, StyleSheet, TextInput, View} from 'react-native';
import * as Crypto from 'expo-crypto';
import {Api} from './api';
import {AppText} from './NativeTypography';
import {Icon} from './Icon';

type CommunityScreen = 'profile' | 'chats' | 'chat' | 'notifications';
type Summary = {id: string; name: string; development?: boolean; verification?: unknown; rating_average?: number | null; rating_count?: number; completed_trip_count?: number};
type Props = {
  api: Api;
  screen: CommunityScreen;
  lang: string;
  t: (key: string) => string;
  user: any;
  bookingId?: string;
  onBack: () => void;
  onOpenChat: (bookingId: string) => void;
  onOpenBooking: (bookingId: string) => void;
  onUserUpdate: (user: any) => void;
  onError: (error: unknown) => void;
};
type CommunityProfile = {id: string; name: string; phone: string | null; share_phone: boolean; verification?: unknown};
type ChatMessage = {id: string; booking_id: string; sender_id: string; sender_name: string; text: string; client_message_id: string; created_at: string; read_at: string | null};

const COLORS = {ink: '#153C32', muted: '#71857B', ivory: '#F5F4EC', white: '#FFFFFF', line: '#E4E8DD', pale: '#E7EDE2', citron: '#D8ED79'};

export function CommunityScreens(props: Props) {
  const {api, screen, lang, t, user, bookingId, onBack, onOpenChat, onOpenBooking, onUserUpdate, onError} = props;
  const [profile, setProfile] = useState<CommunityProfile | null>(null);
  const profileLoaded = useRef(false);
  const threadRef = useRef<ScrollView>(null);
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [sharePhone, setSharePhone] = useState(false);
  const [chats, setChats] = useState<any[]>([]);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [chat, setChat] = useState<any>(null);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sending, setSending] = useState(false);
  const [localError, setLocalError] = useState('');
  const mounted = useRef(true);
  const messageKey = useRef<{text: string; id: string} | null>(null);
  const langTag = lang === 'te' ? 'te-IN' : lang === 'hi' ? 'hi-IN' : 'en-IN';

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const current = useCallback((capturedToken: string | null, actorId: string, alive: boolean) =>
    alive && mounted.current && api.token === capturedToken && user?.id === actorId, [api, user?.id]);

  const loadProfile = useCallback(async (alive = true) => {
    const token = api.token;
    const actorId = String(user?.id || '');
    setLoading(true);
    setLocalError('');
    try {
      const result = await api.request('/api/profile');
      if (!current(token, actorId, alive)) return;
      const next: CommunityProfile = result.profile;
      setProfile(next);
      if (!profileLoaded.current) {
        setName(next?.name || '');
        setPhone(next?.phone || '');
        setSharePhone(Boolean(next?.share_phone));
        profileLoaded.current = true;
      }
    } catch (error) {
      if (current(token, actorId, alive)) { setLocalError(t('communityError')); if ((error as any)?.status === 401) onError(error); }
    } finally {
      if (current(token, actorId, alive)) setLoading(false);
    }
  }, [api, current, onError, t, user?.id]);

  const loadChats = useCallback(async (alive = true) => {
    const token = api.token;
    const actorId = String(user?.id || '');
    setLoading(true);
    setLocalError('');
    try {
      const result = await api.request('/api/chats');
      if (current(token, actorId, alive)) setChats(Array.isArray(result.chats) ? result.chats : []);
    } catch (error) {
      if (current(token, actorId, alive)) { setLocalError(t('communityError')); if ((error as any)?.status === 401) onError(error); }
    } finally { if (current(token, actorId, alive)) setLoading(false); }
  }, [api, current, onError, t, user?.id]);

  const loadNotifications = useCallback(async (alive = true) => {
    const token = api.token;
    const actorId = String(user?.id || '');
    setLoading(true);
    setLocalError('');
    try {
      const result = await api.request('/api/notifications');
      if (current(token, actorId, alive)) setNotifications(Array.isArray(result.notifications) ? result.notifications : []);
    } catch (error) {
      if (current(token, actorId, alive)) { setLocalError(t('communityError')); if ((error as any)?.status === 401) onError(error); }
    } finally { if (current(token, actorId, alive)) setLoading(false); }
  }, [api, current, onError, t, user?.id]);

  const loadChat = useCallback(async (id: string, alive = true) => {
    const token = api.token;
    const actorId = String(user?.id || '');
    setLoading(true);
    setLocalError('');
    try {
      const result = await api.request(`/api/chat?booking_id=${encodeURIComponent(id)}`);
      if (!current(token, actorId, alive) || AppState.currentState !== 'active') return;
      setChat(result);
      const messages: ChatMessage[] = Array.isArray(result.messages) ? result.messages : [];
      const lastIncoming = [...messages].reverse().find(message => message.sender_id !== actorId);
      if (lastIncoming?.id) {
        try { await api.action('mark_chat_read', {booking_id: id, upto_message_id: lastIncoming.id}); }
        catch (error) { if (current(token, actorId, alive) && (error as any)?.status === 401) onError(error); }
      }
    } catch (error) {
      if (current(token, actorId, alive) && AppState.currentState === 'active') { setLocalError(t('communityChatUnavailable')); if ((error as any)?.status === 401) onError(error); }
    } finally { if (current(token, actorId, alive)) setLoading(false); }
  }, [api, current, onError, t, user?.id]);

  useEffect(() => {
    let alive = true;
    setLocalError('');
    if (screen === 'profile') void loadProfile(alive);
    if (screen === 'chats') void loadChats(alive);
    if (screen === 'notifications') void loadNotifications(alive);
    if (screen === 'chat' && bookingId) {
      void loadChat(bookingId, alive);
      let timer: ReturnType<typeof setInterval> | undefined;
      const startPolling = () => {
        if (timer) clearInterval(timer);
        timer = undefined;
        if (AppState.currentState === 'active') timer = setInterval(() => { if (alive) void loadChat(bookingId, alive); }, 8000);
      };
      startPolling();
      const subscription = AppState.addEventListener('change', state => {
        if (state === 'active') { void loadChat(bookingId, alive); startPolling(); }
        else if (timer) { clearInterval(timer); timer = undefined; }
      });
      return () => { alive = false; if (timer) clearInterval(timer); subscription.remove(); };
    }
    return () => { alive = false; };
  }, [screen, bookingId, loadProfile, loadChats, loadChat, loadNotifications]);

  const saveProfile = async () => {
    const cleanName = name.trim();
    if (!cleanName) { setLocalError(t('communityNameRequired')); return; }
    let normalizedPhone: string | undefined;
    const phoneWasEdited = (profile?.phone || '') !== phone.trim();
    if (phone.trim()) {
      const digits = phone.replace(/[^0-9]/g, '');
      const localNumber = digits.length === 12 && digits.startsWith('91') ? digits.slice(2) : digits;
      if (/^[6-9][0-9]{9}$/.test(localNumber)) normalizedPhone = `+91${localNumber}`;
      else { setLocalError(t('communityPhoneInvalid')); return; }
    } else if (sharePhone) {
      setLocalError(t('communityPhoneInvalid'));
      return;
    } else if (phoneWasEdited) {
      normalizedPhone = '';
    }
    const token = api.token;
    const actorId = String(user?.id || '');
    setSaving(true);
    setLocalError('');
    try {
      const result = await api.action('update_profile', {name: cleanName, share_phone: sharePhone, ...(phoneWasEdited ? {phone: normalizedPhone} : {})});
      if (!current(token, actorId, true)) return;
      const next = result.profile as CommunityProfile;
      setProfile(next);
      profileLoaded.current = true;
      setName(next.name || '');
      setPhone(next.phone || '');
      setSharePhone(Boolean(next.share_phone));
      if (result.user) onUserUpdate(result.user);
      setLocalError(t('communityProfileSaved'));
    } catch (error) {
      setLocalError(t('communitySaveFailed'));
      if ((error as any)?.status === 401) onError(error);
    } finally { if (current(token, actorId, true)) setSaving(false); }
  };

  const sendMessage = async () => {
    if (!bookingId || !chat?.can_send || !draft.trim() || sending) return;
    const text = draft.trim().slice(0, 1000);
    if (!messageKey.current || messageKey.current.text !== text) messageKey.current = {text, id: Crypto.randomUUID()};
    const clientMessageId = messageKey.current.id;
    const token = api.token;
    const actorId = String(user?.id || '');
    setSending(true);
    setLocalError('');
    try {
      await api.action('send_message', {booking_id: bookingId, text, client_message_id: clientMessageId});
      if (!current(token, actorId, true)) return;
      if (draft.trim().slice(0, 1000) === text) {
        setDraft('');
        if (messageKey.current?.id === clientMessageId) messageKey.current = null;
      }
      await loadChat(bookingId);
    } catch (error) {
      if (current(token, actorId, true)) { setLocalError(t('communitySendFailed')); if ((error as any)?.status === 401) onError(error); }
    } finally { if (current(token, actorId, true)) setSending(false); }
  };

  const openNotification = async (notification: any) => {
    const token = api.token;
    const actorId = String(user?.id || '');
    try {
      await api.action('mark_notification_read', {notification_id: notification.id});
      if (!current(token, actorId, true) || AppState.currentState !== 'active') return;
      if (notification.booking_id) {
        if (notification.type === 'chat_message') onOpenChat(notification.booking_id);
        else onOpenBooking(notification.booking_id);
      } else void loadNotifications();
    } catch (error) { if ((error as any)?.status === 401) onError(error); else setLocalError(t('communityError')); }
  };

  const header = (title: string) => <View style={styles.header}>
    <Pressable accessibilityRole="button" accessibilityLabel={t('back')} onPress={onBack} style={styles.back}><Icon name="arrowLeft" size={21} color={COLORS.ink}/></Pressable>
    <AppText style={styles.title}>{title}</AppText>
    <View style={styles.headerTail}/>
  </View>;
  const card = (children: React.ReactNode) => <View style={styles.card}>{children}</View>;
  const date = (value?: string) => value ? new Date(value).toLocaleString(langTag, {timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short'}) : '';

  if (screen === 'profile') return <View style={styles.screen}>{header(t('communityProfile'))}<ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
    {card(<>
      {loading && !profile ? <ActivityIndicator color={COLORS.ink}/> : !profile ? <AppText style={styles.empty}>{localError || t('communityEmptyProfile')}</AppText> : <>
        <AppText style={styles.label}>{t('communityName')}</AppText>
        <TextInput accessibilityLabel={t('communityName')} value={name} onChangeText={setName} maxLength={80} autoCapitalize="words" placeholder={t('communityName')} placeholderTextColor={COLORS.muted} style={[styles.input, {fontFamily: lang === 'te' ? 'AnekTelugu400' : 'Manrope400', lineHeight: lang === 'te' ? 24 : undefined}]}/>
        <AppText style={styles.label}>{t('communityPhone')}</AppText>
        <TextInput accessibilityLabel={t('communityPhone')} value={phone} onChangeText={setPhone} maxLength={18} keyboardType="phone-pad" placeholder="+91" placeholderTextColor={COLORS.muted} style={[styles.input, {fontFamily: 'Manrope400'}]}/>
        <Pressable accessibilityRole="checkbox" accessibilityState={{checked: sharePhone}} onPress={() => setSharePhone(value => !value)} style={styles.consentRow}>
          <View style={[styles.check, sharePhone && styles.checkActive]}>{sharePhone ? <Icon name="checkCircle" size={16} color={COLORS.white}/> : null}</View>
          <AppText style={styles.consentText}>{t('communitySharePhone')}</AppText>
        </Pressable>
        <AppText style={styles.helper}>{t('communitySharePhoneHelp')}</AppText>
        <Pressable accessibilityRole="button" disabled={saving || loading} onPress={() => void saveProfile()} style={[styles.primary, (saving || loading) && styles.disabled]}>
          <AppText style={styles.primaryText}>{saving ? t('communitySaving') : t('communitySaveProfile')}</AppText>
        </Pressable>
      </>}
    </>)}
    {localError ? <AppText accessibilityRole="alert" style={styles.message}>{localError}</AppText> : null}
    {localError && !profile ? <Pressable accessibilityRole="button" onPress={() => void loadProfile()} style={styles.retry}><AppText style={styles.retryText}>{t('communityRetry')}</AppText></Pressable> : null}
  </ScrollView></View>;

  if (screen === 'chats') return <View style={styles.screen}>{header(t('communityChats'))}<ScrollView contentContainerStyle={styles.body}>
    {loading && chats.length === 0 ? <ActivityIndicator color={COLORS.ink}/> : chats.length === 0 ? card(<AppText style={styles.empty}>{t('communityNoChats')}</AppText>) : chats.map((item: any) => <Pressable key={item.booking_id} onPress={() => onOpenChat(item.booking_id)} style={styles.chatRow}>
      <View style={styles.avatar}><Icon name="user" size={21} color={COLORS.ink}/></View>
      <View style={styles.chatSummary}><AppText style={styles.rowTitle}>{item.counterpart_summary?.name || t('communityChat')}</AppText><AppText numberOfLines={1} style={styles.preview}>{item.latest_message?.text || t('communityNoMessages')}</AppText></View>
      <View style={styles.rowEnd}>{item.unread_count > 0 ? <View style={styles.badge}><AppText style={styles.badgeText}>{item.unread_count}</AppText></View> : null}<AppText style={styles.date}>{date(item.latest_message?.created_at)}</AppText></View>
    </Pressable>)}
    {localError ? <AppText accessibilityRole="alert" style={styles.message}>{localError}</AppText> : null}
    {localError ? <Pressable accessibilityRole="button" onPress={() => void loadChats()} style={styles.retry}><AppText style={styles.retryText}>{t('communityRetry')}</AppText></Pressable> : null}
  </ScrollView></View>;

  if (screen === 'notifications') return <View style={styles.screen}>{header(t('communityNotifications'))}<ScrollView contentContainerStyle={styles.body}>
    {loading && notifications.length === 0 ? <ActivityIndicator color={COLORS.ink}/> : notifications.length === 0 ? card(<AppText style={styles.empty}>{t('communityNoNotifications')}</AppText>) : notifications.map((item: any) => <Pressable key={item.id} onPress={() => void openNotification(item)} style={[styles.notificationRow, !item.read_at && styles.unread]}>
      <View style={styles.notificationIcon}><Icon name={item.type === 'chat_message' ? 'chatCircleDots' : 'calendarBlank'} size={20} color={COLORS.ink}/></View>
      <View style={styles.chatSummary}><AppText style={styles.rowTitle}>{t(notificationKey(item.type))}</AppText><AppText style={styles.date}>{date(item.created_at)}</AppText></View>
      {!item.read_at ? <View style={styles.unreadDot}/> : null}
    </Pressable>)}
    {localError ? <AppText accessibilityRole="alert" style={styles.message}>{localError}</AppText> : null}
    {localError ? <Pressable accessibilityRole="button" onPress={() => void loadNotifications()} style={styles.retry}><AppText style={styles.retryText}>{t('communityRetry')}</AppText></Pressable> : null}
  </ScrollView></View>;

  return <View style={styles.screen}>{header(t('communityChat'))}
    <ScrollView ref={threadRef} onContentSizeChange={() => threadRef.current?.scrollToEnd({animated: true})} contentContainerStyle={styles.thread}>
      {chat?.messages?.map((message: ChatMessage) => <View key={message.id} style={[styles.bubble, message.sender_id === user?.id ? styles.ownBubble : styles.otherBubble]}>
        {message.sender_id !== user?.id ? <AppText style={styles.sender}>{message.sender_name}</AppText> : null}
        <AppText style={styles.messageText}>{message.text}</AppText>
        <AppText style={styles.date}>{date(message.created_at)}</AppText>
      </View>)}
      {loading && !chat ? <ActivityIndicator color={COLORS.ink}/> : null}{!chat?.messages?.length && !localError && !loading ? <AppText style={styles.empty}>{t('communityNoMessages')}</AppText> : null}
      {localError ? <AppText accessibilityRole="alert" style={styles.message}>{localError}</AppText> : null}
      {localError ? <Pressable accessibilityRole="button" onPress={() => bookingId && void loadChat(bookingId)} style={styles.retry}><AppText style={styles.retryText}>{t('communityRetry')}</AppText></Pressable> : null}
    </ScrollView>
    {chat?.can_send ? <View style={styles.composer}>
      <TextInput accessibilityLabel={t('communityMessage')} value={draft} onChangeText={setDraft} editable={!sending} multiline maxLength={1000} placeholder={t('communityMessagePlaceholder')} placeholderTextColor={COLORS.muted} style={[styles.composerInput, {fontFamily: lang === 'te' ? 'AnekTelugu400' : 'Manrope400', lineHeight: lang === 'te' ? 24 : undefined}]}/>
      <Pressable accessibilityRole="button" accessibilityLabel={t('communitySend')} disabled={!draft.trim() || sending} onPress={() => void sendMessage()} style={[styles.send, (!draft.trim() || sending) && styles.disabled]}><Icon name="navigationArrow" size={19} color={COLORS.white}/></Pressable>
    </View> : <View style={styles.readOnly}><Icon name="lockKey" size={17} color={COLORS.muted}/><AppText style={styles.readOnlyText}>{t('communityReadOnly')}</AppText></View>}
  </View>;
}

function notificationKey(value: string): string {
  const values: Record<string, string> = {
    ride_request: 'communityNotificationRideRequest',
    ride_accepted: 'communityNotificationRideAccepted',
    booking_declined: 'communityNotificationBookingDeclined',
    booking_cancelled: 'communityNotificationBookingCancelled',
    segment_completed: 'communityNotificationSegmentCompleted',
    trip_started: 'communityNotificationTripStarted',
    trip_completed: 'communityNotificationTripCompleted',
    trip_cancelled: 'communityNotificationTripCancelled',
    chat_message: 'communityNotificationChatMessage',
  };
  return values[value] || 'communityNotificationGeneric';
}

const styles = StyleSheet.create({
  screen: {flex:  1, backgroundColor: COLORS.ivory},
  header: {minHeight: 58, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: COLORS.line},
  back: {width: 42, height: 42, alignItems: 'center', justifyContent: 'center'}, title: {fontSize: 18, fontWeight: '700', color: COLORS.ink}, headerTail: {width: 42},
  body: {padding: 18, paddingBottom: 32, gap: 12}, card: {padding: 18, backgroundColor: COLORS.white, borderRadius: 20, gap: 13},
  label: {fontSize: 14, fontWeight: '700', color: COLORS.ink}, input: {minHeight: 50, paddingHorizontal: 14, borderRadius: 14, backgroundColor: COLORS.ivory, color: COLORS.ink, fontSize: 16},
  consentRow: {minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: 12}, check: {width: 23, height: 23, borderWidth: 1, borderColor: COLORS.muted, borderRadius: 6, alignItems: 'center', justifyContent: 'center'}, checkActive: {backgroundColor: COLORS.ink, borderColor: COLORS.ink}, consentText: {flex: 1, color: COLORS.ink, fontSize: 14, lineHeight: 21}, helper: {color: COLORS.muted, fontSize: 13, lineHeight: 19},
  primary: {minHeight: 50, borderRadius: 16, backgroundColor: COLORS.ink, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16}, primaryText: {fontSize: 15, fontWeight: '700', color: COLORS.white}, disabled: {opacity: 0.5}, message: {paddingHorizontal: 4, color: COLORS.ink, fontSize: 14, lineHeight: 21}, empty: {paddingVertical: 14, color: COLORS.muted, fontSize: 15, lineHeight: 23, textAlign: 'center'},
  chatRow: {minHeight: 82, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 14, borderRadius: 18, backgroundColor: COLORS.white}, avatar: {width: 42, height: 42, borderRadius: 21, backgroundColor: COLORS.pale, alignItems: 'center', justifyContent: 'center'}, chatSummary: {flex: 1, gap: 5}, rowTitle: {fontSize: 15, fontWeight: '700', color: COLORS.ink}, preview: {fontSize: 13, color: COLORS.muted}, rowEnd: {alignItems: 'flex-end', gap: 6}, badge: {minWidth: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 5, backgroundColor: COLORS.citron}, badgeText: {fontSize: 12, fontWeight: '700', color: COLORS.ink}, date: {fontSize: 11, color: COLORS.muted},
  notificationRow: {minHeight: 74, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, borderRadius: 17, backgroundColor: COLORS.white}, unread: {backgroundColor: '#F0F3E8'}, notificationIcon: {width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.pale}, unreadDot: {width: 9, height: 9, borderRadius: 5, backgroundColor: COLORS.ink},
  thread: {padding: 16, gap: 10, flexGrow: 1, justifyContent: 'flex-end'}, bubble: {maxWidth: '88%', paddingHorizontal: 14, paddingVertical: 10, borderRadius: 17, gap: 5}, ownBubble: {alignSelf: 'flex-end', backgroundColor: '#DDE8D8', borderBottomRightRadius: 5}, otherBubble: {alignSelf: 'flex-start', backgroundColor: COLORS.white, borderBottomLeftRadius: 5}, sender: {fontSize: 12, fontWeight: '700', color: COLORS.ink}, messageText: {fontSize: 15, lineHeight: 22, color: COLORS.ink}, composer: {flexDirection: 'row', alignItems: 'flex-end', gap: 9, padding: 12, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: COLORS.line, backgroundColor: COLORS.white}, composerInput: {flex: 1, minHeight: 45, maxHeight: 120, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 16, backgroundColor: COLORS.ivory, color: COLORS.ink, fontSize: 15, lineHeight: 21}, send: {width: 45, height: 45, borderRadius: 23, backgroundColor: COLORS.ink, alignItems: 'center', justifyContent: 'center'}, retry: {minHeight: 46, borderRadius: 15, backgroundColor: COLORS.ink, alignItems: 'center', justifyContent: 'center'}, retryText: {color: COLORS.white, fontSize: 15, fontWeight: '700'},
  readOnly: {minHeight: 54, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9, paddingHorizontal: 18, backgroundColor: COLORS.white}, readOnlyText: {color: COLORS.muted, fontSize: 13, lineHeight: 20},
});
