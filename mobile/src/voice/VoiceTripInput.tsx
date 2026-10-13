import React, {useEffect, useRef, useState} from 'react';
import {AppState, Linking, Pressable, StyleSheet, Switch, TextInput, View} from 'react-native';
import {randomUUID} from 'expo-crypto';
import {parseTripTranscript, type VoiceLanguage, type VoiceTripDraft} from './parser';
import {stopVoice, stopPlayback, hasSpokenVoice, registerCaptureStop} from './speech';
import {createLocalCapture, prepareVoiceStorage, recordingAvailable, requestRecordingPermission} from './capture';
import {RecordingSession, type RecordingStatus} from './recordingSession';
import {validVoiceReset, type VoiceOperation, type VoiceCapabilities} from './transport';
import {voiceCopy} from './copy';
import {AppText as Text} from '../NativeTypography';
import type {Api} from '../api';

type Target = 'trip' | 'from' | 'to';
export type VoiceTripInputProps = {
  api: Api;
  lang: VoiceLanguage;
  onDraft: (draft: VoiceTripDraft) => void;
  onFailure?: (message: string) => void;
  onSpokenRepliesChange?: (enabled: boolean) => void;
  onRideChoice?: (index: number, draft: VoiceTripDraft) => void;
};
export function VoiceTripInput({api, lang, onDraft, onFailure, onSpokenRepliesChange, onRideChoice}: VoiceTripInputProps) {
  const copy = voiceCopy(lang), language = lang === 'te' ? 'te' : 'en';
  const inputFont = {fontFamily: lang === 'te' ? 'AnekTelugu500' : 'Manrope500', lineHeight: lang === 'te' ? 25 : 22};
  const [transcript, setTranscript] = useState(''), [fromQuery, setFromQuery] = useState(''), [toQuery, setToQuery] = useState('');
  const [status, setStatus] = useState<RecordingStatus>('idle'), [error, setError] = useState('');
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [capabilities, setCapabilities] = useState<VoiceCapabilities | null>(null), [checking, setChecking] = useState(true);
  const [spoken, setSpoken] = useState(true), [spokenAvailable, setSpokenAvailable] = useState(true);
  const nativeAvailable = recordingAvailable();
  const revision = useRef(0), live = useRef(false), pending = useRef(false);
  const operation = useRef<VoiceOperation | null>(null), session = useRef<RecordingSession | null>(null);
  const failure = useRef(onFailure); failure.current = onFailure;
  const replyChange = useRef(onSpokenRepliesChange); replyChange.current = onSpokenRepliesChange;
  const fail = (message: string) => {if (live.current) {setError(message); failure.current?.(message);}};
  function showError(code: string) {
    if (code === 'VOICE_CANCELLED') return;
    if (code === 'VOICE_DENIED') setPermissionDenied(true);
    if (code === 'VOICE_DAILY_LIMIT') setCapabilities(value => value ? {...value, daily_remaining: 0} : value);
    fail(code === 'VOICE_DAILY_LIMIT' ? copy.dailyLimit : code === 'VOICE_DENIED' ? copy.denied : code === 'VOICE_UNAVAILABLE' ? copy.serverUnavailable : code === 'VOICE_UNSUPPORTED' ? copy.unsupported : code === 'VOICE_BUSY' ? copy.busy : code === 'VOICE_TIMEOUT' ? copy.timeout : code === 'VOICE_NO_SPEECH' ? copy.noSpeech : code === 'VOICE_NETWORK' ? copy.network : copy.failed);
  }
  function cancel(): Promise<void> {
    ++revision.current; pending.current = false;
    const old = operation.current; operation.current = null;
    // Aborts upload immediately; server cancellation is bounded and best effort.
    if (old) void old.cancel();
    if (live.current) {setStatus('idle'); setChecking(false);}
    return session.current?.cancel() || Promise.resolve();
  }
  async function checkSupport() {
    if (pending.current) return;
    pending.current = true; const ticket = ++revision.current;
    if (live.current) {setChecking(true); setError('');}
    const op = api.voiceOperation(randomUUID(), language); operation.current = op;
    try {
      const value = await op.capabilities();
      if (live.current && ticket === revision.current) setCapabilities(value);
    } catch (cause: any) {if (live.current && ticket === revision.current) {setCapabilities(null); showError(cause?.code);}}
    finally {if (ticket === revision.current) {pending.current = false; operation.current = null; if (live.current) setChecking(false);}}
  }
  useEffect(() => {replyChange.current?.(spoken);}, [spoken]);
  useEffect(() => {
    let disposed = false;
    live.current = true; setTranscript(''); setFromQuery(''); setToQuery(''); setCapabilities(null); setError('');
    session.current = new RecordingSession({stopPlayback, permission: requestRecordingPermission, storage: prepareVoiceStorage, create: createLocalCapture,
      onStatus: value => {if (!disposed && live.current) setStatus(value);}, onError: code => {if (!disposed && live.current) {showError(code); pending.current = false; const old = operation.current; operation.current = null; if (old) void old.cancel();}},
    });
    const unregister = registerCaptureStop(cancel);
    void stopPlayback(); void prepareVoiceStorage().catch(() => {if (live.current) fail(copy.failed);});
    void hasSpokenVoice(lang).then(value => {if (!disposed && live.current) setSpokenAvailable(value);});
    void checkSupport();
    const subscription = AppState.addEventListener('change', state => {if (state === 'background') void cancel().catch(() => {});});
    return () => {disposed = true; live.current = false; unregister(); subscription.remove(); void cancel().catch(() => {}); void stopPlayback();};
  }, [lang, api, api.token]);
  async function listen(nextTarget: Target) {
    if (pending.current || status !== 'idle' || !nativeAvailable) return;
    pending.current = true; const ticket = ++revision.current;
    setError(''); setPermissionDenied(false); setStatus('starting');
    const id = randomUUID(), op = api.voiceOperation(id, language); operation.current = op;
    try {
      const support = await op.capabilities();
      if (!live.current || ticket !== revision.current) return;
      setCapabilities(support);
      if (!support.available || !support.languages.includes(language)) throw Object.assign(new Error(), {code: !support.available ? 'VOICE_UNAVAILABLE' : 'VOICE_UNSUPPORTED'});
      if (support.daily_remaining === 0) throw Object.assign(new Error(), {code: 'VOICE_DAILY_LIMIT'});
      await session.current!.start(id, support.max_seconds, async clip => {
        if (!live.current || ticket !== revision.current) return;
        if (clip.size > support.max_bytes) throw Object.assign(new Error(), {code: 'VOICE_INVALID_AUDIO'});
        try {
          const result = await op.transcribe(clip.uri);
          if (!live.current || ticket !== revision.current) return;
          if (nextTarget === 'from') setFromQuery(result.text);
          else if (nextTarget === 'to') setToQuery(result.text);
          else {setTranscript(result.text); setFromQuery(''); setToQuery('');}
        } catch (cause: any) {
          if (live.current && ticket === revision.current && cause?.code === 'VOICE_DAILY_LIMIT' && validVoiceReset(cause.reset_at)) {
            setCapabilities(value => value ? {...value, daily_remaining: 0, reset_at: cause.reset_at} : value);
          }
          throw cause;
        } finally {
          // Also asks the owner-scoped server to clear any work after timeout/error.
          void op.cancel();
          if (ticket === revision.current) {pending.current = false; operation.current = null;}
        }
      });
      // Permission/preparation failures return without a running recording.
      if (ticket === revision.current) pending.current = false;
    } catch (cause: any) {
      if (live.current && ticket === revision.current) {showError(cause?.code); await cancel();}
    }
  }
  function finish() {void session.current?.finish().catch(() => fail(copy.failed));}
  function review() {
    if (!transcript.trim() && !fromQuery.trim() && !toQuery.trim()) {fail(copy.empty); return;}
    void cancel().catch(() => {});
    const draft = parseTripTranscript(transcript);
    if (fromQuery.trim()) draft.fromQuery = fromQuery.trim();
    if (toQuery.trim()) draft.toQuery = toQuery.trim();
    draft.missing = draft.missing.filter(field => !(field === 'from' && draft.fromQuery) && !(field === 'to' && draft.toQuery));
    if (draft.rideOrdinal && onRideChoice && !draft.fromQuery && !draft.toQuery) onRideChoice(draft.rideOrdinal - 1, draft);
    else onDraft(draft);
  }
  const busy = status !== 'idle';
  const quotaReached = capabilities?.daily_remaining === 0;
  const quotaReset = quotaReached && capabilities && validVoiceReset(capabilities.reset_at) ? copy.quotaReset.replace('{reset}', capabilities.reset_at.slice(0, 16).replace('T', ' ')) : '';
  const disabled = quotaReached || busy || checking || !nativeAvailable || !capabilities?.available || !capabilities.languages.includes(language);
  return <View style={styles.card}>
    <Text style={styles.title}>{copy.title}</Text>
    <Text style={styles.body}>{copy.hint}</Text>
    <Text style={styles.note}>{copy.privacy}</Text>
    {lang === 'hi' && <Text style={styles.note}>{copy.englishFallback}</Text>}
    <Text accessibilityLiveRegion="polite" style={styles.note}>{checking ? copy.checking : !nativeAvailable ? copy.unavailable : !capabilities?.available ? copy.serverUnavailable : !capabilities.languages.includes(language) ? copy.unsupported : quotaReached ? copy.dailyLimit : ''}</Text>
    {!!quotaReset && <Text style={styles.note}>{quotaReset}</Text>}
    {busy ? <View style={styles.row}>
      <Text accessibilityLiveRegion="polite" style={styles.body}>{status === 'starting' ? copy.starting : status === 'finishing' ? copy.stopping : copy.listening}</Text>
      {status === 'recording' && <Action label={copy.stop} onPress={finish} />}
      <Action label={copy.cancel} onPress={cancel} />
    </View> : <Action label={copy.listen} onPress={() => void listen('trip')} disabled={disabled} primary />}
    {!busy && !checking && <Action label={copy.retry} onPress={() => void checkSupport()} />}
    <Text style={styles.label}>{copy.transcript}</Text>
    <TextInput accessibilityLabel={copy.transcript} style={[styles.input, styles.transcript, inputFont]} multiline maxLength={1000} value={transcript} onChangeText={value => {setTranscript(value); setFromQuery(''); setToQuery('');}} editable={!busy} placeholder={copy.transcriptHint} placeholderTextColor="#64748b" />
    <Text style={styles.label}>{copy.guided}</Text>
    <Text style={styles.note}>{copy.guidedHint}</Text>
    <TextInput accessibilityLabel={copy.from} placeholder={copy.from} placeholderTextColor="#64748b" style={[styles.input, inputFont]} maxLength={200} value={fromQuery} onChangeText={setFromQuery} editable={!busy} />
    <Action label={copy.fromVoice} onPress={() => void listen('from')} disabled={disabled} />
    <TextInput accessibilityLabel={copy.to} placeholder={copy.to} placeholderTextColor="#64748b" style={[styles.input, inputFont]} maxLength={200} value={toQuery} onChangeText={setToQuery} editable={!busy} />
    <Action label={copy.toVoice} onPress={() => void listen('to')} disabled={disabled} />
    {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
    {permissionDenied && <Action label={copy.settings} onPress={() => {void Linking.openSettings().catch(() => fail(copy.failed));}} />}
    <View style={styles.row}><Text style={styles.body}>{copy.reply}</Text><Switch accessibilityLabel={copy.reply} value={spoken} onValueChange={value => {setSpoken(value); if (!value) void stopVoice();}} /></View>
    {!spokenAvailable && <Text style={styles.note}>{copy.noVoice}</Text>}
    <Text style={styles.note}>{copy.reviewNote}</Text>
    <Action label={copy.review} onPress={review} disabled={busy} primary />
  </View>;
}
function Action({label, onPress, disabled = false, primary = false}: {label: string; onPress: () => void; disabled?: boolean; primary?: boolean}) {
  return <Pressable accessibilityRole="button" accessibilityState={{disabled}} disabled={disabled} onPress={onPress} style={[styles.button, primary && styles.primary, disabled && styles.disabled]}><Text style={[styles.buttonText, primary && styles.primaryText]}>{label}</Text></Pressable>;
}
const styles = StyleSheet.create({
  card: {gap: 12, padding: 16, backgroundColor: '#ffffff', borderRadius: 16}, title: {fontSize: 23, fontWeight: '700', color: '#14251f'},
  body: {fontSize: 16, lineHeight: 24, color: '#233c34', flexShrink: 1}, note: {fontSize: 13, lineHeight: 20, color: '#54655f'},
  label: {fontSize: 15, lineHeight: 23, fontWeight: '600', color: '#233c34'}, row: {flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: 12},
  input: {borderWidth: 1, borderColor: '#b7c7c0', borderRadius: 10, padding: 12, fontSize: 16, color: '#14251f', minHeight: 48},
  transcript: {minHeight: 96, textAlignVertical: 'top'}, button: {minHeight: 48, paddingHorizontal: 16, paddingVertical: 12, borderRadius: 12, backgroundColor: '#edf3ef', justifyContent: 'center', alignItems: 'center'},
  buttonText: {fontSize: 15, fontWeight: '600', color: '#174b38', textAlign: 'center'}, primary: {backgroundColor: '#175c42'}, primaryText: {color: '#fff'}, disabled: {opacity: 0.45}, error: {fontSize: 14, lineHeight: 22, color: '#a32727'},
});
