/* Progressive public-page controls. All explanations and answers are server rendered. */
(() => {
  const journey = document.querySelector('[data-feature-journey]');
  if (journey) {
    const stops = [...journey.querySelectorAll('[data-feature-stop]')];
    const links = [...journey.querySelectorAll('[data-feature-link]')];
    const list = journey.querySelector('.journey-stops');
    const track = journey.querySelector('.journey-track');
    const progress = journey.querySelector('.journey-progress');
    const cursor = journey.querySelector('.journey-cursor');
    const directory = journey.querySelector('.journey-directory');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    const depthLayers = [...document.querySelectorAll('[data-depth-motion]')].map(node => ({ node, center: 0, offset: 0 }));
    const directoryStateKey = 'publicFeatureJourneyDirectoryOpen';
    const notesStateKey = 'publicFeatureJourneyNotesOpen';
    const notes = stops.map(stop => ({ id: stop.dataset.featureStop, node: stop.querySelector('.feature-notes') })).filter(note => note.node);
    const noteIds = new Set(notes.map(note => note.id));
    function restoreJourneyState(initial = false) {
      const saved = history.state?.[directoryStateKey];
      if (typeof saved === 'boolean') directory.open = saved;
      else if (initial) directory.open = window.innerWidth > 900;
      const savedNotes = history.state?.[notesStateKey];
      if (Array.isArray(savedNotes) && savedNotes.length <= notes.length && new Set(savedNotes).size === savedNotes.length && savedNotes.every(id => typeof id === 'string' && noteIds.has(id))) {
        for (const note of notes) note.node.open = savedNotes.includes(note.id);
      }
    }
    function rememberJourneyState() {
      try {
        const prior = history.state;
        if (prior !== null && typeof prior !== 'object') return;
        history.replaceState({ ...(prior || {}), [directoryStateKey]: directory.open, [notesStateKey]: notes.filter(note => note.node.open).map(note => note.id) }, '');
      } catch { /* Navigation remains usable when history writes are unavailable. */ }
    }
    restoreJourneyState(true);
    let anchors = [];
    let trackLength = 0;
    let activeIndex = -1;
    let lastViewedFeature = null;
    let frame = 0;
    let needsMeasure = true;
    function measure() {
      const scroll = window.scrollY;
      const listTop = list.getBoundingClientRect().top + scroll;
      anchors = stops.map(stop => {
        const node = stop.querySelector('.feature-node').getBoundingClientRect();
        return node.top + scroll + node.height / 2;
      });
      trackLength = Math.max(0, anchors[anchors.length - 1] - anchors[0]);
      track.style.top = `${anchors[0] - listTop}px`;
      track.style.height = `${trackLength}px`;
      for (const layer of depthLayers) {
        const rect = layer.node.getBoundingClientRect();
        layer.center = rect.top + scroll + rect.height / 2 - (reduced.matches ? 0 : layer.offset);
      }
      needsMeasure = false;
    }
    function renderJourney() {
      frame = 0;
      if (needsMeasure) measure();
      if (!anchors.length) return;
      for (const layer of depthLayers) {
        layer.offset = reduced.matches ? 0 : Math.max(-8, Math.min(8, (window.scrollY + window.innerHeight / 2 - layer.center) / window.innerHeight * 8));
        layer.node.style.translate = `0 ${layer.offset.toFixed(2)}px`;
      }
      const focus = window.scrollY + Math.min(window.innerHeight * .42, 320);
      const distance = Math.max(0, Math.min(trackLength, focus - anchors[0]));
      progress.style.transform = `scaleY(${reduced.matches ? 1 : trackLength ? distance / trackLength : 0})`;
      cursor.style.transform = `translate3d(0,${distance}px,0)`;
      let nearest = 0;
      for (let i = 1; i < anchors.length; i++) {
        if (Math.abs(anchors[i] - focus) < Math.abs(anchors[nearest] - focus)) nearest = i;
      }
      if (focus >= anchors[0] && focus <= anchors[anchors.length - 1] + window.innerHeight * .5) {
        lastViewedFeature = stops[nearest].dataset.featureStop;
      }
      if (nearest !== activeIndex) {
        activeIndex = nearest;
        stops.forEach((stop, i) => {
          stop.toggleAttribute('data-active', i === nearest);
          stop.toggleAttribute('data-reached', i < nearest);
        });
        links.forEach((link, i) => {
          if (i === nearest) link.setAttribute('aria-current', 'step');
          else link.removeAttribute('aria-current');
        });
      }
      journey.classList.add('journey-enhanced');
    }
    function schedule(measureAgain = false) {
      if (measureAgain) needsMeasure = true;
      if (!frame) frame = requestAnimationFrame(renderJourney);
    }
    window.addEventListener('scroll', () => schedule(), { passive: true });
    window.addEventListener('resize', () => schedule(true), { passive: true });
    reduced.addEventListener('change', () => schedule(true));
    directory.addEventListener('toggle', () => { rememberJourneyState(); schedule(true); });
    for (const note of notes) note.node.addEventListener('toggle', () => { rememberJourneyState(); schedule(true); });
    window.addEventListener('hashchange', rememberJourneyState);
    window.addEventListener('popstate', () => { restoreJourneyState(); schedule(true); });
    rememberJourneyState();
    for (const languageLink of document.querySelectorAll('.language-switch a[lang]')) {
      languageLink.addEventListener('click', () => {
        const destination = new URL(languageLink.href, location.href);
        const sceneRoot = document.querySelector('[data-five-stage-journey]');
        const scene = sceneRoot?.dataset.lastViewedScene;
        const stage = scene && [...sceneRoot.querySelectorAll('[data-journey-stage]')]
          .find(node => node.dataset.journeyStage === scene);
        const feature = stops.find(node => node.dataset.featureStop === lastViewedFeature);
        if (stage) {
          const requestedStage = location.hash === `#stage-${scene}`;
          const featureInStage = feature?.closest('[data-journey-stage]') === stage;
          destination.hash = requestedStage || !featureInStage
            ? `stage-${scene}` : `feature-${lastViewedFeature}`;
        } else {
          destination.hash = lastViewedFeature ? `feature-${lastViewedFeature}` : '';
        }
        languageLink.href = destination.href;
      });
    }
    if ('ResizeObserver' in window) {
      const observer = new ResizeObserver(() => schedule(true));
      observer.observe(list);
      const hero = document.querySelector('.layered-hero');
      if (hero) observer.observe(hero);
      for (const stop of stops) observer.observe(stop);
    }
    document.fonts?.ready.then(() => schedule(true));
    schedule(true);
  }
  const guide = document.querySelector('[data-role-guide]');
  if (guide) {
    const switcher = guide.querySelector('[data-role-switch]');
    const tabs = [...guide.querySelectorAll('[data-role-tab]')];
    const panels = [...guide.querySelectorAll('[data-role-panel]')];
    function selectRole(role, focus = false, animate = false) {
      for (const tab of tabs) {
        const selected = tab.dataset.roleTab === role;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
        if (selected && focus) tab.focus();
      }
      for (const panel of panels) {
        panel.hidden = panel.dataset.rolePanel !== role;
        panel.setAttribute('role', 'tabpanel');
        panel.setAttribute('aria-labelledby', panel.dataset.rolePanel + '-tab');
        panel.tabIndex = 0;
        panel.classList.remove('is-changing');
        if (!panel.hidden && animate) { void panel.offsetWidth; panel.classList.add('is-changing'); }
      }
    }
    switcher.hidden = false;
    switcher.addEventListener('click', event => {
      const tab = event.target.closest('[data-role-tab]');
      if (tab) selectRole(tab.dataset.roleTab, false, true);
    });
    switcher.addEventListener('keydown', event => {
      const index = tabs.indexOf(document.activeElement);
      if (index < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      selectRole(tabs[next].dataset.roleTab, true, true);
    });
    const roleFromHash = () => selectRole(location.hash === '#owner-steps' ? 'owner' : 'rider');
    roleFromHash();
    window.addEventListener('hashchange', () => {
      if (['#owner-steps', '#rider-steps'].includes(location.hash)) roleFromHash();
    });
  }
  const root = document.querySelector('[data-faq-root]');
  if (!root) return;
  const form = root.querySelector('[data-faq-search]');
  const input = form.querySelector('input[type="search"]');
  const status = root.querySelector('[data-faq-status]');
  const empty = root.querySelector('[data-faq-empty]');
  const groups = [...root.querySelectorAll('[data-faq-group]')];
  const items = [...root.querySelectorAll('[data-faq-item]')];
  const normalize = value => value.normalize('NFKC').toLocaleLowerCase(document.documentElement.lang).trim();
  const searchable = new Map(items.map(item => [item, normalize(item.closest('[data-faq-group]').querySelector('h2').textContent + ' ' + item.textContent)]));
  const directoryLinks = [...document.querySelectorAll('[data-category-link]')];
  function updateCategory() {
    const visible = groups.filter(group => !group.hidden);
    let current = visible[0];
    for (const group of visible) { if (group.getBoundingClientRect().top <= 170) current = group; }
    for (const link of directoryLinks) {
      if (link.dataset.categoryLink === current?.id) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    }
  }
  let scrollPending = false;
  window.addEventListener('scroll', () => {
    if (scrollPending) return;
    scrollPending = true;
    requestAnimationFrame(() => { scrollPending = false; updateCategory(); });
  }, { passive: true });
  let priorOpen = null;
  function filter() {
    const query = normalize(input.value);
    const words = query.split(/\s+/u).filter(Boolean);
    if (query && !priorOpen) priorOpen = new Map(items.map(item => [item, item.open]));
    let count = 0;
    for (const item of items) {
      const match = !query || words.every(word => searchable.get(item).includes(word));
      item.hidden = !match;
      if (match) count++;
      if (query) item.open = match;
      else if (priorOpen) item.open = priorOpen.get(item);
    }
    if (!query) priorOpen = null;
    for (const group of groups) group.hidden = ![...group.querySelectorAll('[data-faq-item]')].some(item => !item.hidden);
    empty.hidden = count !== 0;
    status.textContent = root.dataset.countLabel.replace('{count}', String(count));
    updateCategory();
  }
  form.hidden = false;
  form.addEventListener('submit', event => { event.preventDefault(); filter(); });
  input.addEventListener('input', filter);
  form.addEventListener('reset', event => { event.preventDefault(); input.value = ''; filter(); input.focus(); });
  function revealHash() {
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch { return; }
    const target = id && document.getElementById(id);
    if (!target || !root.contains(target)) return;
    if (input.value) { input.value = ''; filter(); }
    if (target.matches('[data-faq-item]')) target.open = true;
    target.scrollIntoView({ block: 'start' });
  }
  document.querySelector('.faq-directory')?.addEventListener('click', () => {
    if (input.value) { input.value = ''; filter(); }
  });
  window.addEventListener('hashchange', revealHash);
  filter();
  revealHash();
})();
