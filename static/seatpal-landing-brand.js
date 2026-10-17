(() => {
  'use strict';
  const DURATION = 9400;
  const FULL_VIEWBOX = '120 130 740 310';
  const FULL_VIEWBOX_BOX = { x: 120, y: 130, width: 740, height: 310 };
  const LOGO_CROP = { x: 285, y: 218, width: 410, height: 100 };
  const DOCK_DURATION = 850;
  const init = (root) => {
    const $ = (id) => root.querySelector(`#sp-seatpal-${id}`);
    const el = {
      scene: $('scene'), seat: $('seat'), back: $('seat-back'), rail: $('seat-rail'),
      car: $('car'), carFill: $('car-fill'), carDecoration: $('car-decoration'),
      carSmallDetails: $('car-small-details'), driver: $('driver-seat'), frame: $('shared-frame'),
      bike: $('bike'), bikeDecoration: $('bike-decoration'), bikeRearDetails: $('bike-rear-details'),
      tank: $('tank-fill'), engine: $('bike-engine'), rear: $('rear-wheel'), front: $('front-wheel'),
      ground: $('ground'), word: $('wordmark'), clip: $('word-clip'),
    };
    const toggle = root.querySelector('[data-seatpal-brand-toggle]');
    if (!toggle || Object.values(el).some((node) => !node)) return;

    const carLines = [...el.car.querySelectorAll('.car-trace')];
    const bikeLines = [...el.bike.querySelectorAll('.bike-trace')];
    const bikeFills = [...el.bike.querySelectorAll('.bike-fill')];
    const clamp = (x) => Math.min(1, Math.max(0, x));
    const ease = (x) => { x = clamp(x); return x * x * x * (x * (x * 6 - 15) + 10); };
    const phase = (t, a, b) => ease((t - a) / (b - a));
    const mix = (a, b, p) => a + (b - a) * p;
    const opacity = (node, x) => node.setAttribute('opacity', clamp(x).toFixed(4));
    const trace = (nodes, p) => nodes.forEach((node) => { node.style.strokeDashoffset = (1 - clamp(p)).toFixed(4); });
    let time = 0, playing = false, last = null, raf = 0;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    let reduceMotion = reduced.matches;
    const homeSlot = root.parentElement;
    const headerLink = document.querySelector('.site-header .wordmark');
    let dockWrap = null, dockWindow = null, docked = false, dockTimer = 0, slotTimer = 0, pendingSlot = null;

    if (!headerLink) return;
    headerLink.setAttribute('aria-label', 'SeatPal');

    function wheel(node, x, y, s, rotation, visibility) {
      node.setAttribute('transform', `translate(${x.toFixed(3)} ${y.toFixed(3)}) scale(${s.toFixed(4)})`);
      node.querySelector('.spokes').setAttribute('transform', `rotate(${rotation.toFixed(2)})`);
      opacity(node, visibility);
    }
    function draw(ms) {
      const t = ms / 1000;
      const intoCar = phase(t, .75, 2.15), toBike = phase(t, 3.2, 4.9), resolve = phase(t, 6.1, 8.2);
      const unfold = phase(t, 6.35, 7.95), retract = phase(t, 6.1, 7.6);
      let sx = mix(466, 328, intoCar), sy = mix(307, 326, intoCar), scale = mix(1.1, .76, intoCar);
      sx = mix(sx, 410, toBike); sy = mix(sy, 282, toBike); scale = mix(scale, .52, toBike);
      sx = mix(sx, 315, resolve); sy = mix(sy, 306, resolve); scale = mix(scale, .54, resolve);
      const fold = toBike * (1 - unfold);
      el.seat.setAttribute('transform', `translate(${sx.toFixed(3)} ${sy.toFixed(3)}) scale(${scale.toFixed(4)})`);
      const seatBackAngle = mix(mix(mix(-8, -12, intoCar), -88, fold), -8, resolve);
      el.back.setAttribute('transform', `rotate(${seatBackAngle.toFixed(3)}) scale(${mix(1, .55, fold).toFixed(4)} 1)`);
      opacity(el.rail, 1 - fold);

      const carBuild = phase(t, .95, 2.2), carLeave = phase(t, 3.2, 4.65);
      opacity(el.car, carBuild > 0 && carLeave < 1 ? 1 : 0);
      trace(carLines, carBuild * (1 - carLeave));
      const carFill = phase(t, 1.6, 2.2) * (1 - phase(t, 3.2, 3.8));
      opacity(el.carFill, carFill);
      opacity(el.carDecoration, carFill);
      opacity(el.carSmallDetails, carFill);
      opacity(el.driver, phase(t, 1.8, 2.2) * (1 - phase(t, 3.2, 3.7)));

      const bikeBuild = phase(t, 3.85, 4.95);
      opacity(el.bike, bikeBuild > 0 && retract < 1 ? 1 : 0);
      trace(bikeLines, bikeBuild * (1 - retract));
      bikeFills.forEach((node) => opacity(node, bikeBuild * (1 - retract)));
      opacity(el.bikeDecoration, bikeBuild * (1 - retract));
      opacity(el.bikeRearDetails, bikeBuild * (1 - retract));
      opacity(el.tank, phase(t, 4.25, 4.95) * (1 - phase(t, 6.1, 6.65)));
      opacity(el.engine, phase(t, 4.3, 4.95) * (1 - phase(t, 6.1, 6.65)));

      let rearX = mix(260, 365, toBike), frontX = mix(700, 585, toBike), wy = 365;
      const collect = phase(t, 6.2, 7.85), targetX = sx, targetY = sy + 3 * scale;
      const bikeKeep = 1 - collect, bikeLift = 22 * Math.sin(Math.PI * collect);
      el.bike.setAttribute('transform', `translate(${targetX * collect} ${targetY * collect + bikeLift}) scale(${bikeKeep})`);
      const rearStart = rearX, frontStart = frontX;
      const carScale = (frontStart - rearStart) / 440;
      el.car.setAttribute('transform', `translate(${rearStart - 260 * carScale} 0) scale(${carScale} 1)`);
      rearX = mix(rearX, targetX, collect); frontX = mix(frontX, targetX, collect);
      wy = mix(wy, targetY, collect) + bikeLift;
      const wheelScale = Math.pow(1 - collect, 1.4) + .035 * collect;
      const wheelShow = phase(t, 1.1, 1.8) * (1 - phase(t, 7.55, 7.9));
      wheel(el.rear, rearX, wy, wheelScale, (rearX - 260) / 52.5 * 180 / Math.PI, wheelShow);
      wheel(el.front, frontX, wy, wheelScale, (frontX - 700) / 52.5 * 180 / Math.PI, wheelShow);

      const p = [rearStart, 365, mix(320, 420, toBike), mix(354, 349, toBike), mix(638, 490, toBike), mix(354, 351, toBike), mix(700, 585, toBike), 365];
      el.frame.setAttribute('d', `M${p[0]} ${p[1]}L${p[2]} ${p[3]}L${p[4]} ${p[5]}L${p[6]} ${p[7]}`);
      el.frame.setAttribute('transform', `translate(${targetX * collect} ${targetY * collect + bikeLift}) scale(${bikeKeep})`);
      opacity(el.frame, phase(t, 1.8, 2.2) * (1 - phase(t, 3.8, 4.6)) * (1 - retract));
      const roadOpacity = phase(t, 1.1, 1.9) * (1 - resolve);
      el.ground.setAttribute('d', `M${mix(150, sx - 5, resolve)} ${mix(422, sy + 27 * scale, resolve)}H${mix(840, sx + 77 * scale, resolve)}`);
      opacity(el.ground, roadOpacity);

      const words = phase(t, 7.25, 8.45);
      el.clip.setAttribute('width', (400 * words).toFixed(3));
      opacity(el.word, words);
      el.word.setAttribute('transform', `translate(${(10 * (1 - words)).toFixed(3)} 0)`);
      root.dataset.phase = t < 1 ? 'seat' : t < 3.2 ? 'car' : t < 4.9 ? 'car-to-bike' : t < 6.1 ? 'bike' : t < 8.45 ? 'resolve' : 'logo';
      root.dataset.time = ms.toFixed(1);
    }
    const render = () => {
      const state = root.dataset.motion;
      const running = state === 'running';
      const label = running ? root.dataset.labelPause
        : state === 'paused' ? root.dataset.labelPlay : root.dataset.labelReplay;
      toggle.setAttribute('aria-label', label);
      toggle.setAttribute('title', label);
      toggle.dataset.motion = state;
    };
    function dock(animate = true) {
      if (docked) return;
      const sourceSlot = homeSlot;
      const sourceSlotHeight = sourceSlot?.getBoundingClientRect().height || 0;
      const firstScene = el.scene.getBoundingClientRect();
      const firstLogo = {
        left: firstScene.left + (LOGO_CROP.x - FULL_VIEWBOX_BOX.x) / FULL_VIEWBOX_BOX.width * firstScene.width,
        top: firstScene.top + (LOGO_CROP.y - FULL_VIEWBOX_BOX.y) / FULL_VIEWBOX_BOX.height * firstScene.height,
        width: LOGO_CROP.width / FULL_VIEWBOX_BOX.width * firstScene.width,
        height: LOGO_CROP.height / FULL_VIEWBOX_BOX.height * firstScene.height,
      };
      const img = headerLink.querySelector('img');
      const text = headerLink.querySelector('span');
      if (img) img.hidden = true;
      if (text) text.hidden = true;
      headerLink.setAttribute('aria-label', 'SeatPal');
      headerLink.classList.add('sp-seatpal-docked');

      if (!dockWrap) {
        dockWrap = document.createElement('div');
        dockWrap.className = 'sp-seatpal-header-dock';
        headerLink.parentNode.insertBefore(dockWrap, headerLink);
        dockWrap.append(headerLink);
      }
      dockWindow = document.createElement('span');
      dockWindow.className = 'sp-seatpal-dock-window';
      headerLink.append(dockWindow);
      toggle.remove();
      root.classList.add('is-docked');
      const targetWidth = dockWindow.getBoundingClientRect().width;
      const rootWidth = targetWidth * FULL_VIEWBOX_BOX.width / LOGO_CROP.width;
      const rootHeight = rootWidth * FULL_VIEWBOX_BOX.height / FULL_VIEWBOX_BOX.width;
      root.style.setProperty('--sp-seatpal-dock-svg-width', `${rootWidth}px`);
      root.style.setProperty('--sp-seatpal-dock-left', `${-(LOGO_CROP.x - FULL_VIEWBOX_BOX.x) / FULL_VIEWBOX_BOX.width * rootWidth}px`);
      root.style.setProperty('--sp-seatpal-dock-top', `${-(LOGO_CROP.y - FULL_VIEWBOX_BOX.y) / FULL_VIEWBOX_BOX.height * rootHeight}px`);
      dockWindow.append(root);
      dockWrap.append(toggle);
      docked = true;
      document.body.classList.add('seatpal-brand-docked');
      const illustration = homeSlot?.parentElement;
      const collapseSlot = (smooth) => {
        if (!sourceSlot) return;
        pendingSlot = sourceSlot;
        sourceSlot.classList.remove('is-collapsed', 'is-docked');
        sourceSlot.style.height = `${sourceSlotHeight}px`;
        sourceSlot.style.overflow = 'hidden';
        if (!smooth || !sourceSlotHeight) {
          sourceSlot.classList.add('is-collapsed');
          sourceSlot.style.height = '';
          sourceSlot.style.overflow = '';
          illustration?.classList.add('is-collapsed');
          return;
        }
        sourceSlot.classList.add('is-collapsing');
        sourceSlot.getBoundingClientRect();
        requestAnimationFrame(() => sourceSlot.classList.add('is-docked'));
        slotTimer = window.setTimeout(() => {
          sourceSlot.classList.add('is-collapsed');
          sourceSlot.classList.remove('is-collapsing', 'is-docked');
          sourceSlot.style.height = '';
          sourceSlot.style.overflow = '';
          illustration?.classList.add('is-collapsed');
          pendingSlot = null;
        }, DOCK_DURATION + 30);
      };

      const lastWindow = dockWindow.getBoundingClientRect();
      const scale = firstLogo.width / lastWindow.width;
      const translateX = firstLogo.left - lastWindow.left;
      const translateY = firstLogo.top - lastWindow.top;
      const reduce = !animate || reduceMotion || !lastWindow.width || !firstLogo.width;
      if (reduce) {
        dockWindow.style.transform = '';
        dockWindow.style.transition = '';
        collapseSlot(false);
        return;
      }

      dockWindow.style.transformOrigin = 'top left';
      dockWindow.style.transition = 'none';
      dockWindow.style.transform = `translate(${translateX.toFixed(2)}px, ${translateY.toFixed(2)}px) scale(${scale.toFixed(4)})`;
      dockWindow.getBoundingClientRect();
      root.dataset.docking = 'true';
      toggle.disabled = true;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        dockWindow.style.transition = `transform ${DOCK_DURATION}ms cubic-bezier(.22, 1, .36, 1)`;
        dockWindow.style.transform = 'none';
        collapseSlot(true);
      }));
      dockTimer = window.setTimeout(() => {
        dockWindow.style.transition = ''; dockWindow.style.transform = '';
        delete root.dataset.docking;
        toggle.disabled = false;
      }, DOCK_DURATION + 40);
    }
    function undock() {
      if (!docked) return;
      window.clearTimeout(dockTimer); window.clearTimeout(slotTimer);
      toggle.disabled = false;
      root.classList.remove('is-docked');
      root.style.cssText = '';
      delete root.dataset.docking;
      dockWindow?.remove(); dockWindow = null;
      toggle.remove();
      root.append(toggle);
      const sourceSlot = homeSlot;
      sourceSlot?.classList.remove('is-collapsing', 'is-collapsed', 'is-docked');
      if (sourceSlot) { sourceSlot.style.height = ''; sourceSlot.style.overflow = ''; sourceSlot.append(root); }
      homeSlot?.parentElement?.classList.remove('is-collapsed');
      document.body.classList.remove('seatpal-brand-docked');
      docked = false;
    }
    function tick(now) {
      if (!playing) return;
      if (last !== null) time = Math.min(DURATION, time + Math.max(0, now - last));
      last = now; draw(time);
      if (time >= DURATION) { playing = false; last = null; root.dataset.motion = 'finished'; render(); dock(true); return; }
      raf = requestAnimationFrame(tick);
    }
    function pause() { playing = false; last = null; cancelAnimationFrame(raf); root.dataset.motion = 'paused'; render(); }
    function start(restart = false) {
      if (docked) undock();
      if (restart || time >= DURATION) time = 0;
      toggle.hidden = false; playing = true; last = null; root.dataset.motion = 'running';
      root.dataset.time = '0.0'; draw(time); render(); raf = requestAnimationFrame(tick);
    }
    toggle.addEventListener('click', () => {
      if (root.dataset.motion === 'running') pause();
      else if (root.dataset.motion === 'paused') start(false);
      else start(true);
    });
    document.addEventListener('visibilitychange', () => { last = null; });
    const onMotionChange = (event) => {
      reduceMotion = event.matches;
      if (reduceMotion) {
        playing = false; last = null; cancelAnimationFrame(raf); time = DURATION; draw(time);
        root.dataset.motion = 'finished'; render(); toggle.hidden = true;
        if (docked) {
          window.clearTimeout(dockTimer); window.clearTimeout(slotTimer);
          if (dockWindow) { dockWindow.style.transition = ''; dockWindow.style.transform = ''; }
          delete root.dataset.docking; toggle.disabled = false;
          if (pendingSlot) { pendingSlot.classList.add('is-collapsed'); pendingSlot.classList.remove('is-collapsing', 'is-docked'); pendingSlot.style.height = ''; pendingSlot.style.overflow = ''; pendingSlot.parentElement?.classList.add('is-collapsed'); pendingSlot = null; }
        } else dock(false);
      } else {
        render(); toggle.hidden = false;
      }
    };
    if (reduced.addEventListener) reduced.addEventListener('change', onMotionChange);
    else reduced.addListener?.(onMotionChange);
    if (reduceMotion) { time = DURATION; draw(time); root.dataset.motion = 'finished'; render(); toggle.hidden = true; dock(false); }
    else start(true);
  };
  const initAll = () => document.querySelectorAll('[data-seatpal-brand]').forEach(init);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initAll, { once: true });
  else initAll();
})();
