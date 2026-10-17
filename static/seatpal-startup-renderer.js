import { frameAt, STARTUP_ASSET_HASH, STARTUP_MS, VIEW_BOX } from './seatpal-startup-motion.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const MOTION_URL = `/static/assets/seatpal/startup-motion.json?v=${STARTUP_ASSET_HASH}`;
const PART_NAMES = ['car', 'bike', 'rearWheel', 'frontWheel', 'seatBack', 'seatRail', 'seatBase', 'wordmark'];
let partsPromise;
let sceneSequence = 0;

function loadParts() {
  if (!partsPromise) {
    partsPromise = fetch(MOTION_URL, { cache: 'force-cache', credentials: 'same-origin' })
      .then(response => {
        if (!response.ok) throw new Error('motion asset unavailable');
        return response.json();
      })
      .then(data => {
        if (!data || !PART_NAMES.every(name => typeof data.parts?.[name]?.xml === 'string')) {
          throw new Error('motion asset invalid');
        }
        return { ...data.parts, wordmarkClip: data.wordmarkClip };
      }).catch(error => {
        partsPromise = null;
        throw error;
      });
  }
  return partsPromise;
}

function importPart(xml) {
  const parsed = new DOMParser().parseFromString(xml, 'image/svg+xml');
  const source = parsed.documentElement;
  if (source.localName !== 'svg' || parsed.querySelector('parsererror')) {
    throw new Error('motion part invalid');
  }
  const group = document.createElementNS(SVG_NS, 'g');
  for (const node of source.childNodes) group.append(document.importNode(node, true));
  return group;
}

