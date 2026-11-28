/**
 * Quiz en direct : écran projeté (data-mode="hote") et téléphone de l'élève (data-mode="eleve").
 * L'état vient du serveur toutes les secondes ; aucun WebSocket nécessaire.
 */
(function () {
  'use strict';
  var app = document.getElementById('directApp');
  if (!app) return;
  var mode = app.getAttribute('data-mode');
  var urlEtat = app.getAttribute('data-etat');
  var urlAction = app.getAttribute('data-action');
  var csrf = app.getAttribute('data-csrf');
  var scene = document.getElementById('directScene');
  var dernier = '';         // empreinte du dernier rendu : on ne redessine que si l'état change
  var etat = null;
  var minuteur = null;
  var envoi = false;

  function el(tag, cls, texte) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (texte !== undefined && texte !== null) n.textContent = texte;
    return n;
  }
  function maths(n) { if (window.renderMath) window.renderMath(n); }
  function post(url, data) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
      body: JSON.stringify(data)
    }).then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.error || 'Erreur'); return d; }); });
  }
  function bouton(texte, cls, action) {
    var b = el('button', 'direct-btn ' + (cls || ''), texte);
    b.type = 'button';
    b.addEventListener('click', action);
    return b;
  }

  // ---------- Minuteur (affiché localement entre deux interrogations) ----------
  var finQuestion = 0;
  function majMinuteur() {
    var reste = Math.max(0, (finQuestion - Date.now()) / 1000);
    var barre = document.getElementById('directTemps');
    var chiffre = document.getElementById('directSecondes');
    if (barre && etat) barre.style.width = (100 * reste / etat.seconds) + '%';
    if (chiffre) chiffre.textContent = Math.ceil(reste);
  }

  // ---------- Écran projeté ----------
  function agir(action) {
    if (envoi) return;
    envoi = true;
    post(urlAction, { action: action }).then(afficher).catch(function (e) { window.alert(e.message); })
      .then(function () { envoi = false; });
  }

  function choixNode(c, avecCompte, total) {
    var b = el('div', 'direct-choix couleur-' + c.couleur + (c.correct === true ? ' est-juste' : c.correct === false ? ' est-faux' : ''));
    b.append(el('span', 'direct-lettre', c.lettre));
    var t = el('span', 'direct-texte', c.text);
    b.append(t);
    if (avecCompte) {
      var barre = el('span', 'direct-barre');
      barre.style.width = (total ? 100 * (c.count || 0) / total : 0) + '%';
      b.append(barre, el('span', 'direct-compte', String(c.count || 0)));
    }
    return b;
  }

  function classementNode(lignes, titre) {
    var box = el('div', 'direct-classement');
    if (titre) box.append(el('h2', '', titre));
    var ol = el('ol');
    lignes.forEach(function (l, i) {
      var li = el('li', i < 3 ? 'podium-' + (i + 1) : '');
      li.append(el('span', 'direct-rang', String(i + 1)), el('span', 'direct-nom', l.name), el('span', 'direct-points', l.score + ' pts'));
      ol.append(li);
    });
    box.append(ol);
    return box;
  }

  function rendreHote(d) {
    scene.textContent = '';
    document.getElementById('directJoueurs').textContent = d.participants + ' joueur' + (d.participants > 1 ? 's' : '');
    if (d.state === 'attente') {
      var box = el('div', 'direct-attente');
      box.append(el('p', 'direct-consigne', 'Sur ton téléphone : EduBac → Quiz en direct, puis le code'));
      box.append(el('div', 'direct-code-geant', d.code.slice(0, 3) + ' ' + d.code.slice(3)));
      var noms = el('div', 'direct-noms');
      (d.joined || []).forEach(function (n) { noms.append(el('span', 'direct-nom-puce', n)); });
      if (!(d.joined || []).length) noms.append(el('span', 'direct-vide', 'En attente des élèves…'));
      box.append(noms);
      box.append(bouton('▶ Commencer', 'principal', function () { agir('demarrer'); }));
      scene.append(box);
      return;
    }
    if (d.state === 'fini') {
      var fin = el('div', 'direct-fin');
      fin.append(el('h1', '', '🏆 Classement final'));
      fin.append(classementNode(d.leaderboard || []));
      var lien = el('a', 'direct-btn', 'Retour à mes quiz');
      lien.href = app.getAttribute('data-retour');
      fin.append(lien);
      scene.append(fin);
      return;
    }
    var q = d.question;
    var tete = el('div', 'direct-tete');
    tete.append(el('span', 'direct-num', 'Question ' + (d.index + 1) + ' / ' + d.total));
    if (d.state === 'question') {
      tete.append(el('span', 'direct-repondu', (d.answered || 0) + ' / ' + d.participants + ' réponses'));
      var sec = el('span', 'direct-secondes');
      sec.id = 'directSecondes';
      tete.append(sec);
    }
    scene.append(tete);
    if (d.state === 'question') {
      var piste = el('div', 'direct-piste');
      var barre = el('div', 'direct-temps');
      barre.id = 'directTemps';
      piste.append(barre);
      scene.append(piste);
    }
    var enonce = el('div', 'direct-enonce', q.text);
    scene.append(enonce);
    var grille = el('div', 'direct-grille');
    var total = (q.choices || []).reduce(function (s, c) { return s + (c.count || 0); }, 0);
    q.choices.forEach(function (c) { grille.append(choixNode(c, d.state === 'resultats', total)); });
    scene.append(grille);
    var pied = el('div', 'direct-pied');
    if (d.state === 'question') {
      pied.append(bouton('Afficher la réponse', '', function () { agir('reveler'); }));
    } else {
      if (q.regle || q.solution) {
        var expl = el('div', 'direct-explication');
        if (q.regle) expl.append(el('p', '', '📘 ' + q.regle));
        if (q.solution) expl.append(el('p', '', '✏️ ' + q.solution));
        pied.append(expl);
      }
      if (d.leaderboard && d.leaderboard.length) pied.append(classementNode(d.leaderboard, 'Top 5'));
      pied.append(bouton(d.index + 1 < d.total ? 'Question suivante →' : 'Classement final 🏆', 'principal', function () { agir('suivant'); }));
    }
    scene.append(pied);
    maths(scene);
  }

  // ---------- Téléphone de l'élève ----------
  function repondre(choix) {
    if (envoi) return;
    envoi = true;
    post(app.getAttribute('data-repondre'), { choice: choix }).then(afficher)
      .catch(function (e) { var m = document.getElementById('directMessage'); if (m) m.textContent = e.message; })
      .then(function () { envoi = false; });
  }

  function rendreEleve(d) {
    scene.textContent = '';
    var score = el('div', 'direct-score', d.score + ' pts');
    scene.append(score);
    if (d.state === 'attente') {
      var a = el('div', 'direct-message-grand');
      a.append(el('div', 'direct-emoji', '🎮'), el('p', '', 'Tu es dans la partie !'), el('p', 'petit', 'Regarde le tableau : le professeur va commencer.'));
      scene.append(a);
      return;
    }
    if (d.state === 'fini') {
      var f = el('div', 'direct-message-grand');
      f.append(el('div', 'direct-emoji', d.rank === 1 ? '🥇' : d.rank === 2 ? '🥈' : d.rank === 3 ? '🥉' : '🏁'));
      f.append(el('p', '', (d.rank ? d.rank + (d.rank === 1 ? 'er' : 'e') + ' sur ' + d.players : 'Partie terminée')));
      f.append(el('p', 'petit', d.score + ' points'));
      scene.append(f);
      return;
    }
    var q = d.question;
    var tete = el('div', 'direct-tete');
    tete.append(el('span', 'direct-num', (d.index + 1) + ' / ' + d.total));
    if (d.state === 'question' && !d.answer) {
      var sec = el('span', 'direct-secondes');
      sec.id = 'directSecondes';
      tete.append(sec);
    }
    scene.append(tete);
    if (d.state === 'question' && !d.answer) {
      var piste = el('div', 'direct-piste');
      var barre = el('div', 'direct-temps');
      barre.id = 'directTemps';
      piste.append(barre);
      scene.append(piste);
    }
    scene.append(el('div', 'direct-enonce petit', q.text));
    if (d.state === 'question' && !d.answer) {
      var grille = el('div', 'direct-grille eleve');
      q.choices.forEach(function (c) {
        var b = el('button', 'direct-choix couleur-' + c.couleur);
        b.type = 'button';
        b.append(el('span', 'direct-lettre', c.lettre), el('span', 'direct-texte', c.text));
        b.addEventListener('click', function () { repondre(c.id); });
        grille.append(b);
      });
      scene.append(grille);
      var msg = el('p', 'direct-erreur');
      msg.id = 'directMessage';
      scene.append(msg);
    } else if (d.state === 'question') {
      var att = el('div', 'direct-message-grand');
      att.append(el('div', 'direct-emoji', '⏳'), el('p', '', 'Réponse envoyée'), el('p', 'petit', 'Attends la correction au tableau.'));
      scene.append(att);
    } else {
      var r = el('div', 'direct-message-grand ' + (d.answer ? (d.answer.correct ? 'juste' : 'faux') : 'faux'));
      if (!d.answer) r.append(el('div', 'direct-emoji', '⌛'), el('p', '', 'Pas de réponse'));
      else if (d.answer.correct) r.append(el('div', 'direct-emoji', '✅'), el('p', '', 'Juste ! +' + d.answer.points + ' pts'));
      else r.append(el('div', 'direct-emoji', '❌'), el('p', '', 'Raté'));
      var bonne = q.choices.filter(function (c) { return c.correct; })[0];
      if (bonne && !(d.answer && d.answer.correct)) r.append(el('p', 'petit', 'Bonne réponse : ' + bonne.lettre + ' — ' + bonne.text));
      if (d.rank) r.append(el('p', 'petit', 'Tu es ' + d.rank + (d.rank === 1 ? 'er' : 'e') + ' sur ' + d.players));
      scene.append(r);
    }
    maths(scene);
  }

  // ---------- Boucle ----------
  function afficher(d) {
    etat = d;
    if (d.state === 'question') finQuestion = Date.now() + d.remaining * 1000;
    var empreinte = JSON.stringify([d.state, d.index, d.answered, d.participants, d.joined, d.answer, d.score, d.rank, d.leaderboard]);
    if (empreinte !== dernier) {
      dernier = empreinte;
      if (mode === 'hote') rendreHote(d); else rendreEleve(d);
    }
    majMinuteur();
  }
  function interroger() {
    fetch(urlEtat, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(afficher)
      .catch(function () { /* réseau : on réessaie au tour suivant */ })
      .then(function () {
        var delai = etat && etat.state === 'fini' ? 0 : etat && etat.state === 'attente' ? 1500 : 1000;
        if (delai) setTimeout(interroger, delai);
      });
  }
  setInterval(majMinuteur, 200);
  interroger();

  if (mode === 'hote') {
    document.addEventListener('keydown', function (e) {
      if (!etat || etat.state === 'fini' || e.target.closest('input, textarea')) return;
      if (e.key === ' ' || e.key === 'ArrowRight' || e.key === 'Enter') {
        e.preventDefault();
        agir(etat.state === 'question' ? 'reveler' : etat.state === 'attente' ? 'demarrer' : 'suivant');
      }
    });
    var plein = document.getElementById('directPleinEcran');
    if (plein) plein.addEventListener('click', function () {
      if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen();
    });
    var stop = document.getElementById('directTerminer');
    if (stop) stop.addEventListener('click', function () {
      if (window.confirm('Terminer la partie maintenant ?')) agir('terminer');
    });
  }
})();
