/* Signale à l'administration les erreurs JavaScript de cette page (au plus
 * 5 par page). Seuls le message, le fichier, la ligne et l'adresse de la page
 * sont envoyés : jamais ce que l'utilisateur a saisi. */
(function () {
  'use strict';
  var url = '/erreurs-client/', sent = 0, seen = {};
  if (navigator.webdriver) return;  // tests automatisés : pas d'alerte
  function report(message, source, line, column, stack) {
    message = String(message || '').slice(0, 300);
    if (!message || sent >= 5 || seen[message]) return;
    seen[message] = true;
    sent += 1;
    var body = JSON.stringify({ message: message, source: source || '', line: line || 0, column: column || 0,
      stack: String(stack || '').slice(0, 1500), page: location.pathname });
    try {
      if (navigator.sendBeacon && navigator.sendBeacon(url, new Blob([body], { type: 'application/json' }))) return;
      fetch(url, { method: 'POST', body: body, credentials: 'same-origin', keepalive: true,
        headers: { 'Content-Type': 'application/json' } }).catch(function () {});
    } catch (e) { /* jamais d'erreur en signalant une erreur */ }
  }
  window.addEventListener('error', function (event) {
    if (event.target && event.target !== window) return;  // image ou script non chargé
    report(event.message, event.filename, event.lineno, event.colno, event.error && event.error.stack);
  });
  window.addEventListener('unhandledrejection', function (event) {
    var reason = event.reason;
    if (reason && (reason.name === 'AbortError' || reason.status)) return;  // requête annulée ou refusée : déjà gérée
    report('Promesse rejetée : ' + (reason && reason.message ? reason.message : String(reason)), '', 0, 0, reason && reason.stack);
  });
})();
