import {prepareVoiceStorage} from './capture';
// Startup cleanup only touches marked files owned by this voice feature.
void prepareVoiceStorage().catch(() => {});
export {VoiceTripInput, type VoiceTripInputProps} from './VoiceTripInput';
export {parseTripTranscript, type VoiceTripDraft, type VoiceLanguage, type TripField} from './parser';
export {speakReply, stopVoice} from './speech';
export type {VoiceCapabilities} from './transport';
