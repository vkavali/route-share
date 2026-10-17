(() => {
  if (location.pathname !== '/' || location.hash) return;
  const standaloneDisplay = typeof matchMedia === 'function' && matchMedia('(display-mode: standalone)').matches;
  const iosStandalone = typeof navigator !== 'undefined' && navigator.standalone === true;
  if (standaloneDisplay || iosStandalone) return;
  const query = new URLSearchParams(location.search);
  if (query.get('app') === '1') return;
  const lang = ['en', 'te'].includes(query.get('lang')) ? query.get('lang') : 'en';
  location.replace(`/welcome?lang=${lang}`);
})();
