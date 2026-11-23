/* Présence : tant que la page est ouverte et visible, une nabda par minute
   (l'administrateur voit qui est actif dans chaque classe). */
(function () {
  var script = document.currentScript;
  var url = script && script.dataset.url;
  var jeton = script && script.dataset.csrf;
  if (!url || !window.fetch) return;
  var derniere = Date.now();
  function battre() {
    if (document.visibilityState !== 'visible') return;
    derniere = Date.now();
    fetch(url, { method: 'POST', credentials: 'same-origin', keepalive: true,
      headers: { 'X-CSRFToken': jeton || '' } }).catch(function () {});
  }
  setInterval(battre, 60000);
  // Retour sur l'onglet après une absence : signaler tout de suite.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && Date.now() - derniere > 60000) battre();
  });
})();
