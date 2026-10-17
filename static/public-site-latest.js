/* Public FAQ controls. Landing content is server rendered and immediately visible. */
(() => {
  const greetingRoot = document.querySelector('[data-festival-greeting-root]');
  if (!greetingRoot) return;
  import('./festival-greetings.js').then(({ createFestivalGreeting, startFestivalGreetingUpdates }) => {
    const greeting = createFestivalGreeting();
    const lang = () => ['en', 'te', 'hi'].includes(document.documentElement.lang) ? document.documentElement.lang : 'en';
    const render = () => { greetingRoot.innerHTML = greeting.html(lang(), true); };
    greetingRoot.addEventListener('click', event => {
      const button = event.target.closest('[data-festival-dismiss]');
      if (button && greeting.dismiss(button.dataset.festivalDismiss)) render();
    });
    startFestivalGreetingUpdates({ onChange: render });
    render();
  }).catch(() => {});
})();
(() => {
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
