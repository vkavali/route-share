/* Compact requests use a quiet progress cue without repeating the brand mark. */
export function busyMark() {
  return '<span class="seatpal-loading-mark" aria-hidden="true"></span>';
}

// Call only for a user operation. Cleanup restores the original control state.
export function beginBusy(button, label, _startedAt = Date.now()) {
  if (!button || button.dataset.seatpalPending) return () => {};
  const before = button.innerHTML, disabled = button.disabled;
  button.dataset.seatpalPending = 'true';
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  button.innerHTML = busyMark();
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
