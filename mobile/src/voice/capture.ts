import {Platform} from 'react-native';
import type {AudioRecorder, RecordingOptions} from 'expo-audio';

type Audio = typeof import('expo-audio');
type Files = typeof import('expo-file-system');
let audioModule: Audio | null | undefined;
function audio(): Audio | null {
  if (audioModule !== undefined) return audioModule;
  try {audioModule = require('expo-audio');} catch {audioModule = null;}
  return audioModule || null;
}
function files(): Files {return require('expo-file-system');}
const activeFiles = new Set<string>();
// Native audio ownership survives React component/session replacement.
let nativeLeaseTail: Promise<void> = Promise.resolve();
function acquireNativeLease() {
  const previous = nativeLeaseTail;
  let release!: () => void, reject!: (cause: unknown) => void;
  const held = new Promise<void>((resolve, fail) => {release = resolve; reject = fail;});
  void held.catch(() => {});
  nativeLeaseTail = previous.then(() => held);
  // A failed native release fails subsequent acquisition closed, without an unhandled rejection.
  void nativeLeaseTail.catch(() => {});
  return {ready: previous, release, reject};
}
const temporaryName = /^recording-[a-f\d-]+\.route-share-voice\.m4a$/i;
const readyName = /^route-share-voice-[a-f\d-]+\.m4a$/i;
const error = (code: string) => Object.assign(new Error(code), {code});
let startupCleanup: Promise<void> | undefined;

