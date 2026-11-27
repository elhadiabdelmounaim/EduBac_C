/* Recherche rapide d'EduBac : bouton micro flottant.
 * On parle (« produit scalaire », « ouvre la messagerie ») : la phrase s'écrit dans le champ, les
 * résultats arrivent pendant la dictée et, quand une seule réponse s'impose, on y va après un court
 * compte à rebours (annulable). Sans reconnaissance vocale (Firefox, micro refusé) : même fenêtre,
 * au clavier. Ctrl+K ou « / » l'ouvrent aussi. Le son n'est ni enregistré ni envoyé à EduBac :
 * c'est le navigateur qui le transforme en texte ; seul le texte part vers /recherche/rapide/. */
(function () {
  'use strict';

  var script = document.currentScript;
  var URL_RECHERCHE = script ? script.getAttribute('data-url') : '/recherche/rapide/';
  var $ = function (id) { return document.getElementById(id); };
  var fab = $('rvFab'), fond = $('rvPanel'), champ = $('rvChamp'), micro = $('rvMicro');
  var langueBtn = $('rvLangue'), etat = $('rvEtat'), liste = $('rvResultats'), tout = $('rvTout');
  var direct = $('rvDirect'), directTexte = $('rvDirectTexte'), annuler = $('rvAnnuler');
  if (!fab || !fond) return;

  var Reconnaissance = window.SpeechRecognition || window.webkitSpeechRecognition;
  var CLE_LANGUE = 'edubac-rv-langue';
  var LANGUES = { fr: { code: 'fr-FR', court: 'FR', nom: 'français' }, ar: { code: 'ar-MA', court: 'ع', nom: 'arabe' } };
  var DELAI_DIRECT = 1200;
  var TYPES = { page: 'Pages', cours: 'Cours', lecon: 'Leçons', paragraphe: 'Dans les cours' };

  function lire(cle) { try { return localStorage.getItem(cle); } catch (e) { return null; } }
  function ecrire(cle, v) { try { if (v === null) localStorage.removeItem(cle); else localStorage.setItem(cle, v); } catch (e) { /* rien */ } }

  var langue = lire(CLE_LANGUE) === 'ar' ? 'ar' : 'fr';
  var vocal = !!Reconnaissance && window.isSecureContext !== false;
  var reco = null, ecoute = false, dicte = false;
  var resultats = [], choisi = -1, minuteur = null, attente = null, compteur = 0, controleur = null;
  var avantOuverture = null;

  function modeVocal(actif) {
    vocal = actif;
    fab.classList.toggle('rv-clavier', !actif);
    fab.querySelector('i').className = actif ? 'bi bi-mic-fill' : 'bi bi-search';
    fab.setAttribute('aria-label', actif ? 'Rechercher à la voix' : 'Rechercher');
    fab.title = actif ? 'Rechercher à la voix (Ctrl+K)' : 'Rechercher (Ctrl+K)';
    micro.hidden = !actif;
    langueBtn.hidden = !actif;
  }

  function majLangue() {
    var l = LANGUES[langue];
    langueBtn.textContent = l.court;
    langueBtn.setAttribute('aria-label', 'Langue de la dictée : ' + l.nom + ' (changer)');
    langueBtn.title = 'Dictée en ' + l.nom + ' — cliquer pour changer';
  }

  function direEtat(texte, genre) {
    etat.textContent = texte || '';
    etat.className = 'rv-etat' + (genre ? ' rv-' + genre : '');
  }

  // ---------- Fenêtre ----------
  function ouvert() { return !fond.hidden; }

  function ouvrir(parler) {
    if (!ouvert()) {
      avantOuverture = document.activeElement;
      fond.hidden = false;
      document.documentElement.classList.add('rv-ouvert');
      fab.setAttribute('aria-expanded', 'true');
    }
    champ.focus();
    champ.select();
    if (parler && vocal) ecouter();
    else if (!champ.value) direEtat(vocal ? '' : 'Tapez ce que vous cherchez.');
  }

  function fermer() {
    if (!ouvert()) return;
    arreterEcoute();
    annulerDirect();
    fond.hidden = true;
    document.documentElement.classList.remove('rv-ouvert');
    fab.setAttribute('aria-expanded', 'false');
    if (avantOuverture && avantOuverture.focus) avantOuverture.focus();
    else fab.focus();
  }

  // ---------- Dictée ----------
  function ecouter() {
    if (!vocal) return;
    annulerDirect();
    if (ecoute) { arreterEcoute(); return; }
    try {
      reco = new Reconnaissance();
      reco.lang = LANGUES[langue].code;
      reco.interimResults = true;
      reco.continuous = false;
      reco.maxAlternatives = 1;
    } catch (e) {
      modeVocal(false);
      direEtat('La dictée n’est pas disponible ici : tapez votre recherche.', 'alerte');
      return;
    }
    var texteFinal = '';
    var moi = reco;          // une ancienne dictée (changement de langue) ne touche plus à l'état
    reco.onstart = function () {
      if (moi !== reco) return;
      ecoute = true;
      fond.classList.add('rv-ecoute');
      micro.setAttribute('aria-label', 'Arrêter l’écoute');
      direEtat(langue === 'ar' ? 'أنا أستمع…' : 'Je vous écoute…', 'ecoute');
    };
    reco.onresult = function (event) {
      if (moi !== reco) return;
      var provisoire = '';
      for (var i = event.resultIndex; i < event.results.length; i++) {
        var morceau = event.results[i][0].transcript;
        if (event.results[i].isFinal) texteFinal += morceau; else provisoire += morceau;
      }
      champ.value = (texteFinal + provisoire).trim();
      dicte = true;
      chercherBientot(texteFinal && !provisoire);
    };
    reco.onerror = function (event) {
      if (moi !== reco) return;
      var e = event.error;
      if (e === 'not-allowed' || e === 'service-not-allowed') {
        modeVocal(false);          // pour cette page ; on réessaie à la suivante
        direEtat('Micro refusé : vous pouvez taper votre recherche. (Pour la dictée, autorisez le micro '
          + 'dans les réglages du site.)', 'alerte');
        champ.focus();
      } else if (e === 'no-speech') {
        direEtat('Je n’ai rien entendu. Touchez le micro et parlez.', 'alerte');
      } else if (e === 'audio-capture') {
        direEtat('Aucun micro trouvé sur cet appareil : tapez votre recherche.', 'alerte');
      } else if (e === 'network') {
        direEtat('La dictée demande une connexion Internet. Tapez votre recherche.', 'alerte');
      } else if (e === 'language-not-supported') {
        direEtat('Cette langue n’est pas disponible pour la dictée sur cet appareil.', 'alerte');
      } else if (e !== 'aborted') {
        direEtat('La dictée s’est arrêtée. Touchez le micro pour réessayer.', 'alerte');
      }
    };
    reco.onend = function () {
      if (moi !== reco) return;
      ecoute = false;
      fond.classList.remove('rv-ecoute');
      micro.setAttribute('aria-label', 'Parler');
      if (/rv-ecoute/.test(etat.className)) direEtat(champ.value ? '' : 'Touchez le micro pour parler.');
      if (texteFinal) chercher(true);
    };
    try { reco.start(); } catch (e) { /* déjà démarrée */ }
  }

  function arreterEcoute() {
    var ancienne = reco;
    reco = null;
    if (ancienne && ecoute) { try { ancienne.abort(); } catch (e) { /* rien */ } }
    ecoute = false;
    micro.setAttribute('aria-label', 'Parler');
    fond.classList.remove('rv-ecoute');
  }

  // ---------- Recherche ----------
  function chercherBientot(finale) {
    clearTimeout(attente);
    attente = setTimeout(function () { chercher(finale); }, finale ? 0 : 220);
  }

  function chercher(depuisDictee) {
    clearTimeout(attente);
    annulerDirect();
    var q = champ.value.trim();
    tout.href = tout.href.split('?')[0] + (q ? '?q=' + encodeURIComponent(q) : '');
    if (q.length < 2) { afficher([], q); return; }
    var numero = ++compteur;
    if (controleur) controleur.abort();
    controleur = window.AbortController ? new AbortController() : null;
    fond.classList.add('rv-charge');
    fetch(URL_RECHERCHE + '?q=' + encodeURIComponent(q), {
      credentials: 'same-origin', headers: { 'Accept': 'application/json' },
      signal: controleur ? controleur.signal : undefined
    }).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }).then(function (donnees) {
      if (numero !== compteur) return;
      fond.classList.remove('rv-charge');
      afficher(donnees.resultats || [], q);
      if (depuisDictee && dicte && donnees.direct && ouvert()) allerBientot(donnees.direct);
    }).catch(function (err) {
      if (err && err.name === 'AbortError') return;
      if (numero !== compteur) return;
      fond.classList.remove('rv-charge');
      direEtat('Recherche impossible pour le moment (connexion ?).', 'alerte');
    });
  }

  function element(tag, classe, texte) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (texte) el.textContent = texte;
    return el;
  }

  function afficher(liste_, q) {
    resultats = liste_;
    choisi = resultats.length ? 0 : -1;
    liste.textContent = '';
    var groupe = null;
    resultats.forEach(function (r, i) {
      if (r.type !== groupe) {
        groupe = r.type;
        var tete = element('li', 'rv-groupe', TYPES[r.type] || '');
        tete.setAttribute('role', 'presentation');
        liste.appendChild(tete);
      }
      var li = element('li', 'rv-item');
      li.setAttribute('role', 'option');
      li.id = 'rvItem' + i;
      var a = element('a', 'rv-lien');
      a.href = r.url;
      a.tabIndex = -1;
      var icone = element('i', 'bi bi-' + (r.icone || 'search') + ' rv-icone');
      icone.setAttribute('aria-hidden', 'true');
      var textes = element('span', 'rv-textes');
      textes.appendChild(element('span', 'rv-titre', r.titre));
      if (r.detail) textes.appendChild(element('span', 'rv-detail', r.detail));
      if (r.extrait) textes.appendChild(element('span', 'rv-extrait', r.extrait));
      a.appendChild(icone);
      a.appendChild(textes);
      if (r.verrou) {
        var v = element('span', 'rv-verrou', '🔒');
        v.title = 'Disponible après la séance';
        v.setAttribute('aria-label', 'verrouillée');
        a.appendChild(v);
      }
      a.addEventListener('mousemove', function () { if (choisi !== i) { choisi = i; marquer(); } });
      li.appendChild(a);
      liste.appendChild(li);
    });
    marquer();
    if (ecoute) return;
    if (q.length >= 2 && !resultats.length) direEtat('Aucun résultat pour « ' + q + ' ».', 'alerte');
    else if (resultats.length) direEtat(resultats.length + (resultats.length > 1 ? ' résultats' : ' résultat'));
    else direEtat('');
  }

  function marquer() {
    var items = liste.querySelectorAll('.rv-item');
    for (var k = 0; k < items.length; k++) {
      var actif = k === choisi;
      items[k].classList.toggle('rv-choisi', actif);
      items[k].setAttribute('aria-selected', actif ? 'true' : 'false');
      if (actif && items[k].scrollIntoView) items[k].scrollIntoView({ block: 'nearest' });
    }
    if (choisi >= 0) champ.setAttribute('aria-activedescendant', 'rvItem' + choisi);
    else champ.removeAttribute('aria-activedescendant');
  }

  // ---------- Aller directement au résultat ----------
  function aller(url) {
    annulerDirect();
    window.location.href = url;
  }

  function allerBientot(url) {
    var r = resultats.filter(function (x) { return x.url === url; })[0];
    directTexte.textContent = 'Ouverture de « ' + (r ? r.titre : url) + ' »…';
    direct.hidden = false;
    direct.classList.remove('rv-en-cours');
    void direct.offsetWidth;          // relance l'animation de la barre
    direct.classList.add('rv-en-cours');
    minuteur = setTimeout(function () { aller(url); }, DELAI_DIRECT);
    annuler.focus();
  }

  function annulerDirect() {
    clearTimeout(minuteur);
    minuteur = null;
    if (direct) { direct.hidden = true; direct.classList.remove('rv-en-cours'); }
  }

  // ---------- Commandes ----------
  fab.addEventListener('click', function () { ouvrir(true); });
  micro.addEventListener('click', ecouter);
  langueBtn.addEventListener('click', function () {
    langue = langue === 'fr' ? 'ar' : 'fr';
    ecrire(CLE_LANGUE, langue);
    majLangue();
    if (ecoute) { arreterEcoute(); ecouter(); }
    else direEtat('Dictée en ' + LANGUES[langue].nom + '.');
  });
  $('rvFermer').addEventListener('click', fermer);
  annuler.addEventListener('click', function () { annulerDirect(); champ.focus(); });
  fond.addEventListener('mousedown', function (event) { if (event.target === fond) fermer(); });
  champ.addEventListener('input', function () { dicte = false; chercherBientot(false); });
  champ.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!resultats.length) return;
      event.preventDefault();
      choisi = (choisi + (event.key === 'ArrowDown' ? 1 : -1) + resultats.length) % resultats.length;
      marquer();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (choisi >= 0 && resultats[choisi]) aller(resultats[choisi].url);
      else if (champ.value.trim()) window.location.href = tout.href;
    }
  });
  liste.addEventListener('click', function (event) {
    var a = event.target.closest('a.rv-lien');
    if (a) { event.preventDefault(); aller(a.getAttribute('href')); }
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && ouvert()) {
      event.preventDefault();
      if (minuteur) { annulerDirect(); champ.focus(); } else fermer();
      return;
    }
    if (ouvert()) {
      if (event.key === 'Tab') {                 // la tabulation reste dans la fenêtre
        var focusables = fond.querySelectorAll('button:not([hidden]), input, a[href]:not([tabindex="-1"])');
        var premier = focusables[0], dernier = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === premier) { dernier.focus(); event.preventDefault(); }
        else if (!event.shiftKey && document.activeElement === dernier) { premier.focus(); event.preventDefault(); }
      }
      return;
    }
    var cible = event.target;
    var saisie = cible && (cible.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(cible.tagName));
    if ((event.ctrlKey || event.metaKey) && (event.key === 'k' || event.key === 'K')) {
      event.preventDefault();
      ouvrir(false);
    } else if (event.key === '/' && !saisie && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      ouvrir(false);
    }
  });
  // Retour arrière depuis la page ouverte : la fenêtre ne doit pas rester affichée.
  window.addEventListener('pageshow', function (event) { if (event.persisted) fermer(); });

  fab.setAttribute('aria-expanded', 'false');
  modeVocal(vocal);
  majLangue();
  fab.hidden = false;
})();
