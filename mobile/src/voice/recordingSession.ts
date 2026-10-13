import type {CapturedAudio, LocalCapture} from './capture';
export type RecordingStatus = 'idle' | 'starting' | 'recording' | 'finishing';
type Dependencies = {
  stopPlayback(): Promise<void>;
  permission(): Promise<boolean>;
  storage(): Promise<void>;
  create(onFinished: (failed: boolean) => void): LocalCapture;
  onStatus(status: RecordingStatus): void;
  onError(code: string): void;
};
/** Owns only local microphone work. Consumers decide what to do with a finished clip. */
export class RecordingSession {
  private revision = 0;
  private capture: LocalCapture | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private cleanup: Promise<void> = Promise.resolve();
  private finishing = false;
  constructor(private readonly deps: Dependencies) {}
  async start(id: string, seconds: number, consume: (clip: CapturedAudio) => Promise<void>): Promise<void> {
    const stopping = this.cancel();
    const ticket = this.revision;
    const current = () => ticket === this.revision;
    this.deps.onStatus('starting');
    try {
      await stopping;
      if (!current()) return;
      await this.deps.stopPlayback();
      if (!current()) return;
      if (!await this.deps.permission()) {if (current()) throw Object.assign(new Error(), {code: 'VOICE_DENIED'}); return;}
      if (!current()) return;
      await this.deps.storage();
      if (!current()) return;
      const capture = this.deps.create(failed => {
        if (!current()) return;
        if (failed) {this.deps.onError('VOICE_FAILED'); void this.cancel().catch(() => {});}
        else void this.finish(id, consume, ticket).catch(() => {if (current()) this.deps.onError('VOICE_FAILED');});
      });
      this.capture = capture;
      await capture.prepare();
      if (!current()) return;
      capture.start(seconds);
      this.finishCallback = () => this.finish(id, consume, ticket);
      this.deps.onStatus('recording');
      this.timer = setTimeout(() => {void this.finish(id, consume, ticket).catch(() => {if (current()) this.deps.onError('VOICE_FAILED');});}, Math.min(45, seconds) * 1000);
    } catch (cause: any) {
      if (current()) {this.deps.onError(cause?.code || 'VOICE_FAILED'); await this.cancel();}
    }
  }
  private finishCallback: (() => Promise<void>) | undefined;
  async finish(id?: string, consume?: (clip: CapturedAudio) => Promise<void>, ticket = this.revision): Promise<void> {
    if (!id || !consume) {await this.finishCallback?.(); return;}
    if (this.finishing || ticket !== this.revision || !this.capture) return;
    this.finishing = true; this.clearTimer(); this.deps.onStatus('finishing');
    const capture = this.capture;
    try {
      const clip = await capture.finish(id);
      if (ticket === this.revision) await consume(clip);
    } catch (cause: any) {
      if (ticket === this.revision && cause?.code !== 'VOICE_CANCELLED') this.deps.onError(cause?.code || 'VOICE_FAILED');
    } finally {
      if (ticket === this.revision) await this.cancel();
    }
  }
  private clearTimer() {if (this.timer) clearTimeout(this.timer); this.timer = undefined;}
  cancel(): Promise<void> {
    ++this.revision; this.clearTimer(); this.finishCallback = undefined; this.finishing = false;
    const capture = this.capture; this.capture = undefined;
    this.deps.onStatus('idle');
    this.cleanup = Promise.all([this.cleanup, capture?.dispose()]).then(() => undefined);
    return this.cleanup;
  }
}
