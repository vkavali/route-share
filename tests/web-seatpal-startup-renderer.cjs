/* Focused lifecycle and preview behavior tests with a small DOM/clock mock. */
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const path = require('node:path');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');

const modes = ['lifecycle', 'failure-removal', 'reduced-motion', 'preview', 'busy-indicator'];
if (!process.argv[2]) {
  for (const mode of modes) {
    const result = spawnSync(process.execPath, [__filename, mode], { encoding: 'utf8' });
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
    assert.equal(result.status, 0, `${mode} scenario failed`);
  }
  process.exit(0);
}

const mode = process.argv[2];
let clock = 0;
let nextRaf = 1;
const rafs = new Map();
const documentListeners = new Map();
const observers = [];
let fetchImpl;
let fetchCount = 0;

class Element {
  constructor(name = 'div') {
    this.localName = name;
    this.dataset = {};
    this.attributes = {};
    this.childNodes = [];
    this.parentNode = null;
    this.listeners = new Map();
    this.textContent = '';
    this.value = '';
    this.innerHTML = '';
  }
  get isConnected() {
    for (let node = this; node; node = node.parentNode) if (node === document.documentElement) return true;
    return false;
  }
  append(node) { node.parentNode = this; this.childNodes.push(node); }
  appendChild(node) { this.append(node); return node; }
  replaceChildren(...nodes) {
    this.childNodes.forEach(node => { node.parentNode = null; });
    this.childNodes = [];
    nodes.forEach(node => this.append(node));
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  removeAttribute(name) { delete this.attributes[name]; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  closest() { return null; }
  querySelector(selector) {
    if (selector === '[data-seatpal-fallback]') return this.childNodes.find(node => 'seatpalFallback' in node.dataset) || null;
    return null;
  }
  addEventListener(name, fn) {
    const list = this.listeners.get(name) || [];
    list.push(fn); this.listeners.set(name, list);
  }
  click() { for (const fn of this.listeners.get('click') || []) fn({ currentTarget: this }); }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.childNodes = this.parentNode.childNodes.filter(node => node !== this);
    this.parentNode = null;
  }
}

const documentElement = new Element('html');
const document = global.document = {
  documentElement,
  hidden: false,
  createElementNS: (_ns, name) => new Element(name),
  createElement: name => new Element(name),
  importNode: node => new Element(node.localName),
  addEventListener(name, fn) {
    const list = documentListeners.get(name) || [];
    list.push(fn); documentListeners.set(name, list);
  },
  removeEventListener(name, fn) {
    documentListeners.set(name, (documentListeners.get(name) || []).filter(entry => entry !== fn));
  },
};
class MockMutationObserver {
  constructor(callback) { this.callback = callback; this.disconnected = false; observers.push(this); }
  observe(target) { this.target = target; }
  disconnect() { this.disconnected = true; }
  trigger() { this.callback([]); }
}
global.MutationObserver = MockMutationObserver;
global.DOMParser = class {
  parseFromString(xml) {
    const root = new Element(xml.includes('<svg') ? 'svg' : 'invalid');
    root.childNodes.push(new Element('path'));
    return { documentElement: root, querySelector: () => null };
  }
};
let reduced = false;
const mediaListeners = [];
const media = {
  get matches() { return reduced; },
  addEventListener(_name, fn) { mediaListeners.push(fn); },
  removeEventListener(_name, fn) { const i = mediaListeners.indexOf(fn); if (i >= 0) mediaListeners.splice(i, 1); },
};
global.window = { matchMedia: () => media };
global.performance = { now: () => clock };
global.requestAnimationFrame = fn => { const id = nextRaf++; rafs.set(id, fn); return id; };
global.cancelAnimationFrame = id => rafs.delete(id);
global.fetch = (...args) => { fetchCount += 1; return fetchImpl(...args); };

const validPayload = () => ({
  parts: Object.fromEntries(
    ['car', 'bike', 'rearWheel', 'frontWheel', 'seatBack', 'seatRail', 'seatBase', 'wordmark']
      .map(name => [name, { xml: '<svg><path/></svg>' }])
  ),
  wordmarkClip: { x: 385, y: 215, width: 400, height: 130 },
});
function deferredFetch() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  fetchImpl = () => promise;
  return {
    resolve: payload => resolve({ ok: true, json: async () => payload }),
    reject,
  };
}
function addStage() {
  const app = new Element('main');
  const stage = new Element('div');
  const fallback = new Element('div');
  fallback.dataset.seatpalFallback = '';
  fallback.innerHTML = '<svg data-seatpal-frame0="true"></svg>';
  stage.append(fallback);
  app.append(stage);
  documentElement.append(app);
  return { app, stage };
}
function fireDocument(name) { for (const fn of documentListeners.get(name) || []) fn(); }
function frame(ms) {
  clock += ms;
  const pending = [...rafs.entries()][0];
  assert(pending, 'expected an animation frame to be scheduled');
  rafs.delete(pending[0]);
  pending[1](clock);
}
async function settle() { await Promise.resolve(); await Promise.resolve(); await new Promise(resolve => setImmediate(resolve)); }
const rendererUrl = pathToFileURL(path.resolve(__dirname, '../static/seatpal-startup-renderer.js')).href;
const motionUrl = pathToFileURL(path.resolve(__dirname, '../static/seatpal-startup-motion.js')).href;
async function expectedFinalViewBox() {
  const { frameAt } = await import(`${motionUrl}?test=${mode}`);
  const frame = frameAt(1);
  return `${frame.viewBoxX} ${frame.viewBoxY} ${frame.viewBoxWidth} ${frame.viewBoxHeight}`;
}

