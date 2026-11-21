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
  var ouvreurs = document.querySelectorAll('[data-seance-ouvrir]');
  var lecon = panneau.getAttribute('data-lecon');
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
        cocher(selection, data.deja || {});
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
    var n = courantes().length;
    compte.textContent = n ? n + ' élément' + (n > 1 ? 's' : '') + ' coché' + (n > 1 ? 's' : '') : 'Rien de coché';
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

  // ---------- Enregistrer ----------
  bouton.addEventListener('click', function () {
    var cles = courantes();
    if (!cles.length) { dire('Cochez au moins un élément traité.', 'erreur'); return; }
    if (!champDate.value) { dire('Choisissez la date.', 'erreur'); return; }
    bouton.disabled = true;
    dire('Enregistrement…');
    fetch(panneau.getAttribute('data-enregistrer'), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json',
                 'X-CSRFToken': panneau.getAttribute('data-csrf') },
      body: JSON.stringify({ classe: champClasse.value, date: champDate.value, cles: cles })
    }).then(function (r) {
      return r.json().catch(function () { return { ok: false, message: 'Erreur ' + r.status + '.' }; });
    }).then(function (data) {
      if (!data.ok) { dire(data.message || 'Enregistrement impossible.', 'erreur'); return; }
      oublier(cleBrouillon());
      dire(data.message, 'succes');
      if (data.url) lienCahier.href = data.url;
    }).catch(function () {
      dire('Connexion impossible : rien n’a été perdu, réessayez.', 'erreur');
    }).then(function () { majParents(); });
  });
})();
