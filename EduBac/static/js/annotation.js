/**
 * Correction d'une copie photographiée : un calque transparent par-dessus la page (stylo,
 * texte, tampons ✓ ✗, gomme), annulation, zoom. À l'enregistrement : le calque seul (pour
 * reprendre la correction plus tard) et la page corrigée (image + calque) pour l'élève.
 */
(function () {
  'use strict';
  var app = document.getElementById('annotation');
  if (!app) return;
  var fond = app.querySelector('[data-fond]');
  var dessin = app.querySelector('[data-dessin]');
  var feuille = app.querySelector('[data-feuille]');
  var zone = app.querySelector('[data-zone]');
  var etat = app.querySelector('[data-etat]');
  var ctx = dessin.getContext('2d');
  var MAX = 2400;                 // côté le plus long, en pixels : lisible et léger
  var outil = 'stylo', couleur = '#d32f2f', epaisseurs = [4, 8, 14], ie = 0;
  var zoom = 1, historique = [], modifie = false, trait = null;

  function dire(t) { etat.textContent = t || ''; }

  function charger(url) {
    return new Promise(function (ok, ko) {
      var img = new Image();
      img.onload = function () { ok(img); };
      img.onerror = ko;
      img.src = url;
    });
  }

  function ajuster() {
    var largeur = zone.clientWidth - 2;
    feuille.style.width = Math.round(largeur * zoom) + 'px';
  }

  charger(app.getAttribute('data-image')).then(function (img) {
    var echelle = Math.min(1, MAX / Math.max(img.naturalWidth, img.naturalHeight));
    var w = Math.round(img.naturalWidth * echelle), h = Math.round(img.naturalHeight * echelle);
    [fond, dessin].forEach(function (c) { c.width = w; c.height = h; });
    fond.getContext('2d').drawImage(img, 0, 0, w, h);
    ajuster();
    var calque = app.getAttribute('data-calque');
    if (calque) {
      return charger(calque + '&t=' + Date.now()).then(function (c) { ctx.drawImage(c, 0, 0, w, h); dire(''); })
        .catch(function () { dire(''); });
    }
    dire('');
  }).catch(function () { dire('Cette image ne peut pas être ouverte dans le navigateur.'); });

  // ---------- Outils ----------
  function choisir(bouton) {
    app.querySelectorAll('[data-outil]').forEach(function (b) { b.classList.toggle('est-actif', b === bouton); });
    outil = bouton.getAttribute('data-outil');
    if (bouton.getAttribute('data-couleur')) couleur = bouton.getAttribute('data-couleur');
    dessin.style.touchAction = outil === 'main' ? 'auto' : 'none';
    dessin.style.cursor = outil === 'main' ? 'grab' : outil === 'texte' ? 'text' : 'crosshair';
  }
  app.querySelectorAll('[data-outil]').forEach(function (b) { b.addEventListener('click', function () { choisir(b); }); });
  app.querySelector('[data-epaisseur]').addEventListener('click', function (e) {
    ie = (ie + 1) % epaisseurs.length;
    e.currentTarget.style.fontWeight = ['400', '700', '900'][ie];
    e.currentTarget.title = 'Épaisseur ' + (ie + 1) + '/3';
  });
  app.querySelectorAll('[data-zoom]').forEach(function (b) {
    b.addEventListener('click', function () {
      zoom = Math.max(0.5, Math.min(4, zoom * (b.getAttribute('data-zoom') === '1' ? 1.25 : 0.8)));
      ajuster();
    });
  });
  window.addEventListener('resize', ajuster);

  function memoriser() {
    historique.push(ctx.getImageData(0, 0, dessin.width, dessin.height));
    if (historique.length > 30) historique.shift();
    modifie = true;
  }
  app.querySelector('[data-annuler]').addEventListener('click', function () {
    var avant = historique.pop();
    if (avant) ctx.putImageData(avant, 0, 0);
  });
  app.querySelector('[data-effacer]').addEventListener('click', function () {
    if (!window.confirm('Effacer toute la correction de cette page ?')) return;
    memoriser();
    ctx.clearRect(0, 0, dessin.width, dessin.height);
  });

  // ---------- Dessin ----------
  function point(e) {
    var r = dessin.getBoundingClientRect();
    return { x: (e.clientX - r.left) * dessin.width / r.width, y: (e.clientY - r.top) * dessin.height / r.height };
  }
  function taille() { return epaisseurs[ie] * dessin.width / 1200; }

  function tampon(p, signe) {
    memoriser();
    var t = taille() * 9;
    ctx.save();
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = signe === '✓' ? '#2e7d32' : '#d32f2f';
    ctx.font = 'bold ' + t + 'px system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(signe, p.x, p.y);
    ctx.restore();
  }
  function texte(p) {
    var t = window.prompt('Texte à écrire sur la copie :');
    if (!t) return;
    memoriser();
    var corps = taille() * 6;
    ctx.save();
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = couleur;
    ctx.font = '600 ' + corps + 'px "Segoe Print", "Comic Sans MS", system-ui, sans-serif';
    ctx.textBaseline = 'top';
    t.split('\n').forEach(function (ligne, i) { ctx.fillText(ligne, p.x, p.y + i * corps * 1.2); });
    ctx.restore();
  }

  dessin.addEventListener('pointerdown', function (e) {
    if (outil === 'main') return;
    var p = point(e);
    if (outil === 'juste' || outil === 'faux') { tampon(p, outil === 'juste' ? '✓' : '✗'); return; }
    if (outil === 'texte') { texte(p); return; }
    e.preventDefault();
    dessin.setPointerCapture(e.pointerId);
    memoriser();
    trait = p;
    ctx.globalCompositeOperation = outil === 'gomme' ? 'destination-out' : 'source-over';
    ctx.strokeStyle = couleur;
    ctx.lineWidth = outil === 'gomme' ? taille() * 5 : taille();
    ctx.lineCap = ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ctx.lineTo(p.x + 0.1, p.y + 0.1);
    ctx.stroke();
  });
  dessin.addEventListener('pointermove', function (e) {
    if (!trait) return;
    var p = point(e);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    trait = p;
  });
  function finTrait() { trait = null; ctx.globalCompositeOperation = 'source-over'; }
  dessin.addEventListener('pointerup', finTrait);
  dessin.addEventListener('pointercancel', finTrait);

  // ---------- Enregistrer ----------
  function enBlob(canvas) {
    return new Promise(function (ok) { canvas.toBlob(ok, 'image/png'); });
  }
  var bouton = app.querySelector('[data-enregistrer-btn]');
  bouton.addEventListener('click', function () {
    bouton.disabled = true;
    dire('Enregistrement…');
    var compose = document.createElement('canvas');
    compose.width = fond.width;
    compose.height = fond.height;
    var c = compose.getContext('2d');
    c.drawImage(fond, 0, 0);
    c.drawImage(dessin, 0, 0);
    Promise.all([enBlob(dessin), enBlob(compose)]).then(function (blobs) {
      var fd = new FormData();
      fd.append('calque', blobs[0], 'calque.png');
      fd.append('annotee', blobs[1], 'corrigee.png');
      return fetch(app.getAttribute('data-enregistrer'), {
        method: 'POST', credentials: 'same-origin', body: fd,
        headers: { 'X-CSRFToken': app.getAttribute('data-csrf'), Accept: 'application/json' }
      });
    }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.d.error || 'Enregistrement impossible.');
        modifie = false;
        dire('✓ Correction enregistrée : l’élève voit sa copie corrigée.');
      })
      .catch(function (err) { dire(err.message || 'Enregistrement impossible (connexion ?).'); })
      .then(function () { bouton.disabled = false; });
  });
  window.addEventListener('beforeunload', function (e) { if (modifie) { e.preventDefault(); e.returnValue = ''; } });
})();
