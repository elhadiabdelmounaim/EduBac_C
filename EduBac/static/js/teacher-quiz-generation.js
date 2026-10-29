(function () {
  'use strict';
  var form = document.getElementById('genForm');
  var button = document.getElementById('genBtn');
  var loading = document.getElementById('genLoading');
  if (!form || !button || !loading || !window.fetch) return;
  var running = false;
  function now() { return performance.timeOrigin + performance.now(); }

  // A replacement document reports reception AND a stabilized DOM, not a server estimate.
  try {
    var saved = JSON.parse(sessionStorage.getItem('edubacQuizTiming') || 'null');
    sessionStorage.removeItem('edubacQuizTiming');
    if (saved && now() - saved.started < 300000) {
      var report = function () {
        requestAnimationFrame(function () { requestAnimationFrame(function () {
          var csrf = form.querySelector('[name="csrfmiddlewaretoken"]');
          fetch(saved.url, {
            method: 'POST', credentials: 'same-origin', keepalive: true,
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf ? csrf.value : ''},
            body: JSON.stringify({
              http_headers_ms: saved.headers, html_received_ms: saved.received,
              dom_ready_ms: now() - saved.started
            })
          }).catch(function () {});
        }); });
      };
      if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', report, {once: true});
      else report();
    }
  } catch (_) { /* Storage disabled: generation remains functional. */ }

  form.addEventListener('submit', async function (event) {
    if (event.defaultPrevented) return; // Resource validation registered before this handler.
    var action = (event.submitter && event.submitter.value) || 'generate';
    if (action !== 'generate') return;
    event.preventDefault();
    if (running) return;
    running = true;
    var started = now();
    var payload = new FormData(form);
    payload.set('action', 'generate');
    var label = loading.querySelector('[data-gen-status]');
    loading.classList.remove('d-none');
    if (label) label.textContent = 'Préparation de la demande…';
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    var url = form.dataset.progressUrl;
    var controller = window.AbortController ? new AbortController() : null;
    var finished = false;
    var pollTimer;
    var deadline = window.setTimeout(function () {
      finished = true;
      if (controller) controller.abort();
      if (label) label.textContent = 'Délai maximal atteint. Vérifiez « Mes quiz » avant de relancer.';
      var recovery = document.getElementById('genRecovery');
      if (recovery) recovery.hidden = false;
    }, 150000);
    async function poll() {
      if (finished || !url) return;
      try {
        var response = await fetch(url, {
          credentials: 'same-origin', cache: 'no-store',
          signal: controller ? controller.signal : undefined
        });
        if (response.ok) {
          var status = await response.json();
          if (!finished && label && status.label) label.textContent = status.label;
        }
      } catch (_) { /* Polling is diagnostic; never resubmit a generation. */ }
      if (!finished) pollTimer = window.setTimeout(poll, 1000);
    }
    pollTimer = window.setTimeout(poll, 150);
    try {
      var response = await fetch(form.getAttribute('action') || window.location.href, {
        method: 'POST', body: payload, credentials: 'same-origin',
        signal: controller ? controller.signal : undefined,
        headers: {'X-Requested-With': 'XMLHttpRequest'}
      });
      var headersAt = now();
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }
      var type = response.headers.get('content-type') || '';
      if (!response.ok || !type.includes('text/html')) {
        var error = type.includes('application/json') ? await response.json() : {};
        throw new Error(error.error || 'Réponse du serveur indisponible.');
      }
      var html = await response.text();
      finished = true;
      if (label) label.textContent = 'Affichage du résultat validé…';
      try {
        sessionStorage.setItem('edubacQuizTiming', JSON.stringify({
          url: url, started: started, headers: headersAt - started, received: now() - started
        }));
      } catch (_) {}
      document.open();
      document.write(html);
      document.close();
    } catch (error) {
      if (label) label.textContent = error.name === 'AbortError'
        ? 'Délai maximal atteint. Vérifiez « Mes quiz » avant de relancer.'
        : (error.message === 'Failed to fetch'
          ? 'Connexion interrompue. Vérifiez « Mes quiz » avant de relancer.'
          : error.message);
      var recovery = document.getElementById('genRecovery');
      if (recovery) recovery.hidden = false;
    } finally {
      finished = true;
      window.clearTimeout(pollTimer);
      window.clearTimeout(deadline);
    }
  });
})();
