import {AppState, Platform} from 'react-native';
import type {VoiceLanguage} from './parser';
type Speech = typeof import('expo-speech');
let engine: Speech | null | undefined;
function speech(): Speech | null {
  if (engine !== undefined) return engine;
  try {engine = require('expo-speech');} catch {engine = null;}
  return engine || null;
}
const captureStops = new Set<() => Promise<void>>();
const pendingStops = new Set<Promise<void>>();
function trackedStop(stop: () => Promise<void>): Promise<void> {
  let pending: Promise<void>;
  try {pending = stop();} catch (cause) {pending = Promise.reject(cause);}
  pendingStops.add(pending);
  void pending.then(() => pendingStops.delete(pending), () => {cleanupFailed = true; safelyStopped = false; pendingStops.delete(pending);});
  return pending;
}
let epoch = 0, safelyStopped = true, cleanupFailed = false;
export const voiceLocale = (lang: VoiceLanguage) => lang === 'te' ? 'te-IN' : 'en-IN';
const matchesLanguage = (candidate: string, requested: string) => candidate.toLowerCase().replace('_', '-').split('-')[0] === requested.toLowerCase().split('-')[0];
function withTimeout<T>(promise: Promise<T>, ms = 5000): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('VOICE_TIMEOUT')), ms);
    promise.then(value => {clearTimeout(timer); resolve(value);}, error => {clearTimeout(timer); reject(error);});
  });
}
export function registerCaptureStop(stop: () => Promise<void>): () => void {
  captureStops.add(stop);
  return () => {trackedStop(stop); captureStops.delete(stop);};
}
/** Stops playback before the recorder is prepared; does not start any audio. */
export async function stopPlayback(): Promise<void> {++epoch; const module = speech(); if (module) await module.stop();}
export async function stopVoice(): Promise<void> {
  ++epoch;
  const results = await Promise.allSettled([stopPlayback(), ...[...captureStops].map(trackedStop), ...pendingStops]);
  safelyStopped = !cleanupFailed && results.every(result => result.status === 'fulfilled');
}
export async function hasSpokenVoice(lang: VoiceLanguage): Promise<boolean> {
  const module = speech();
  if (!module) return false;
  try {return (await withTimeout(module.getAvailableVoicesAsync())).some(voice => matchesLanguage(voice.language, voiceLocale(lang)));}
  catch {return false;}
}
export async function speakReply(text: string, lang: VoiceLanguage, options: {enabled: boolean; onUnavailable?: () => void}): Promise<boolean> {
  if (!options.enabled || !text.trim() || AppState.currentState !== 'active') return false;
  const stopping = stopVoice(), ticket = epoch;
  await stopping;
  if (ticket !== epoch || AppState.currentState !== 'active') return false;
  const module = speech();
  if (!module || !safelyStopped) {options.onUnavailable?.(); return false;}
  try {
    const locale = voiceLocale(lang), voices = await withTimeout(module.getAvailableVoicesAsync());
    if (ticket !== epoch || AppState.currentState !== 'active') return false;
    const voice = voices.find(value => value.language.toLowerCase() === locale.toLowerCase()) || voices.find(value => matchesLanguage(value.language, locale));
    if (!voice) {options.onUnavailable?.(); return false;}
    return await new Promise<boolean>(resolve => {
      module.speak(text, {language: locale, voice: voice.identifier, rate: 0.95,
        ...(Platform.OS === 'ios' ? {useApplicationAudioSession: false} : {}),
        onDone: () => resolve(true), onStopped: () => resolve(false),
        onError: () => {if (ticket === epoch) options.onUnavailable?.(); resolve(false);},
      });
    });
  } catch {if (ticket === epoch) options.onUnavailable?.(); return false;}
}
AppState.addEventListener('change', state => {if (state === 'background') void stopVoice();});
