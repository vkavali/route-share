/* Public route labels are a draft, never geocoded or submitted as a booking. */
(() => {
  const form = document.querySelector('[data-landing-search]');
  if (!form) return;
  const pickup = form.elements.namedItem('origin');
  const destination = form.elements.namedItem('destination');
  const error = form.querySelector('[data-landing-error]');
  const staticPreview = document.body.dataset.publicStaticPreview === 'true';
  const lang = form.dataset.lang === 'te' ? 'te' : 'en';
  function target(intent, labels = {}) {
    const url = staticPreview ? new URL(`https://seatpal.in/?lang=${lang}`) : new URL(form.dataset.appUrl, location.href);
    url.hash = '/login';
    if (!staticPreview && url.origin === location.origin) {
      const payload = {v:1, intent, ...labels};
      const bytes = new TextEncoder().encode(JSON.stringify(payload));
      const encoded = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
      url.hash += `~sp1:${encoded}`;
    }
    return url.href;
  }
  function labels() {
    return {originLabel: pickup.value.trim().slice(0,120), destinationLabel: destination.value.trim().slice(0,120)};
  }
  function showError(message, field) {
    error.textContent = message;
    error.hidden = false;
    field.setAttribute('aria-invalid', 'true');
    field.focus();
  }
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (staticPreview) { location.assign(target('search')); return; }
    pickup.removeAttribute('aria-invalid'); destination.removeAttribute('aria-invalid'); error.hidden = true;
    const draft = labels();
    if (!draft.originLabel || !draft.destinationLabel) { showError(form.dataset.emptyError, !draft.originLabel ? pickup : destination); return; }
    if (draft.originLabel.toLocaleLowerCase(lang).replace(/\s+/g,' ') === draft.destinationLabel.toLocaleLowerCase(lang).replace(/\s+/g,' ')) { showError(form.dataset.sameError, destination); return; }
    location.assign(target('search', draft));
  });
  form.noValidate = true;
  form.hidden = false;
  if (staticPreview) {
    pickup.required = false;
    destination.required = false;
    form.querySelector('.combined-form-note').textContent = form.dataset.staticNote;
  }
  for (const link of document.querySelectorAll('[data-landing-offer]')) {
    link.href = target('offer');
    link.addEventListener('click', event => {
      const draft = labels();
      if (draft.originLabel && draft.destinationLabel && draft.originLabel.toLocaleLowerCase(lang).replace(/\s+/g,' ') === draft.destinationLabel.toLocaleLowerCase(lang).replace(/\s+/g,' ')) { event.preventDefault(); showError(form.dataset.sameError, destination); return; }
      link.href = target('offer', Object.fromEntries(Object.entries(draft).filter(([,value]) => value)));
    });
  }
})();
