/* route-share/static/polish.js
 * Progressive enhancement: toast notification system + API progress bar.
 * Loaded as a plain script before app.js — exposes window.showToast().
 */
(function () {
  'use strict';

  /* ─── Toast system ──────────────────────────────────────────── */

  const ICONS = { success: '✓', error: '✕', warning: '!', info: 'i' };

  function getContainer() {
    var el = document.getElementById('toast-container');
    if (!el) {
      el = document.createElement('div');
      el.id = 'toast-container';
      el.setAttribute('aria-live', 'assertive');
      el.setAttribute('aria-atomic', 'false');
      document.body.appendChild(el);
    }
    return el;
  }

  function dismiss(wrap) {
    if (wrap._leaving) return;
    wrap._leaving = true;
    wrap.classList.add('is-leaving');
    function remove() { if (wrap.parentNode) wrap.parentNode.removeChild(wrap); }
    wrap.addEventListener('animationend', remove, { once: true });
    setTimeout(remove, 500);
  }

  function showToast(message, type, opts) {
    type = type || 'info';
    opts = opts || {};
    var duration = opts.duration !== undefined ? opts.duration : 4500;
    var title    = opts.title || null;

    var c = getContainer();

    var wrap = document.createElement('div');
    wrap.className = 'toast toast--' + type;
    wrap.setAttribute('role', type === 'error' ? 'alert' : 'status');

    var icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = ICONS[type] || 'i';

    var body = document.createElement('div');
    body.className = 'toast-body';
    if (title) {
      var t = document.createElement('div');
      t.className = 'toast-title';
      t.textContent = title;
      body.appendChild(t);
    }
    var msg = document.createElement('div');
    msg.textContent = message;
    body.appendChild(msg);

    var close = document.createElement('button');
    close.className = 'toast-close';
    close.setAttribute('aria-label', 'Dismiss');
    close.textContent = '×';
    close.addEventListener('click', function (e) {
      e.stopPropagation();
      dismiss(wrap);
    });

    wrap.appendChild(icon);
    wrap.appendChild(body);
    wrap.appendChild(close);
    wrap.addEventListener('click', function () { dismiss(wrap); });

    c.appendChild(wrap);

    if (duration > 0) {
      setTimeout(function () { dismiss(wrap); }, duration);
    }
    return wrap;
  }

  /* ─── API progress bar ──────────────────────────────────────── */

  var _progressEl, _progressFill, _count = 0;

  function getProgress() {
    if (!_progressEl) {
      _progressEl  = document.createElement('div');
      _progressEl.id = 'nav-progress';
      _progressFill = document.createElement('div');
      _progressFill.id = 'nav-progress-fill';
      _progressEl.appendChild(_progressFill);
      document.body.appendChild(_progressEl);
    }
    return _progressEl;
  }

  function progressStart() {
    _count++;
    getProgress().classList.add('is-active');
  }

  function progressDone() {
    _count = Math.max(0, _count - 1);
    if (_count === 0) {
      getProgress().classList.remove('is-active');
    }
  }

  /* Wrap window.fetch to show progress on /api/ calls */
  var _origFetch = window.fetch;
  window.fetch = function () {
    var args  = Array.prototype.slice.call(arguments);
    var first = args[0];
    var url   = typeof first === 'string' ? first : (first && first.url) || '';
    var isApi = url.indexOf('/api/') !== -1;
    if (isApi) progressStart();
    return _origFetch.apply(this, args).finally(function () {
      if (isApi) progressDone();
    });
  };

  /* ─── Expose ─────────────────────────────────────────────────── */
  window.showToast     = showToast;
  window.progressStart = progressStart;
  window.progressDone  = progressDone;

})();
