/* Five-stage explanation only: no account, booking, payment or location access. */
(() => {
  const journey = document.querySelector('[data-five-stage-journey]');
  if (!journey || journey.dataset.scenesEnhanced === 'true') return;
  const names = ['find', 'check', 'agree', 'meet', 'arrive'];
  const stages = names.map(name => journey.querySelector(`[data-journey-stage="${name}"]`));
  if (stages.some(stage => !stage)) return;
  const stageLinks = [...journey.querySelectorAll('[data-stage-jump]')];
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const layers = [...journey.querySelectorAll('[data-scene-depth]')].map(node => ({ node, center: 0, offset: 0 }));
  let geometry = [];
  let frame = 0;
  let needsMeasure = true;
  let active = -1;
  // One bounded brand sequence. All contexts share the same highlighted cushion.
  const seatBrand = journey.querySelector('[data-seat-brand]');
  if (seatBrand && typeof Element.prototype.animate === 'function') {
    const car = seatBrand.querySelector('[data-seat-car]');
    const bike = seatBrand.querySelector('[data-seat-bike]');
    const back = seatBrand.querySelector('[data-seat-back]');
    const base = seatBrand.querySelector('[data-seat-base]');
    const replay = seatBrand.querySelector('[data-seat-replay]');
    let animations = [], started = false, visible = false;
    const cancel = () => { animations.forEach(a => a.cancel()); animations = []; };
    const play = () => {
      cancel();
      if (reduced.matches || document.hidden) return;
      started = true;
      const options = { duration: 4400, fill: 'none', easing: 'linear' };
      const run = (node, frames) => { const animation = node.animate(frames, options); animations.push(animation); return animation; };
      run(car, [{opacity:0,offset:0},{opacity:0,offset:.05},{opacity:1,offset:.17},{opacity:1,offset:.34},{opacity:0,offset:.45},{opacity:0,offset:1}]);
      run(bike, [{opacity:0,offset:0},{opacity:0,offset:.39},{opacity:1,offset:.53},{opacity:1,offset:.74},{opacity:0,offset:.86},{opacity:0,offset:1}]);
      run(back, [{transform:'none',offset:0},{transform:'scaleY(.55)',offset:.18},{transform:'scaleY(.55)',offset:.34},{transform:'rotate(-72deg) scale(.3)',offset:.53},{transform:'rotate(-72deg) scale(.3)',offset:.74},{transform:'none',offset:.94},{transform:'none',offset:1}]);
      run(seatBrand.querySelector('[data-seat-headrest]'), [{opacity:1,offset:0},{opacity:1,offset:.34},{opacity:0,offset:.48},{opacity:0,offset:.78},{opacity:1,offset:.94},{opacity:1,offset:1}]);
      run(base, [{transform:'none',offset:0},{transform:'none',offset:.34},{transform:'scaleY(.45)',offset:.53},{transform:'scaleY(.45)',offset:.74},{transform:'none',offset:.94},{transform:'none',offset:1}]);
      for (const envelope of [car,bike]) {
        const line = envelope.querySelector('[data-envelope-line]');
        const start = envelope === car ? .05 : .39, end = envelope === car ? .17 : .53;
        run(line, [{strokeDasharray:'1',strokeDashoffset:'1',offset:0},{strokeDashoffset:'1',offset:start},{strokeDashoffset:'0',offset:end},{strokeDashoffset:'0',offset:1}]);
      }
    };
    const sync = () => {
      replay.hidden = reduced.matches;
      if (reduced.matches) { cancel(); return; }
      for (const a of animations) {
        if (document.hidden || !visible) { if (a.playState === 'running') a.pause(); }
        else if (a.playState === 'paused') a.play();
      }
    };
    replay.addEventListener('click', play);
    reduced.addEventListener('change', sync);
    document.addEventListener('visibilitychange', sync);
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(entries => { visible = entries[0].isIntersecting; if (visible && !started && !reduced.matches) play(); sync(); }, {threshold:.45}).observe(seatBrand);
    } else { visible = true; }
    sync();
  }

  const exampleStateKey = 'publicJourneyExamplesV1';
  const examples = [];

  function savedExamples() {
    const saved = history.state?.[exampleStateKey];
    return saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {};
  }

  function rememberExamples() {
    try {
      const prior = history.state;
      if (prior !== null && (typeof prior !== 'object' || Array.isArray(prior))) return;
      const saved = Object.fromEntries(examples.map(item => [item.kind, item.container.dataset.exampleState]));
      history.replaceState({ ...(prior || {}), [exampleStateKey]: saved }, '');
    } catch { /* Examples still work when history writes are unavailable. */ }
  }

  function measure() {
    const scroll = window.scrollY;
    geometry = stages.map(stage => {
      const rect = stage.getBoundingClientRect();
      return { top: rect.top + scroll, height: rect.height };
    });
    for (const layer of layers) {
      const rect = layer.node.getBoundingClientRect();
      layer.center = rect.top + scroll + rect.height / 2 - (reduced.matches ? 0 : layer.offset);
    }
    needsMeasure = false;
  }

  function render() {
    frame = 0;
    if (document.hidden) return;
    if (needsMeasure) measure();
    const viewport = Math.max(1, window.innerHeight);
    const focus = window.scrollY + Math.min(viewport * .42, 320);
    let index = 0;
    for (let i = 1; i < geometry.length; i++) {
      if (focus >= geometry[i].top) index = i;
    }
    const lastStage = geometry[geometry.length - 1];
    if (focus >= geometry[0].top && focus <= lastStage.top + lastStage.height) {
      journey.dataset.lastViewedScene = names[index];
    }
    if (index !== active) {
      active = index;
      journey.dataset.activeScene = names[index];
      journey.style.setProperty('--scene-index', String(index));
      stages.forEach((stage, i) => { stage.dataset.sceneActive = String(i === index); });
      stageLinks.forEach(link => {
        if (link.dataset.stageJump === names[index]) link.setAttribute('aria-current', 'step');
        else link.removeAttribute('aria-current');
      });
    }
    const start = geometry[index].top;
    const end = geometry[index + 1]?.top ?? start + geometry[index].height;
    const progress = Math.max(0, Math.min(1, (focus - start) / Math.max(1, end - start)));
    journey.style.setProperty('--scene-progress', progress.toFixed(4));
    journey.dataset.sceneMotion = reduced.matches ? 'static' : 'scroll';
    for (const layer of layers) {
      const offset = reduced.matches ? 0 : Math.max(-8, Math.min(8, (window.scrollY + viewport / 2 - layer.center) / viewport * 8));
      if (offset !== layer.offset || !layer.node.style.translate) {
        layer.offset = offset;
        layer.node.style.translate = `0 ${offset.toFixed(2)}px`;
      }
    }
  }

  function schedule(measureAgain = false) {
    if (measureAgain) needsMeasure = true;
    if (!frame && !document.hidden) frame = requestAnimationFrame(render);
  }

  function example(kind, choices) {
    const container = journey.querySelector(`[data-${kind}-demo]`);
    if (!container) return;
    const buttons = [...container.querySelectorAll(`[data-${kind}-state]`)];
    const panels = [...container.querySelectorAll(`[data-${kind}-panel]`)];
    const attribute = `data-${kind}-state`;
    const panelAttribute = `data-${kind}-panel`;
    if (!choices.every(choice => buttons.some(button => button.getAttribute(attribute) === choice) && panels.some(panel => panel.getAttribute(panelAttribute) === choice))) return;
    function select(choice) {
      if (!choices.includes(choice)) return;
      container.dataset.exampleState = choice;
      buttons.forEach(button => button.setAttribute('aria-pressed', String(button.getAttribute(attribute) === choice)));
      panels.forEach(panel => { panel.hidden = panel.getAttribute(panelAttribute) !== choice; });
      schedule(true);
    }
    container.addEventListener('click', event => {
      const button = event.target instanceof Element ? event.target.closest(`[data-${kind}-state]`) : null;
      if (!button || !container.contains(button) || button.disabled) return;
      select(button.getAttribute(attribute));
      rememberExamples();
    });
    // Native buttons already support keyboard Enter/Space; no custom keyboard trap.
    const saved = savedExamples()[kind];
    select(choices.includes(saved) ? saved : choices[0]);
    examples.push({ kind, choices, select, container });
    container.dataset.exampleEnhanced = 'true';
    for (const controls of container.querySelectorAll('[data-example-controls]')) controls.hidden = false;
  }

  // Exactly two people: driver follows the full route; passenger joins and leaves once.
  const story = journey.querySelector('[data-ride-story]');
  if (story && 'IntersectionObserver' in window && typeof Element.prototype.animate === 'function') {
    const driver=story.querySelector('[data-story-driver]'), passenger=story.querySelector('[data-story-passenger]');
    const path=story.querySelector('[data-owner-path]'), replay=story.querySelector('[data-story-replay]');
    let visible=false, started=false, animations=[];
    const length=path.getTotalLength();
    const atY=y=>{let best=0, distance=Infinity;for(let i=0;i<=400;i++){const d=Math.abs(path.getPointAtLength(length*i/400).y-y);if(d<distance){distance=d;best=i/400;}}return best;};
    const pickup=atY(137),dropoff=atY(313);
    const driverFrames=[], passengerFrames=[];
    for(let i=0;i<=200;i++){
      const t=i/200;
      const progress=t<.22?pickup*t/.22:t<.30?pickup:t<.66?pickup+(dropoff-pickup)*(t-.30)/.36:t<.74?dropoff:dropoff+(1-dropoff)*(t-.74)/.26;
      const p=path.getPointAtLength(length*progress);
      let x=121,y=137;
      if(t>=.22&&t<.30){x=121+(104-121)*(t-.22)/.08;}
      else if(t>=.30&&t<.66){x=p.x+44;y=p.y;}
      else if(t>=.66&&t<.74){x=104+(121-104)*(t-.66)/.08;y=313;}
      else if(t>=.74){y=313;}
      driverFrames.push({transform:`translate(${p.x}px,${p.y}px)`,offset:t});
      passengerFrames.push({transform:`translate(${x}px,${y}px)`,offset:t});
    }
    function stop(){for(const a of animations)a.cancel();animations=[];story.dataset.storyPlaying='false';}
    function play(){if(reduced.matches)return;stop();started=true;story.dataset.storyPlaying='true';const options={duration:6800,fill:'both',easing:'linear'};animations=[driver.animate(driverFrames,options),passenger.animate(passengerFrames,options)];animations[0].onfinish=()=>{story.dataset.storyPlaying='false';};update();}
    function update(){replay.hidden=reduced.matches;if(reduced.matches){stop();return;}if(visible&&!document.hidden&&!started)play();for(const a of animations){if(a.playState==='finished')continue;if(visible&&!document.hidden)a.play();else a.pause();}}
    replay.addEventListener('click',play);
    new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting===true;update();},{threshold:.35}).observe(story);
    reduced.addEventListener('change',update);document.addEventListener('visibilitychange',update);
    window.addEventListener('pagehide',()=>animations.forEach(a=>{if(a.playState!=='finished')a.pause();}));window.addEventListener('pageshow',update);update();
  }

  example('agreement', ['pending', 'accepted']);
  example('location', ['stopped', 'sharing']);
  rememberExamples();
  journey.dataset.scenesEnhanced = 'true';
  window.addEventListener('scroll', () => schedule(), { passive: true });
  window.addEventListener('resize', () => schedule(true), { passive: true });
  window.addEventListener('pageshow', () => schedule(true));
  window.addEventListener('hashchange', () => { rememberExamples(); schedule(true); });
  window.addEventListener('popstate', () => {
    const saved = savedExamples();
    for (const item of examples) {
      if (item.choices.includes(saved[item.kind])) item.select(saved[item.kind]);
    }
    schedule(true);
  });
  window.addEventListener('pagehide', () => { if (frame) cancelAnimationFrame(frame); frame = 0; });
  document.addEventListener('visibilitychange', () => schedule(true));
  journey.addEventListener('toggle', () => schedule(true), true);
  reduced.addEventListener('change', () => schedule(true));
  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(() => schedule(true));
    observer.observe(journey);
    for (const stage of stages) observer.observe(stage);
  }
  document.fonts?.ready.then(() => schedule(true));
  document.fonts?.addEventListener?.('loadingdone', () => schedule(true));
  schedule(true);
})();
