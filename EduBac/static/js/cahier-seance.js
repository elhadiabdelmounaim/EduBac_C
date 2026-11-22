/* Cahier de textes — panneau « Séance » du cours en ligne (enseignants seulement).
   L'enseignant choisit la date et la classe, coche ce qu'il a traité (parties, sous-titres,
   blocs : définition, proposition, exemples, applications…) puis « Enregistrer ».
   Enregistrer de nouveau la même date remplace la séance (pas de doublon).
   JavaScript sans dépendance. */
(function () {
  'use strict';

  var panneau = document.getElementById('seancePanneau');
  if (!panneau) return;

  var champDate = document.getElementById('seanceDate');
  var champClasse = document.getElementById('seanceClasse');
  var arbre = document.getElementById('seanceArbre');
  var compte = document.getElementById('seanceCompte');
  var bouton = document.getElementById('seanceEnregistrer');
  var message = document.getElementById('seanceMessage');
  var lienCahier = document.getElementById('seanceCahier');
  var champObs = document.getElementById('seanceObservations');
  var ouvreurs = document.querySelectorAll('[data-seance-ouvrir]');
  var lecon = panneau.getAttribute('data-lecon');
  var infoLecon = document.getElementById('seanceLecon');
  var champDuree = document.getElementById('seanceDuree');
  var blocSuivi = document.getElementById('seanceSuivi');
  var dureeSaisie = false;  // la durée a été tapée (ou vient d'une séance enregistrée) : on n'y touche plus
  var minutesDe = {};      // clé → minutes prévues (répartition horaire)
  var charge = false;
  var plan = [];
  var requete = 0;

  // ---------- Petits utilitaires ----------
  function lire(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }
  function ecrire(cle, valeur) { try { localStorage.setItem(cle, valeur); } catch (e) { /* stockage indisponible */ } }
  function oublier(cle) { try { localStorage.removeItem(cle); } catch (e) { /* stockage indisponible */ } }

  function aujourdhui() {
    var d = new Date();
    function deux(n) { return (n < 10 ? '0' : '') + n; }
    return d.getFullYear() + '-' + deux(d.getMonth() + 1) + '-' + deux(d.getDate());
  }

  function el(tag, attrs, texte) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (texte != null) e.textContent = texte;
    return e;
  }

  function dire(texte, genre) {
    message.textContent = texte || '';
    message.className = 'seance-message' + (genre ? ' ' + genre : '');
  }

  // 95 → « 1 h 35 » ; 40 → « 40 min ».
  function duree(m) {
    m = Math.round(m || 0);
    if (m < 60) return m + ' min';
    var h = Math.floor(m / 60), r = m % 60;
    return h + ' h' + (r ? ' ' + (r < 10 ? '0' : '') + r : '');
  }

  function cleBrouillon() { return 'edubac-seance:' + lecon + ':' + champClasse.value + ':' + champDate.value; }

  // ---------- Ouverture / fermeture ----------
  function ouvrir(oui) {
    panneau.hidden = !oui;
    document.documentElement.classList.toggle('seance-ouverte', oui);
    ouvreurs.forEach(function (b) { b.setAttribute('aria-expanded', oui ? 'true' : 'false'); });
    if (oui && !charge) { charge = true; demarrer(); }
    if (oui) setTimeout(function () { (champClasse.options.length ? champClasse : champDate).focus(); }, 30);
  }

  ouvreurs.forEach(function (b) { b.addEventListener('click', function () { ouvrir(panneau.hidden); }); });
  panneau.querySelector('[data-seance-fermer]').addEventListener('click', function () { ouvrir(false); });
  document.addEventListener('keydown', function (event) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    var cible = event.target;
    if (cible && /^(INPUT|SELECT|TEXTAREA)$/.test(cible.tagName)) return;
    if (event.key === 's' || event.key === 'S') { ouvrir(panneau.hidden); event.preventDefault(); }
    else if (event.key === 'Escape' && !panneau.hidden && panneau.contains(document.activeElement)) {
      ouvrir(false); event.stopPropagation();
    }
  }, true);
  // Les touches tapées dans le panneau ne tournent pas les pages du cours.
  panneau.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape' && event.key !== 'Tab') event.stopPropagation();
  });

  // ---------- Données ----------
  function charger(params) {
    var url = panneau.getAttribute('data-etat') + (params ? '?' + params : '');
    return fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      });
  }

  function demarrer() {
    champDate.value = aujourdhui();
    charger('').then(function (data) {
      plan = data.plan || [];
      var rep = data.repartition;
      if (data.prevu_texte) {
        infoLecon.hidden = false;
        infoLecon.textContent = 'Durée prévue de la leçon : ' + data.prevu_texte
          + (rep && rep.semaines ? ' · semaines ' + rep.semaines : '')
          + (rep && rep.annee ? ' · répartition ' + rep.annee : '');
      }
      if (data.cahier_url) lienCahier.href = data.cahier_url;
      champClasse.innerHTML = '';
      if (!data.classes.length) {
        arbre.innerHTML = '';
        var p = el('p', { 'class': 'seance-info' }, 'Vous n’avez pas encore de classe. ');
        p.appendChild(el('a', { href: data.creer_classe_url }, 'Créer une classe'));
        arbre.appendChild(p);
        return;
      }
      var memo = lire('edubac-seance-classe:' + lecon);
      var defaut = null;
      data.classes.forEach(function (c) {
        champClasse.appendChild(new Option(c.nom + ' — ' + c.niveau, c.id));
        if (String(c.id) === memo) defaut = c.id;
        if (defaut === null && c.meme_niveau) defaut = c.id;
      });
      if (defaut !== null) champClasse.value = String(defaut);
      construire();
      actualiser();
    }).catch(function () {
      arbre.innerHTML = '';
      arbre.appendChild(el('p', { 'class': 'seance-info erreur' }, 'Impossible de charger le plan du cours. Vérifiez votre connexion.'));
    });
  }

  // État de la classe et de la date choisies : séance déjà enregistrée, éléments vus ailleurs.
  function actualiser() {
    if (!champClasse.value || !champDate.value) return;
    ecrire('edubac-seance-classe:' + lecon, champClasse.value);
    var numero = ++requete;
    dire('');
    charger('classe=' + encodeURIComponent(champClasse.value) + '&date=' + encodeURIComponent(champDate.value))
      .then(function (data) {
        if (numero !== requete) return;
        var brouillon = lire(cleBrouillon());
        var selection = data.existe ? data.selection : (brouillon ? brouillon.split(',') : courantes());
        dureeSaisie = !!(data.existe && data.duree);
        if (champDuree) champDuree.value = dureeSaisie ? data.duree : '';
        cocher(selection, data.deja || {});
        if (champObs) champObs.value = data.observations || '';
        afficherSuivi(data.suivi);
        if (data.existe) dire('Une séance est déjà enregistrée à cette date : elle sera mise à jour.', 'info');
      })
      .catch(function () { if (numero === requete) dire('Connexion impossible.', 'erreur'); });
  }

  champClasse.addEventListener('change', actualiser);
  champDate.addEventListener('change', actualiser);

  // ---------- Arbre des éléments ----------
  function estFeuille(n) { return n.type === 'bloc' || !(n.enfants && n.enfants.length); }

  function noeud(n, niveau) {
    var li = el('li', { 'class': 'seance-noeud niveau-' + niveau });
    var ligne = el('div', { 'class': 'seance-ligne' });
    var feuille = estFeuille(n);
    if (!feuille) {
      var plier = el('button', { type: 'button', 'class': 'seance-plier', 'aria-expanded': 'false',
                                 'aria-label': 'Afficher le détail : ' + n.titre }, '▸');
      ligne.appendChild(plier);
    } else {
      ligne.appendChild(el('span', { 'class': 'seance-puce', 'aria-hidden': 'true' }));
    }
    var label = el('label');
    var box = el('input', { type: 'checkbox' });
    if (feuille) box.setAttribute('data-cle', n.key);
    label.appendChild(box);
    label.appendChild(el('span', { 'class': 'seance-libelle' }, n.titre));
    ligne.appendChild(label);
    ligne.appendChild(el('span', { 'class': 'seance-deja', hidden: '' }));
    if (n.minutes) {
      ligne.appendChild(el('span', { 'class': 'seance-min', title: 'Durée prévue' }, duree(n.minutes)));
      if (feuille) minutesDe[n.key] = n.minutes;
    }
    if (!feuille) ligne.appendChild(el('span', { 'class': 'seance-part' }));
    li.appendChild(ligne);
    if (!feuille) {
      var ul = el('ul', { 'class': 'seance-enfants', hidden: '' });
      n.enfants.forEach(function (e) { ul.appendChild(noeud(e, niveau + 1)); });
      li.appendChild(ul);
    }
    return li;
  }

  function construire() {
    arbre.innerHTML = '';
    var ul = el('ul', { 'class': 'seance-racine' });
    plan.forEach(function (p) { ul.appendChild(noeud(p, 1)); });
    arbre.appendChild(ul);
    majParents();
  }

  arbre.addEventListener('click', function (event) {
    var plier = event.target.closest('.seance-plier');
    if (!plier) return;
    var ul = plier.closest('li').querySelector(':scope > .seance-enfants');
    var ouvert = ul.hidden;
    ul.hidden = !ouvert;
    plier.setAttribute('aria-expanded', ouvert ? 'true' : 'false');
    plier.textContent = ouvert ? '▾' : '▸';
  });

  arbre.addEventListener('change', function (event) {
    var box = event.target;
    if (box.type !== 'checkbox') return;
    var li = box.closest('li');
    // Cocher une partie ou un sous-titre coche tout ce qu'il contient.
    li.querySelectorAll('.seance-enfants input[type=checkbox]').forEach(function (b) { b.checked = box.checked; });
    majParents();
    ecrire(cleBrouillon(), courantes().join(','));
  });

  function feuilles(li) { return li.querySelectorAll('input[data-cle]'); }

  function majParents() {
    var noeuds = arbre.querySelectorAll('li.seance-noeud');
    for (var k = noeuds.length - 1; k >= 0; k--) {   // des feuilles vers les parties
      var li = noeuds[k];
      var ul = li.querySelector(':scope > .seance-enfants');
      if (!ul) continue;
      var tout = feuilles(li);
      var faits = 0, vus = 0;
      tout.forEach(function (b) {
        if (b.checked) faits++;
        if (b.closest('li').querySelector(':scope > .seance-ligne > .seance-deja:not([hidden])')) vus++;
      });
      var box = li.querySelector(':scope > .seance-ligne input');
      box.checked = tout.length > 0 && faits === tout.length;
      box.indeterminate = faits > 0 && faits < tout.length;
      li.querySelector(':scope > .seance-ligne > .seance-part').textContent = faits ? faits + '/' + tout.length : '';
      var deja = li.querySelector(':scope > .seance-ligne > .seance-deja');
      deja.hidden = !(tout.length && vus === tout.length);
      deja.textContent = '✓';
    }
    var cles = courantes();
    var n = cles.length;
    var temps = cles.reduce(function (t, c) { return t + (minutesDe[c] || 0); }, 0);
    compte.textContent = n ? n + ' élément' + (n > 1 ? 's' : '') + ' coché' + (n > 1 ? 's' : '')
      + (temps ? ' · ' + duree(temps) : '') : 'Rien de coché';
    // Durée proposée : temps prévu des éléments cochés, tant que l'enseignant ne l'a pas saisie.
    if (champDuree && !dureeSaisie) champDuree.value = temps ? Math.min(480, temps) : '';
    bouton.disabled = !n || !champClasse.value;
  }

  function courantes() {
    return Array.prototype.map.call(arbre.querySelectorAll('input[data-cle]:checked'),
                                    function (b) { return b.getAttribute('data-cle'); });
  }

  function cocher(cles, deja) {
    var choix = {};
    cles.forEach(function (c) { choix[c] = true; });
    arbre.querySelectorAll('input[data-cle]').forEach(function (b) {
      var cle = b.getAttribute('data-cle');
      b.checked = !!choix[cle];
      var marque = b.closest('.seance-ligne').querySelector('.seance-deja');
      marque.hidden = !deja[cle];
      marque.textContent = deja[cle] ? '✓ ' + deja[cle] : '';
      marque.title = deja[cle] ? 'Déjà traité le ' + deja[cle] : '';
    });
    majParents();
  }

  if (champDuree) champDuree.addEventListener('input', function () { dureeSaisie = champDuree.value !== ''; });

  // ---------- Barre de progression de la leçon (même rendu que cahier/_suivi.html) ----------
  function afficherSuivi(b) {
    if (!blocSuivi) return;
    blocSuivi.innerHTML = '';
    blocSuivi.hidden = !b;
    if (!b) return;
    if (!b.connu) {
      blocSuivi.appendChild(el('p', { 'class': 'suivi-inconnu' },
        'Durée réalisée : ' + b.realise_texte + ' · durée prévue de la leçon non renseignée.'));
      return;
    }
    var suivi = el('div', { 'class': 'suivi' });
    var barre = el('div', { 'class': 'suivi-barre', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100',
                            'aria-valuenow': String(b.pourcent),
                            'aria-valuetext': b.pourcent_texte + ' % réalisé, ' + b.reste_pourcent_texte + ' % restant' });
    var fait = el('span', { 'class': 'suivi-fait' });
    fait.style.width = b.largeur + '%';
    barre.appendChild(fait);
    suivi.appendChild(barre);
    var pc = el('p', { 'class': 'suivi-pourcents' });
    var a = el('span'); a.appendChild(el('strong', null, b.pourcent_texte + ' %')); a.appendChild(document.createTextNode(' réalisé'));
    pc.appendChild(a);
    pc.appendChild(el('span', null, b.reste_pourcent_texte + ' % restant'));
    suivi.appendChild(pc);
    var dl = el('dl', { 'class': 'suivi-durees' });
    [['Durée prévue', b.prevu_texte], ['Durée réalisée', b.realise_texte], ['Durée restante', b.restant_texte]]
      .forEach(function (x) {
        var d = el('div'); d.appendChild(el('dt', null, x[0])); d.appendChild(el('dd', null, x[1])); dl.appendChild(d);
      });
    suivi.appendChild(dl);
    if (b.depassement) suivi.appendChild(el('p', { 'class': 'suivi-depasse' }, 'Durée prévue dépassée de ' + b.depassement_texte + '.'));
    blocSuivi.appendChild(suivi);
  }

  // ---------- Enregistrer ----------
  bouton.addEventListener('click', function () {
    var cles = courantes();
    if (!cles.length) { dire('Cochez au moins un élément traité.', 'erreur'); return; }
    if (!champDate.value) { dire('Choisissez la date.', 'erreur'); return; }
    var minutes = champDuree ? parseInt(champDuree.value, 10) : NaN;
    if (champDuree && !(minutes >= 1 && minutes <= 480)) {
      dire('Indiquez la durée réalisée (entre 1 et 480 minutes).', 'erreur');
      champDuree.focus();
      return;
    }
    bouton.disabled = true;
    dire('Enregistrement…');
    fetch(panneau.getAttribute('data-enregistrer'), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json',
                 'X-CSRFToken': panneau.getAttribute('data-csrf') },
      body: JSON.stringify({ classe: champClasse.value, date: champDate.value, cles: cles,
                             observations: champObs ? champObs.value : undefined,
                             duree: champDuree ? minutes : undefined })
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, message: 'Erreur ' + r.status + '.' }; });
    }).then(function (data) {
      if (!data.ok) { dire(data.message || 'Enregistrement impossible.', 'erreur'); return; }
      oublier(cleBrouillon());
      dire(data.message, 'succes');
      dureeSaisie = true;
      afficherSuivi(data.suivi);
      if (data.url) lienCahier.href = data.url;
    }).catch(function () {
      dire('Connexion impossible : rien n’a été perdu, réessayez.', 'erreur');
    }).then(function () { majParents(); });
  });
})();