(async () => {
  if (mode === 'failure-removal') {
    const failed = deferredFetch();
    const renderer = await import(`${rendererUrl}?scenario=failure`);
    const first = addStage();
    const failedController = renderer.mountSeatPalStartupMotion(first.stage);
    failed.reject(new Error('offline'));
    assert.equal(await failedController.ready, false);
    assert.equal(first.stage.childNodes.length, 1, 'failed fetch preserves canonical fallback');
    assert(observers.at(-1).disconnected, 'failed fetch disconnects removal observer');
    assert.equal(fetchCount, 1);
    assert.equal(documentListeners.get('visibilitychange')?.length || 0, 0);

    const delayed = deferredFetch();
    const second = addStage();
    const removedController = renderer.mountSeatPalStartupMotion(second.stage);
    assert.equal(fetchCount, 2, 'a failed asset request is retried for the next mount');
    second.app.remove(); // removal above the stage's direct parent
    observers.at(-1).trigger();
    assert(observers.at(-1).disconnected, 'removing an app ancestor disposes the renderer');
    delayed.resolve(validPayload());
    assert.equal(await removedController.ready, false, 'late asset resolution does not mount detached content');
    assert.equal(second.stage.childNodes.length, 1, 'detached stage keeps only the fallback');
    console.log('PASS fetch failure cleanup, preserved fallback, retryable loader, ancestor removal');
  } else if (mode === 'reduced-motion') {
    reduced = true;
    const finalViewBox = await expectedFinalViewBox();
    const pending = deferredFetch();
    const renderer = await import(`${rendererUrl}?scenario=reduced`);
    const { stage } = addStage();
    const frames = [];
    const controller = renderer.mountSeatPalStartupMotion(stage, { onFrame: value => frames.push(value) });
    pending.resolve(validPayload());
    assert.equal(await controller.ready, true);
    assert.equal(stage.childNodes.length, 1);
    assert.equal(stage.childNodes[0].getAttribute('viewBox'), finalViewBox);
    assert.deepEqual(frames, [1], 'reduced motion draws the final pose immediately');
    assert.equal(rafs.size, 0, 'reduced motion schedules no animation frames');
    controller.dispose();
    reduced = false;
    const liveStage = addStage().stage;
    const liveController = renderer.mountSeatPalStartupMotion(liveStage);
    assert.equal(await liveController.ready, true);
    assert.equal(rafs.size, 1, 'normal motion begins with one scheduled frame');
    reduced = true;
    mediaListeners.at(-1)({ matches: true });
    assert.equal(rafs.size, 0, 'changing the preference to reduced motion cancels animation');
    assert.equal(liveStage.childNodes[0].getAttribute('viewBox'), finalViewBox);
    liveController.dispose();
    console.log('PASS initial and live reduced-motion changes render the final pose without frames');
  } else if (mode === 'lifecycle') {
    const { STARTUP_MS } = await import(`${motionUrl}?test=${mode}`);
    const finalViewBox = await expectedFinalViewBox();
    const pending = deferredFetch();
    const renderer = await import(`${rendererUrl}?scenario=lifecycle`);
    const { stage } = addStage();
    const frames = [];
    const controller = renderer.mountSeatPalStartupMotion(stage, { onFrame: value => frames.push(value) });
    pending.resolve(validPayload());
    assert.equal(await controller.ready, true);
    const { frameAt } = await import(`${motionUrl}?test=${mode}`);
    const firstFrame = frameAt(0);
    assert.equal(stage.childNodes[0].getAttribute('viewBox'), `${firstFrame.viewBoxX} ${firstFrame.viewBoxY} ${firstFrame.viewBoxWidth} ${firstFrame.viewBoxHeight}`);
    frame(400);
    const beforeHide = frames.at(-1);
    document.hidden = true; fireDocument('visibilitychange');
    assert.equal(rafs.size, 0, 'hidden document pauses scheduled frame');
    document.hidden = false; fireDocument('visibilitychange');
    frame(100);
    assert(frames.at(-1) > beforeHide, 'visible document resumes from elapsed progress');

    controller.seek(.52);
    assert.equal(rafs.size, 0, 'manual seek pauses playback');
    const selectedPose = frames.at(-1);
    document.hidden = true; fireDocument('visibilitychange');
    document.hidden = false; fireDocument('visibilitychange');
    assert.equal(rafs.size, 0, 'visibility return does not resume a manually paused pose');
    assert.equal(frames.at(-1), selectedPose);

    controller.replay();
    assert.equal(rafs.size, 1, 'replay starts one animation loop');
    frame(STARTUP_MS);
    assert.equal(frames.at(-1), 1);
    assert.equal(stage.childNodes[0].getAttribute('viewBox'), finalViewBox);
    assert.equal(rafs.size, 0, 'completed animation releases its frame callback');
    controller.dispose();
    assert(observers.at(-1).disconnected);
    console.log('PASS replay lifecycle, visibility pause/resume, paused seek, and completion cleanup');
  } else if (mode === 'preview') {
    const pending = deferredFetch();
    const { stage } = addStage();
    const slider = new Element('input');
    const status = new Element('p');
    const replay = new Element('button');
    const car = new Element('button'); car.dataset.seek = '0.33'; car.textContent = 'Car';
    const elements = new Map([
      ['[data-seatpal-startup]', stage], ['.preview-slider', slider],
      ['[data-preview-status]', status], ['[data-replay]', replay],
    ]);
    document.querySelector = selector => elements.get(selector) || null;
    document.querySelectorAll = selector => selector === '[data-seek]' ? [car] : [];
    const previewUrl = pathToFileURL(path.resolve(__dirname, '../static/seatpal-startup-preview.js')).href;
    await import(`${previewUrl}?scenario=preview`);
    const previewHtml = fs.readFileSync(path.resolve(__dirname, '../static/seatpal-startup-preview.html'), 'utf8');
    assert.match(previewHtml, /seatpal:startup-frame0:start[\s\S]*?<svg[\s\S]*?seatpal:startup-frame0:end/, 'generated first-frame fallback is inline before scripts load');
    replay.click(); // before fetch resolves: must queue a replay
    car.click(); // the later command must replace that queued replay
    assert.equal(slider.value, '330');
    pending.resolve(validPayload());
    await settle();
    assert.equal(slider.value, '330', 'the last pre-load command wins');
    assert.equal(rafs.size, 0, 'a pre-load phase selection remains paused');
    replay.click(); // replay after readiness starts the actual animation
    assert.equal(slider.value, '0', 'replay begins at the first frame');
    assert.equal(rafs.size, 1);
    frame(900);
    assert(Number(slider.value) > 0, 'slider follows the renderer during replay');
    assert.equal(status.textContent, 'Animation preview: Car phase');
    frame(3000);
    assert.equal(slider.value, '1000');
    assert.equal(status.textContent, 'Animation preview: Logo phase');
    car.click();
    assert.equal(slider.value, '330');
    assert.equal(status.textContent, 'Animation preview: Car phase');
    console.log('PASS preview queues early replay and reflects animation frames and phase captions');
  } else if (mode === 'busy-indicator') {
    const busyUrl = pathToFileURL(path.resolve(__dirname, '../static/seatpal-busy.js')).href;
    const { busyMark, beginBusy } = await import(`${busyUrl}?scenario=busy`);
    assert.match(busyMark(), /^<span class="seatpal-loading-mark" aria-hidden="true"><\/span>$/);
    assert.doesNotMatch(busyMark(), /<img|<svg/);
    const button = new Element('button');
    button.innerHTML = '<strong>Save</strong>';
    button.disabled = true;
    const stop = beginBusy(button, 'Saving');
    assert.equal(button.disabled, true);
    assert.equal(button.getAttribute('aria-busy'), 'true');
    assert.equal(button.dataset.seatpalPending, 'true');
    assert.match(button.innerHTML, /seatpal-loading-mark/);
    const duplicateStop = beginBusy(button, 'Duplicate operation');
    duplicateStop();
    assert.equal(button.getAttribute('aria-busy'), 'true', 'duplicate start cannot clear the active request');
    stop();
    assert.equal(button.innerHTML, '<strong>Save</strong>');
    assert.equal(button.disabled, true, 'original disabled state is restored');
    assert.equal(button.getAttribute('aria-busy'), null);
    assert.equal(button.dataset.seatpalPending, undefined);
    console.log('PASS compact spinner is unbranded and preserves idempotent pending cleanup');
  } else {
    throw new Error(`unknown test mode ${mode}`);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
