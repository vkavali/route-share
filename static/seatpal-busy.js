/* Clone the generator-checked startup geometry; never maintain another SVG copy. */
const source = document.querySelector('[data-seatpal-startup] svg');
const canonicalHero = source?.outerHTML || '';

export function busyMark(startedAt = Date.now()) {
  const elapsed = Math.max(0, Math.min(4400, Date.now() - startedAt));
  if (!canonicalHero) return '<img class="seatpal-loading-mark" src="/static/assets/seatpal/seat.svg" alt="" aria-hidden="true">';
  return `<span class="seatpal-startup-sequence seatpal-mini-sequence" data-animate aria-hidden="true" style="--seatpal-delay:-${elapsed}ms">${canonicalHero}</span>`;
}

// Call only for a user operation. Cleanup restores the original control state.
export function beginBusy(button, label, startedAt = Date.now()) {
  if (!button || button.dataset.seatpalPending) return () => {};
  const before = button.innerHTML, disabled = button.disabled;
  button.dataset.seatpalPending = 'true';
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  button.innerHTML = busyMark(startedAt);
  const status = document.createElement('span');
  status.setAttribute('role', 'status');
  status.textContent = label;
  button.append(status);
  let finished = false;
  return () => {
    if (finished) return;
    finished = true;
    button.innerHTML = before;
    button.disabled = disabled;
    button.removeAttribute('aria-busy');
    delete button.dataset.seatpalPending;
  };
}