function buildScene(stage, partData) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('width', '100%');
  svg.setAttribute('height', '100%');
  const firstFrame = frameAt(0);
  svg.setAttribute('viewBox', `${firstFrame.viewBoxX} ${firstFrame.viewBoxY} ${firstFrame.viewBoxWidth} ${firstFrame.viewBoxHeight}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.setAttribute('focusable', 'false');
  svg.setAttribute('aria-hidden', 'true');
  svg.dataset.seatpalMotion = 'true';
  const clipId = `seatpal-startup-word-${++sceneSequence}`;
  const defs = document.createElementNS(SVG_NS, 'defs');
  const clip = document.createElementNS(SVG_NS, 'clipPath');
  clip.setAttribute('id', clipId);
  clip.setAttribute('clipPathUnits', 'userSpaceOnUse');
  const clipRect = document.createElementNS(SVG_NS, 'rect');
  clipRect.setAttribute('x', String(dataWordClip(partData).x));
  clipRect.setAttribute('y', String(dataWordClip(partData).y));
  clipRect.setAttribute('width', '0');
  clipRect.setAttribute('height', String(dataWordClip(partData).height));
  clip.append(clipRect);
  defs.append(clip);
  svg.append(defs);
  const groups = {};
  for (const name of ['car', 'bike', 'rearWheel', 'frontWheel']) {
    const wrapper = document.createElementNS(SVG_NS, 'g');
    wrapper.dataset.part = name;
    wrapper.append(importPart(partData[name].xml));
    svg.append(wrapper);
    groups[name] = wrapper;
  }
  const seat = document.createElementNS(SVG_NS, 'g');
  seat.dataset.part = 'seat';
  for (const name of ['seatRail', 'seatBack', 'seatBase']) {
    const wrapper = document.createElementNS(SVG_NS, 'g');
    wrapper.dataset.part = name;
    wrapper.append(importPart(partData[name].xml));
    seat.append(wrapper);
    groups[name] = wrapper;
  }
  svg.append(seat);
  groups.seat = seat;
  const wordmark = document.createElementNS(SVG_NS, 'g');
  wordmark.dataset.part = 'wordmark';
  wordmark.setAttribute('clip-path', `url(#${clipId})`);
  wordmark.append(importPart(partData.wordmark.xml));
  svg.append(wordmark);
  groups.wordmark = wordmark;
  groups.wordmarkClip = clipRect;
  // Swap the canonical inline first-paint fallback only after all actual parts exist.
  stage.replaceChildren(svg);
  stage.dataset.motionInitialized = 'true';
  return { svg, groups, wordmarkClip: partData.wordmarkClip };
}

function dataWordClip(partData) {
  return partData.wordmarkClip || { x: 385, y: 215, width: 400, height: 130 };
}

function setPose(scene, progress, onFrame) {
  const frame = frameAt(progress);
  const { svg, groups, wordmarkClip } = scene;
  svg.setAttribute('viewBox', `${frame.viewBoxX} ${frame.viewBoxY} ${frame.viewBoxWidth} ${frame.viewBoxHeight}`);
  const set = (name, key, value) => groups[name].setAttribute(key, String(value));

  set('car', 'opacity', 1);
  set('car', 'transform', `translate(${frame.carX} 0) scale(${frame.carScaleX} 1)`);
  const carXml = groups.car;
  const setPartOpacity = (root, selector, opacity) => {
    const element = root.querySelector(selector);
    if (element) element.setAttribute('opacity', String(opacity));
  };
  const setTraceProgress = (root, selector, progress) => {
    root.querySelectorAll(selector).forEach(path => {
      path.setAttribute('stroke-dasharray', '1');
      path.setAttribute('stroke-dashoffset', String(1 - progress));
    });
  };
  setPartOpacity(carXml, '#sp-seatpal-car', 1);
  setPartOpacity(carXml, '#sp-seatpal-car-fill', frame.carFillOpacity);
  setPartOpacity(carXml, '#sp-seatpal-car-decoration', frame.carDecorationOpacity);
  setPartOpacity(carXml, '#sp-seatpal-car-small-details', frame.carSmallDetailsOpacity);
  setPartOpacity(carXml, '#sp-seatpal-driver-seat', frame.driverOpacity);
  setTraceProgress(carXml, '.car-trace', frame.carLineProgress);
  set('bike', 'opacity', 1);
  set('bike', 'transform', `translate(${frame.bikeX} ${frame.bikeY}) scale(${frame.bikeScale})`);
  const bikeXml = groups.bike;
  setPartOpacity(bikeXml, '#sp-seatpal-bike', 1);
  setPartOpacity(bikeXml, '#sp-seatpal-bike-decoration', frame.bikeDecorationOpacity);
  setPartOpacity(bikeXml, '#sp-seatpal-tank-fill', frame.tankOpacity);
  setPartOpacity(bikeXml, '#sp-seatpal-bike-engine', frame.engineOpacity);
  setPartOpacity(bikeXml, '#sp-seatpal-bike-rear-details', frame.bikeRearDetailsOpacity);
  bikeXml.querySelectorAll('.bike-fill').forEach(path => {
    if (path.id === 'sp-seatpal-tank-fill') return;
    if (path.closest('#sp-seatpal-bike-decoration')) return;
    path.setAttribute('opacity', String(frame.bikeFillOpacity));
  });
  setTraceProgress(bikeXml, '.bike-trace', frame.bikeLineProgress);
  set('rearWheel', 'opacity', frame.wheelOpacity);
  set('rearWheel', 'transform', `translate(${frame.rearX} ${frame.wheelY}) rotate(${frame.rearRotation}) scale(${frame.wheelScale})`);
  set('frontWheel', 'opacity', frame.wheelOpacity);
  set('frontWheel', 'transform', `translate(${frame.frontX} ${frame.wheelY}) rotate(${frame.frontRotation}) scale(${frame.wheelScale})`);
  set('seat', 'transform', `translate(${frame.seatX} ${frame.seatY}) scale(${frame.seatScale})`);
  set('seatBack', 'transform', `rotate(${frame.backAngle}) scale(${frame.backScaleX} 1)`);
  set('seatRail', 'opacity', frame.railOpacity);
  set('wordmark', 'opacity', frame.wordOpacity);
  set('wordmark', 'transform', `translate(${frame.wordX} 0)`);
  groups.wordmarkClip.setAttribute('width', String(wordmarkClip.width * frame.wordReveal));
  onFrame(progress);
}

export function mountSeatPalStartupMotion(stage, { autoStart = true, onFrame = () => {} } = {}) {
  if (!stage) return { ready: Promise.resolve(false), replay() {}, seek() {}, dispose() {} };
  let scene = null;
  let raf = 0;
  let disposed = false;
  let finished = false;
  let playing = autoStart;
  let startedAt = 0;
  let elapsedBeforePause = 0;
  let pendingSeek = autoStart ? null : 0;
  let pendingReplay = false;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const observerRoot = document.documentElement || stage.parentNode;

  const stopFrame = () => {
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
  };
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    stopFrame();
    observer.disconnect();
    document.removeEventListener('visibilitychange', visibilityChanged);
    reducedMotion.removeEventListener?.('change', motionPreferenceChanged);
  };
  const finishAtFinal = () => {
    if (!scene || disposed) return;
    stopFrame();
    elapsedBeforePause = STARTUP_MS;
    finished = true;
    playing = false;
    setPose(scene, 1, onFrame);
  };
  const renderElapsed = (now) => {
    if (!scene || disposed) return;
    const elapsed = Math.max(0, Math.min(STARTUP_MS, elapsedBeforePause + now - startedAt));
    setPose(scene, elapsed / STARTUP_MS, onFrame);
    if (elapsed >= STARTUP_MS) {
      finishAtFinal();
      return;
    }
    raf = requestAnimationFrame(renderElapsed);
  };
  const startFromBeginning = () => {
    if (disposed) return;
    if (!scene) {
      pendingReplay = true;
      pendingSeek = null;
      return;
    }
    pendingReplay = false;
    stopFrame();
    elapsedBeforePause = 0;
    finished = false;
    playing = true;
    startedAt = performance.now();
    if (reducedMotion.matches) {
      finishAtFinal();
      return;
    }
    setPose(scene, 0, onFrame);
    if (!document.hidden) raf = requestAnimationFrame(renderElapsed);
  };
  const seek = (progress) => {
    const normalized = Math.max(0, Math.min(1, Number(progress) || 0));
    pendingSeek = normalized;
    pendingReplay = false;
    playing = false;
    finished = normalized >= 1;
    if (!scene || disposed) return;
    stopFrame();
    elapsedBeforePause = normalized * STARTUP_MS;
    setPose(scene, normalized, onFrame);
  };
  const replay = () => startFromBeginning();
  const visibilityChanged = () => {
    if (!scene || disposed || finished || !playing) return;
    if (document.hidden) {
      if (raf) {
        elapsedBeforePause = Math.max(0, Math.min(STARTUP_MS, elapsedBeforePause + performance.now() - startedAt));
        stopFrame();
      }
    } else if (!reducedMotion.matches) {
      startedAt = performance.now();
      raf = requestAnimationFrame(renderElapsed);
    }
  };
  const motionPreferenceChanged = (event) => {
    if (event.matches) finishAtFinal();
  };
  const observer = new MutationObserver(() => {
    if (!stage.isConnected) dispose();
  });
  observer.observe(observerRoot, { childList: true, subtree: true });
  document.addEventListener('visibilitychange', visibilityChanged);
  reducedMotion.addEventListener?.('change', motionPreferenceChanged);

  const ready = loadParts().then(partData => {
    if (disposed || !stage.isConnected) {
      dispose();
      return false;
    }
    scene = buildScene(stage, partData);
    if (reducedMotion.matches) {
      finishAtFinal();
    } else if (pendingReplay) {
      startFromBeginning();
    } else if (pendingSeek !== null) {
      seek(pendingSeek);
    } else if (autoStart) {
      startFromBeginning();
    }
    return true;
  }).catch(() => {
    dispose();
    return false;
  });

  return { ready, replay, seek, dispose };
}
