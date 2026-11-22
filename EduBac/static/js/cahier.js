/* Cahier de textes d'un niveau : sélection de séances (conservée d'une page à l'autre)
   et téléchargement de la sélection en un seul PDF. */
(function () {
  'use strict';
  var racine = document.getElementById('cahierNiveau');
  if (!racine) return;
  var cle = 'edubac-cahier-selection-' + racine.dataset.niveau;
  var barre = document.getElementById('cahierSelection');
  var compte = document.getElementById('cahierCompte');
  var lien = document.getElementById('cahierPdfSelection');
  var coches = Array.prototype.slice.call(document.querySelectorAll('.cahier-coche'));
  var choix = [];

  try { choix = JSON.parse(sessionStorage.getItem(cle) || '[]').filter(function (v) { return /^\d+$/.test(v); }); }
  catch (e) { choix = []; }

  function memoriser() {
    try { sessionStorage.setItem(cle, JSON.stringify(choix)); } catch (e) { /* navigation privée */ }
  }

  function majBarre() {
    var n = choix.length;
    barre.hidden = n === 0;
    compte.textContent = n + (n > 1 ? ' séances sélectionnées' : ' séance sélectionnée');
    lien.href = racine.dataset.pdf + '?' + choix.map(function (id) { return 'ids=' + id; }).join('&');
    coches.forEach(function (c) {
      c.closest('.cahier-seance').classList.toggle('choisie', c.checked);
    });
    document.body.classList.toggle('cahier-avec-selection', n > 0);
  }

  coches.forEach(function (c) {
    c.checked = choix.indexOf(c.value) >= 0;
    c.addEventListener('change', function () {
      var i = choix.indexOf(c.value);
      if (c.checked && i < 0) choix.push(c.value);
      if (!c.checked && i >= 0) choix.splice(i, 1);
      memoriser();
      majBarre();
    });
  });

  document.getElementById('cahierTout').addEventListener('click', function () {
    coches.forEach(function (c) {
      c.checked = true;
      if (choix.indexOf(c.value) < 0) choix.push(c.value);
    });
    memoriser();
    majBarre();
  });

  document.getElementById('cahierAucun').addEventListener('click', function () {
    coches.forEach(function (c) { c.checked = false; });
    choix = [];
    memoriser();
    majBarre();
  });

  majBarre();
})();