/** Deletes only this feature's marked recordings, never another feature's cache. */
export async function cleanupVoiceFiles(): Promise<void> {
  const {Directory, File, Paths} = files();
  for (const [directory, pattern] of [[new Directory(Paths.cache, 'Audio'), temporaryName], [new Directory(Paths.cache, 'ExpoAudio'), temporaryName], [new Directory(Paths.cache, 'route-share-voice'), readyName]] as const) {
    if (!directory.exists) continue;
    for (const item of directory.list()) {
      if (item instanceof File && pattern.test(item.name) && !activeFiles.has(item.uri)) item.delete();
    }
  }
}
export function prepareVoiceStorage(): Promise<void> {
  if (!startupCleanup) startupCleanup = cleanupVoiceFiles().catch(cause => {startupCleanup = undefined; throw cause;});
  return startupCleanup;
}
export function recordingAvailable(): boolean {return audio() !== null && (Platform.OS === 'ios' || Platform.OS === 'android');}
export async function requestRecordingPermission(): Promise<boolean> {
  const module = audio();
  if (!module) throw error('VOICE_UNAVAILABLE');
  return (await module.requestRecordingPermissionsAsync()).granted;
}
export type CapturedAudio = {uri: string; size: number};
export type LocalCapture = {
  prepare(): Promise<void>;
  start(seconds: number): void;
  finish(requestId: string): Promise<CapturedAudio>;
  dispose(): Promise<void>;
};
export function createLocalCapture(onFinished: (failed: boolean) => void): LocalCapture {
  const module = audio();
  if (!module) throw error('VOICE_UNAVAILABLE');
  const options: RecordingOptions = {
    ...module.RecordingPresets.HIGH_QUALITY,
    // Both native recorders generate their own name. A feature-specific suffix
    // identifies unfinished recordings after process death without deleting other audio.
    extension: '.route-share-voice.m4a', numberOfChannels: 1, sampleRate: 44100, bitRate: 64000,
    android: {outputFormat: 'mpeg4', audioEncoder: 'aac', maxFileSize: 2_097_152},
  };
  const {ios, android, web: _web, ...common} = options;
  // Same platform normalization as Expo's useAudioRecorder; ownership is explicit
  // here so cancellation can await native prepare before releasing its resources.
  let recorder: AudioRecorder | undefined;
  let subscription: {remove(): void} | undefined;
  const owned = new Set<string>();
  let prepared: Promise<void> | undefined, stopped: Promise<void> | undefined, disposal: Promise<void> | undefined;
  let disposed = false, released = false, ownsLease = false;
  let finalizing: Promise<CapturedAudio> | undefined;
  let lease: ReturnType<typeof acquireNativeLease> | undefined;
  const remember = () => {
    try {if (recorder?.uri) {owned.add(recorder.uri); activeFiles.add(recorder.uri);}} catch { /* Native object may have released. */ }
  };
  const stop = () => {
    if (!stopped) stopped = (async () => {
      try {await prepared;} catch { /* Still release files from a failed prepare. */ }
      remember();
      try {if (recorder?.isRecording) await recorder.stop();} finally {remember();}
    })();
    return stopped;
  };
  return {
    prepare() {
      if (disposed) return Promise.reject(error('VOICE_CANCELLED'));
      if (!prepared) prepared = (async () => {
        lease = acquireNativeLease();
        await lease.ready; ownsLease = true;
        if (disposed) throw error('VOICE_CANCELLED');
        await module.setAudioModeAsync({allowsRecording: true, playsInSilentMode: true, shouldPlayInBackground: false, interruptionMode: 'doNotMix'});
        if (disposed) throw error('VOICE_CANCELLED');
        recorder = new module.AudioModule.AudioRecorder({...common, ...(Platform.OS === 'ios' ? ios : android)});
        remember();
        subscription = recorder.addListener('recordingStatusUpdate', status => {
          remember();
          if (!disposed && (status.isFinished || status.hasError)) onFinished(Boolean(status.hasError));
        });
        await recorder.prepareToRecordAsync(); remember();
      })();
      return prepared;
    },
    start(seconds) {
      if (disposed || !prepared || !recorder) throw error('VOICE_CANCELLED');
      recorder.record({forDuration: Math.min(45, seconds)}); remember();
    },
    finish(requestId) {
      if (finalizing) return finalizing;
      finalizing = (async () => {
      await stop();
      if (disposed) throw error('VOICE_CANCELLED');
      const uri = recorder?.uri;
      if (!uri) throw error('VOICE_INVALID_AUDIO');
      const {Directory, File, Paths} = files();
      const source = new File(uri);
      if (!source.exists || source.size <= 0 || source.size > 2_097_152 || !temporaryName.test(source.name)) throw error('VOICE_INVALID_AUDIO');
      if (!/^[a-f\d-]{36}$/i.test(requestId)) throw error('VOICE_INVALID_AUDIO');
      const directory = new Directory(Paths.cache, 'route-share-voice'); directory.create({idempotent: true, intermediates: true});
      const destination = new File(directory, `route-share-voice-${requestId}.m4a`);
      source.move(destination); owned.add(source.uri); activeFiles.add(source.uri);
      const clip = {uri: source.uri, size: source.size};
      recorder!.release(); released = true;
      await module.setAudioModeAsync({allowsRecording: false});
      if (disposed) throw error('VOICE_CANCELLED');
      return clip;
      })();
      return finalizing;
    },
    dispose() {
      if (disposal) return disposal;
      disposed = true; subscription?.remove();
      disposal = (async () => {
        try {
          await stop();
          try {await finalizing;} catch { /* Finish may have been cancelled; still release its lease. */ }
        } finally {
          remember();
          try {if (!released) {recorder?.release(); released = true;}} catch { /* Continue deleting owned files even after native release fails. */ }
          let cleanupFailed = false;
          const {File} = files();
          for (const uri of owned) {
            activeFiles.delete(uri);
            try {const file = new File(uri); if (file.exists && (temporaryName.test(file.name) || readyName.test(file.name))) file.delete();}
            catch {cleanupFailed = true;}
          }
          try {if (ownsLease) await module.setAudioModeAsync({allowsRecording: false});} catch { /* Recorder has stopped. */ }
          if (cleanupFailed) {startupCleanup = undefined; throw error('VOICE_CLEANUP_FAILED');}
        }
      })();
      void disposal.then(() => lease?.release(), cause => lease?.reject(cause));
      return disposal;
    },
  };
}
