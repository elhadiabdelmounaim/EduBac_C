/**
 * Outils de la messagerie : sondages rapides (salon de classe), mentions « @Prénom Nom »
 * (autocomplétion + surlignage) et éditeur de formules ∑ (palette LaTeX + aperçu).
 * Exposé sous window.EduBacChatOutils ; l'éditeur de formules s'installe tout seul sur
 * chaque zone de saisie marquée data-formules.
 */
(function () {
  'use strict';

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }
  function icon(name) {
    var i = el('i', 'bi ' + name);
    i.setAttribute('aria-hidden', 'true');
    return i;
  }
  function csrfOf() {
    var app = document.getElementById('chatApp');
    return (app && app.getAttribute('data-csrf')) || '';
  }
  function postJSON(url, data) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfOf(), Accept: 'application/json' },
      body: JSON.stringify(data || {})
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) throw new Error(d.error || 'Action impossible.');
        return d;
      });
    });
  }

  // ---------- Mentions : surlignage ----------
  function highlightMentions(container, mentions, userId) {
    if (!container || !mentions || !mentions.length) return;
    var noms = mentions.map(function (p) { return { id: p.id, texte: '@' + p.name }; })
      .sort(function (a, b) { return b.texte.length - a.texte.length; });
    var walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    var noeuds = [];
    while (walker.nextNode()) noeuds.push(walker.currentNode);
    noeuds.forEach(function (noeud) {
      var texte = noeud.nodeValue;
      if (texte.indexOf('@') < 0) return;
      var fragment = document.createDocumentFragment();
      var i = 0, trouve = false;
      while (i < texte.length) {
        var meilleur = null;
        noms.forEach(function (n) {
          var pos = texte.indexOf(n.texte, i);
          if (pos >= 0 && (!meilleur || pos < meilleur.pos)) meilleur = { pos: pos, n: n };
        });
        if (!meilleur) break;
        if (meilleur.pos > i) fragment.append(texte.slice(i, meilleur.pos));
        var span = el('span', 'chat-mention' + (meilleur.n.id === userId ? ' is-me' : ''), meilleur.n.texte);
        fragment.append(span);
        i = meilleur.pos + meilleur.n.texte.length;
        trouve = true;
      }
      if (!trouve) return;
      if (i < texte.length) fragment.append(texte.slice(i));
      noeud.parentNode.replaceChild(fragment, noeud);
    });
  }

  // ---------- Mentions : autocomplétion ----------
  function mentionAutocomplete(input, membersUrl, userId) {
    var membres = null;
    var choisis = {};          // id → nom
    var liste = el('ul', 'chat-mention-list');
    liste.setAttribute('role', 'listbox');
    liste.hidden = true;
    var pill = input.closest('.chat-input-pill') || input.parentNode;
    pill.style.position = 'relative';
    pill.append(liste);
    var actif = 0, debut = -1, resultats = [];

    function charger() {
      if (membres) return Promise.resolve(membres);
      return fetch(membersUrl, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          membres = (d.members || []).filter(function (m) { return m.id !== userId; })
            .map(function (m) { return { id: m.id, name: m.name, role: m.role || '' }; });
          return membres;
        }).catch(function () { membres = []; return membres; });
    }
    function sansAccents(t) { return t.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
    function fermer() { liste.hidden = true; debut = -1; resultats = []; }
    function afficher() {
      liste.textContent = '';
      resultats.forEach(function (m, i) {
        var li = el('li', 'chat-mention-item' + (i === actif ? ' is-active' : ''));
        li.setAttribute('role', 'option');
        li.append(el('strong', '', m.name));
        if (m.role) li.append(el('small', '', ' · ' + m.role));
        li.addEventListener('mousedown', function (e) { e.preventDefault(); choisir(m); });
        liste.append(li);
      });
      liste.hidden = !resultats.length;
    }
    function choisir(m) {
      var avant = input.value.slice(0, debut);
      var apres = input.value.slice(input.selectionStart);
      var texte = '@' + m.name + ' ';
      input.value = avant + texte + apres;
      var pos = avant.length + texte.length;
      input.setSelectionRange(pos, pos);
      choisis[m.id] = m.name;
      fermer();
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    }
    input.addEventListener('input', function () {
      var pos = input.selectionStart;
      var avant = input.value.slice(0, pos);
      var match = /(^|\s)@([^\s@]{0,30}(?: [^\s@]{0,30})?)$/.exec(avant);
      if (!match) { fermer(); return; }
      debut = pos - match[2].length - 1;
      var q = sansAccents(match[2]);
      charger().then(function (ms) {
        resultats = ms.filter(function (m) { return !q || sansAccents(m.name).indexOf(q) >= 0; }).slice(0, 6);
        actif = 0;
        afficher();
      });
    });
    input.addEventListener('keydown', function (e) {
      if (liste.hidden) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        actif = (actif + (e.key === 'ArrowDown' ? 1 : -1) + resultats.length) % resultats.length;
        afficher();
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        e.stopImmediatePropagation();
        if (resultats[actif]) choisir(resultats[actif]);
      } else if (e.key === 'Escape') {
        fermer();
      }
    }, true);
    input.addEventListener('blur', function () { setTimeout(fermer, 150); });
    return {
      ids: function () {
        return Object.keys(choisis).filter(function (id) {
          return input.value.indexOf('@' + choisis[id]) >= 0;
        }).map(function (id) { return parseInt(id, 10); });
      },
      reset: function () { choisis = {}; fermer(); }
    };
  }

  // ---------- Sondages ----------
  function pollNode(m, onUpdated) {
    var p = m.poll;
    var box = el('div', 'chat-poll' + (p.closed ? ' is-closed' : ''));
    var tete = el('div', 'chat-poll-head');
    tete.append(icon('bi-bar-chart-fill'), ' ', el('strong', '', p.question));
    box.append(tete);
    p.options.forEach(function (o) {
      var b = el('button', 'chat-poll-option' + (o.mine ? ' is-mine' : ''));
      b.type = 'button';
      b.disabled = p.closed;
      b.setAttribute('aria-pressed', o.mine ? 'true' : 'false');
      var barre = el('span', 'chat-poll-bar');
      barre.style.width = o.percent + '%';
      var libelle = el('span', 'chat-poll-label', o.text);
      var chiffre = el('span', 'chat-poll-count', o.count + ' · ' + o.percent + ' %');
      b.append(barre, libelle, chiffre);
      if (o.names && o.names.length) b.title = o.names.join(', ');
      b.addEventListener('click', function () {
        postJSON('/chat/api/sondage/' + p.id + '/voter/', { option: o.index })
          .then(function (d) { if (onUpdated) onUpdated(d.message); })
          .catch(function (err) { window.alert(err.message); });
      });
      box.append(b);
    });
    var pied = el('div', 'chat-poll-foot');
    pied.append(el('span', '', p.total + ' vote' + (p.total > 1 ? 's' : '') + (p.closed ? ' · sondage clos' : '')));
    if (p.can_close) {
      var clore = el('button', 'chat-poll-close', p.closed ? 'Rouvrir' : 'Clore');
      clore.type = 'button';
      clore.addEventListener('click', function () {
        postJSON('/chat/api/sondage/' + p.id + '/clore/')
          .then(function (d) { if (onUpdated) onUpdated(d.message); })
          .catch(function (err) { window.alert(err.message); });
      });
      pied.append(clore);
    }
    box.append(pied);
    return box;
  }

  function pollDialog(classroomId, onCreated) {
    var dialog = document.getElementById('chatPollDialog');
    if (!dialog) return null;
    var form = dialog.querySelector('form');
    var options = dialog.querySelector('[data-options]');
    var erreur = dialog.querySelector('[data-erreur]');
    function ligne(valeur) {
      var input = el('input', 'form-control form-control-sm');
      input.name = 'option';
      input.maxLength = 120;
      input.placeholder = 'Choix ' + (options.children.length + 1);
      input.value = valeur || '';
      options.append(input);
    }
    function ouvrir(question, choix) {
      form.reset();
      options.textContent = '';
      (choix || ['', '']).forEach(ligne);
      form.elements.question.value = question || '';
      erreur.hidden = true;
      if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
      form.elements.question.focus();
    }
    dialog.querySelector('[data-ajouter]').addEventListener('click', function () {
      if (options.children.length < 6) ligne('');
    });
    dialog.querySelectorAll('[data-modele]').forEach(function (b) {
      b.addEventListener('click', function () {
        var modele = JSON.parse(b.getAttribute('data-modele'));
        ouvrir(modele.q, modele.o);
      });
    });
    dialog.querySelector('[data-annuler]').addEventListener('click', function () { dialog.close(); });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var choix = Array.prototype.map.call(options.querySelectorAll('input'), function (i) { return i.value; })
        .filter(function (v) { return v.trim(); });
      postJSON('/chat/api/classe/' + classroomId + '/sondage/', { question: form.elements.question.value, options: choix })
        .then(function (d) { dialog.close(); if (onCreated) onCreated(d.message); })
        .catch(function (err) { erreur.textContent = err.message; erreur.hidden = false; });
    });
    return { ouvrir: ouvrir };
  }

  // ---------- Éditeur de formules ∑ ----------
  var PALETTE = [
    ['Fraction', '\\frac{a}{b}', 'a/b'], ['Racine', '\\sqrt{x}', '√'], ['Puissance', 'x^{n}', 'xⁿ'],
    ['Indice', 'u_{n}', 'uₙ'], ['Vecteur', '\\vec{u}', 'u→'], ['Vecteur AB', '\\overrightarrow{AB}', 'AB→'],
    ['Produit scalaire', '\\vec{u}\\cdot\\vec{v}', 'u·v'], ['Norme', '\\|\\vec{u}\\|', '‖u‖'],
    ['Angle', '\\widehat{ABC}', 'Â'], ['Limite', '\\lim_{x \\to +\\infty} f(x)', 'lim'],
    ['Somme', '\\sum_{k=1}^{n} k', 'Σ'], ['Intégrale', '\\int_{a}^{b} f(x)\\,dx', '∫'],
    ['Infini', '\\infty', '∞'], ['Pi', '\\pi', 'π'], ['Appartient', '\\in', '∈'], ['Réels', '\\mathbb{R}', 'ℝ'],
    ['Inférieur ou égal', '\\leq', '≤'], ['Supérieur ou égal', '\\geq', '≥'], ['Différent', '\\neq', '≠'],
    ['Implique', '\\Rightarrow', '⇒'], ['Équivaut', '\\Leftrightarrow', '⇔'], ['Pour tout', '\\forall', '∀'],
    ['Il existe', '\\exists', '∃'], ['Delta', '\\Delta', 'Δ'], ['Alpha', '\\alpha', 'α'], ['Thêta', '\\theta', 'θ'],
    ['Cosinus', '\\cos', 'cos'], ['Sinus', '\\sin', 'sin'], ['Système', '\\begin{cases} x+y=1 \\\\ x-y=0 \\end{cases}', '{']
  ];

  function formula(input) {
    if (!input || input.dataset.formulesPret) return;
    input.dataset.formulesPret = '1';
    var pill = input.closest('.chat-input-pill') || input.parentNode;
    pill.style.position = 'relative';
    var bouton = el('button', 'chat-tool-btn chat-formula-btn');
    bouton.type = 'button';
    bouton.title = 'Insérer une formule';
    bouton.setAttribute('aria-label', 'Insérer une formule mathématique');
    bouton.setAttribute('aria-expanded', 'false');
    bouton.append(el('span', 'chat-formula-sigma', '∑'));
    input.parentNode.insertBefore(bouton, input);
    var panneau = el('div', 'chat-formula-panel');
    panneau.hidden = true;
    panneau.setAttribute('role', 'dialog');
    panneau.setAttribute('aria-label', 'Formules');
    var grille = el('div', 'chat-formula-grid');
    PALETTE.forEach(function (item) {
      var b = el('button', 'chat-formula-key', item[2]);
      b.type = 'button';
      b.title = item[0] + ' : ' + item[1];
      b.addEventListener('click', function () { inserer(item[1]); });
      grille.append(b);
    });
    var apercuTitre = el('div', 'chat-formula-preview-title', 'Aperçu');
    var apercu = el('div', 'chat-formula-preview');
    var aide = el('p', 'chat-formula-help', 'Les formules s’écrivent entre $ … $ : elles s’affichent comme dans le cours.');
    panneau.append(grille, apercuTitre, apercu, aide);
    pill.append(panneau);

    function inserer(code) {
      var debut = input.selectionStart, fin = input.selectionEnd;
      var valeur = input.value;
      var avant = valeur.slice(0, debut);
      // Déjà dans une formule (nombre impair de $ avant) : pas de nouveaux $.
      var dans = ((avant.match(/\$/g) || []).length % 2) === 1;
      var texte = dans ? code : '$' + code + '$';
      input.value = avant + texte + valeur.slice(fin);
      var pos = avant.length + texte.length - (dans ? 0 : 1);
      input.focus();
      input.setSelectionRange(pos, pos);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    function majApercu() {
      if (panneau.hidden) return;
      var Chat = window.EduBacChat;
      apercu.textContent = '';
      var texte = input.value.trim();
      if (!texte) { apercu.append(el('span', 'text-muted', 'Votre message s’affichera ici.')); return; }
      if (Chat && Chat.renderText) Chat.renderText(apercu, texte); else apercu.textContent = texte;
      if (((texte.match(/\$/g) || []).length % 2) === 0 && Chat && Chat.renderMath) Chat.renderMath(apercu);
    }
    bouton.addEventListener('click', function () {
      panneau.hidden = !panneau.hidden;
      bouton.setAttribute('aria-expanded', panneau.hidden ? 'false' : 'true');
      majApercu();
    });
    input.addEventListener('input', majApercu);
    document.addEventListener('click', function (e) {
      if (!panneau.hidden && !panneau.contains(e.target) && e.target !== bouton && !bouton.contains(e.target) && e.target !== input) {
        panneau.hidden = true;
        bouton.setAttribute('aria-expanded', 'false');
      }
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panneau.hidden) { panneau.hidden = true; bouton.setAttribute('aria-expanded', 'false'); }
    });
    var form = input.closest('form');
    if (form) form.addEventListener('submit', function () { panneau.hidden = true; });
  }

  function init() {
    document.querySelectorAll('textarea[data-formules]').forEach(formula);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();

  window.EduBacChatOutils = {
    highlightMentions: highlightMentions,
    mentionAutocomplete: mentionAutocomplete,
    pollNode: pollNode,
    pollDialog: pollDialog,
    formula: formula
  };
})();
