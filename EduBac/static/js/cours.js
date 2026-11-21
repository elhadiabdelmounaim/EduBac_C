/* Cours en ligne (HTML), présenté comme un cahier : le contenu est réparti en pages
   à la taille de l'écran, tournées avec les boutons, les flèches du clavier ou un
   glissement du doigt — une page à la fois, qui se tourne comme une feuille.
   Chargé avec « defer » après jQuery et avant MathJax (l'ordre est conservé). */
(function ($) {
  'use strict';

  // ---------- MathJax : configuration lue au chargement de MathJax ----------
  var mathPret = $.Deferred();
  window.MathJax = {
    tex: {
      inlineMath: [['\\(', '\\)']],
      displayMath: [['\\[', '\\]']],
      macros: {
        vect: ['\\overrightarrow{#1}', 1],
        vu: '\\overrightarrow{u}', vv: '\\overrightarrow{v}', vw: '\\overrightarrow{w}',
        vn: '\\overrightarrow{n}', vi: '\\overrightarrow{i}', vj: '\\overrightarrow{j}',
        R: '\\mathbb{R}', Cc: '(\\mathcal{C})', Dd: '(D)',
        Rep: '\\left(O;\\overrightarrow{i},\\overrightarrow{j}\\right)',
        angv: ['(\\widehat{#1\\,;#2})', 2]
      }
    },
    svg: { fontCache: 'global' },
    startup: {
      pageReady: function () {
        return window.MathJax.startup.defaultPageReady().then(
          function () { mathPret.resolve(); },
          function () { mathPret.resolve(); });
      }
    }
  };
  // Si MathJax ne se charge pas, les pages sont tout de même construites.
  setTimeout(function () { mathPret.resolve(); }, 12000);

  function policesPretes() {
    var d = $.Deferred();
    setTimeout(d.resolve, 4000);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(d.resolve, d.resolve);
    else d.resolve();
    return d.promise();
  }

  $(function () {
    var $root = $(document.documentElement);
    var $source = $('#source');
    var $sections = $source.find('section.chap[id]');
    var $scene = $('#scene');
    var $feuilles = $('#feuilles');
    var $prev = $('#pagePrev');
    var $next = $('#pageNext');
    var $num = $('#pageNum');
    var $etapes = $('#pageEtapes');
    var $select = $('#pageChapitre');
    var $bar = $('#progress');

    // ---------- Parties du cours ----------
    var parties = $sections.map(function () {
      var $s = $(this);
      return {
        id: this.id,
        num: $.trim($s.children('h2').find('.num').first().text()),
        label: $s.data('toc') || $.trim($s.children('h2').first().text())
      };
    }).get();
    var partieParId = {};
    $.each(parties, function (_, p) { partieParId[p.id] = p; });

    // ---------- Chiffres de l'en-tête (comptés dans le cours) ----------
    var $stats = $source.find('[data-stats]');
    $.each([['def', 'définition', 'définitions'], ['prop', 'proposition', 'propositions'],
            ['app', 'application', 'applications']], function (_, item) {
      var count = $sections.find('.bloc.' + item[0]).length;
      if (!count) return;
      $('<div>', { 'class': 'stat' })
        .append($('<b>', { text: count }))
        .append($('<span>', { text: count > 1 ? item[2] : item[1] }))
        .appendTo($stats);
    });

    // ---------- Thème : même réglage (« edubac-theme ») que le reste du site ----------
    var $theme = $('#coursTheme');
    function sombre() {
      var t = $root.attr('data-theme');
      if (t) return t === 'dark';
      return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    }
    function libelleTheme() {
      var dark = sombre();
      $theme.text(dark ? 'Mode clair' : 'Mode sombre').attr('aria-pressed', dark ? 'true' : 'false');
    }
    $theme.on('click', function () {
      var next = sombre() ? 'light' : 'dark';
      $root.attr('data-theme', next);
      try { localStorage.setItem('edubac-theme', next); } catch (e) { /* stockage indisponible */ }
      libelleTheme();
    });
    libelleTheme();

    // ---------- Sommaire de la couverture et liste « Aller à la partie » ----------
    var $liste = $('<ol>');
    $.each(parties, function (_, p) {
      $('<li>').append($('<a>', { href: '#' + p.id })
        .append($('<span>', { 'class': 'n', text: p.num }))
        .append($('<span>', { text: p.label }))).appendTo($liste);
    });
    $source.find('.hero').append(
      $('<nav>', { 'class': 'bloc-sommaire', 'aria-label': 'Sommaire du cours' })
        .append($('<h2>', { text: 'Sommaire' })).append($liste));
    $select.append(new Option('Couverture et sommaire', ''));
    $.each(parties, function (_, p) { $select.append(new Option(p.num + '. ' + p.label, p.id)); });

    if (!$root.hasClass('pagine')) return;   // lecture continue (secours)

    // ---------- Unités à répartir dans les pages ----------
    // Chaque partie (I, II…) commence sur une nouvelle page ; un titre reste avec ce qui le suit ;
    // une liste trop longue pour une page continue sur la suivante (« suite »).
    var unites = [];
    $source.find('.hero').children().each(function () { unites.push({ el: this, partie: '' }); });
    $sections.each(function () {
      var id = this.id;
      $(this).children().each(function (i) { unites.push({ el: this, partie: id, rupture: i === 0 }); });
    });
    var $fin = $source.children('.fin');
    if ($fin.length) unites.push({ el: $fin[0], partie: parties.length ? parties[parties.length - 1].id : '' });

    // ---------- Présentation pas à pas ----------
    // Au vidéoprojecteur, une page apparaît avec son titre, puis chaque bloc (définition,
    // proposition, exemple…) à chaque appui sur → / Espace / télécommande ; les exemples d'une
    // liste arrivent un par un. Une application reste voilée (« Afficher l'application »)
    // jusqu'à ce qu'on la demande. ↓ / ↑ et les boutons du bas changent de page directement.
    // Clé de chaque bloc, comme dans le cahier de textes : « s1-b3 » = 3e bloc de la partie s1.
    $sections.each(function () {
      var id = this.id;
      $(this).find('.bloc').filter(function () { return !$(this).parent().closest('.bloc').length; })
        .each(function (i) { $(this).attr('data-cle', id + '-b' + (i + 1)); });
    });
    $source.find('.bloc.app').append($('<button>', {
      type: 'button', 'class': 'app-voile', text: "Afficher l'application"
    }));
    var CLASSES_ETAPE = 'etape-cache voilee etape-anime';

    function calculerEtapes(p) {
      var etapes = [];
      var attente = [];     // un sous-titre apparaît avec ce qui le suit
      p.$corps.children().each(function () {
        var $el = $(this);
        if (this.tagName === 'H3') { attente.push(this); return; }
        if (!$el.hasClass('bloc')) { attente = []; return; }
        var items = $el.hasClass('ex') ? $el.children('ol, ul').first().children('li') : $();
        if (items.length >= 2) {
          etapes.push(attente.concat([this, items[0]]));
          items.slice(1).each(function () { etapes.push([this]); });
        } else {
          etapes.push(attente.concat([this]));
        }
        attente = [];
      });
      p.etapes = etapes;
      p.vu = 0;
    }

    function majEtapes(k, anime) {
      var p = pages[k];
      if (!p) return;
      $.each(p.etapes, function (i, els) {
        var $els = $(els).removeClass('etape-anime');
        var prochaineApp = i === p.vu && $els.filter('.bloc.app').length > 0;
        $.each(els, function (_, el) {
          var $el = $(el);
          if (i < p.vu) $el.removeClass('etape-cache voilee');
          else if (prochaineApp) $el.removeClass('etape-cache').toggleClass('voilee', $el.is('.bloc.app'));
          else $el.addClass('etape-cache').removeClass('voilee');
        });
        if (anime && i === p.vu - 1) {
          $els[0].offsetWidth;
          $els.addClass('etape-anime');
        }
      });
      if (k === courante) majCompteur();
    }

    function majCompteur() {
      suivreMinuteur();
      var p = pages[courante];
      var n = p && $root.hasClass('presentation') ? p.etapes.length : 0;
      if (!n) { $etapes.prop('hidden', true).text(''); return; }
      var texte = n <= 12
        ? new Array(Math.min(p.vu, n) + 1).join('●') + new Array(n - Math.min(p.vu, n) + 1).join('○')
        : p.vu + ' / ' + n;
      $etapes.prop('hidden', false).text(texte)
        .attr('aria-label', 'Élément ' + p.vu + ' sur ' + n + ' de la page');
    }

    function enPresentation() { return $root.hasClass('presentation'); }

    // ---------- Minuteur du paragraphe (présentation) ----------
    // Le paragraphe en cours est le dernier bloc apparu ; son temps prévu (répartition horaire)
    // est décompté jusqu'à zéro. Revenir à un paragraphe reprend son temps restant.
    var minutage = {};
    try { minutage = JSON.parse($('#cours-minutage').text() || '{}'); } catch (e) { minutage = {}; }
    var $minuteur = $('#minuteur');
    var chrono = { cle: null, restant: {}, pause: false, dernier: 0, horloge: null };
    var TOUR = 2 * Math.PI * 44;

    function blocCourant() {
      var p = pages[courante];
      if (!p || !p.vu) return null;
      var $bloc = $(p.etapes[p.vu - 1]).closest('.bloc[data-cle]').last();
      var cle = $bloc.attr('data-cle');
      return cle && minutage[cle] ? { cle: cle, nom: $.trim($bloc.children('.tag').first().text().replace(/\s*\(suite\)$/, '')) } : null;
    }

    function suivreMinuteur() {
      if (!$minuteur.length) return;
      if (!enPresentation()) { arreterHorloge(); $minuteur.prop('hidden', true); return; }
      var b = blocCourant();
      if (b && b.cle !== chrono.cle) {
        chrono.cle = b.cle;
        chrono.nom = b.nom;
        if (chrono.restant[b.cle] == null) chrono.restant[b.cle] = minutage[b.cle] * 60000;
        chrono.pause = false;
        $minuteur.removeClass('change');
        $minuteur[0].offsetWidth;
        $minuteur.addClass('change');
      }
      $minuteur.prop('hidden', !chrono.cle);
      if (chrono.cle) demarrerHorloge();
      dessinerMinuteur();
    }

    function demarrerHorloge() {
      if (chrono.horloge) return;
      chrono.dernier = Date.now();
      chrono.horloge = setInterval(function () {
        var maintenant = Date.now();
        if (!chrono.pause && chrono.cle) {
          chrono.restant[chrono.cle] = Math.max(0, chrono.restant[chrono.cle] - (maintenant - chrono.dernier));
        }
        chrono.dernier = maintenant;
        dessinerMinuteur();
      }, 250);
    }

    function arreterHorloge() { clearInterval(chrono.horloge); chrono.horloge = null; }

    function dessinerMinuteur() {
      if (!chrono.cle) return;
      var total = minutage[chrono.cle] * 60000;
      var reste = chrono.restant[chrono.cle];
      var s = Math.ceil(reste / 1000);
      $('#minuteurTemps').text(Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2));
      $('#minuteurNom').text(chrono.nom || '');
      $minuteur.find('.minuteur-arc').css('stroke-dashoffset', (TOUR * (1 - reste / total)).toFixed(2));
      $minuteur.toggleClass('bientot', reste > 0 && reste <= Math.min(120000, total * 0.2))
        .toggleClass('fini', reste <= 0).toggleClass('en-pause', chrono.pause)
        .attr('aria-label', 'Temps restant pour « ' + (chrono.nom || 'ce paragraphe') + ' » : '
              + Math.floor(s / 60) + ' min ' + (s % 60) + ' s' + (chrono.pause ? ' (en pause)' : ''));
    }

    $minuteur.find('.minuteur-arc').css('stroke-dasharray', TOUR.toFixed(2));
    // Le minuteur ne garde pas le focus : Espace / Entrée continuent d'avancer dans le cours.
    $minuteur.on('mousedown', function (event) { event.preventDefault(); });
    $minuteur.on('click', function () {
      if (!chrono.cle) return;
      chrono.pause = !chrono.pause;
      dessinerMinuteur();
      this.blur();
    });
    $minuteur.on('dblclick', function () {
      if (!chrono.cle) return;
      chrono.restant[chrono.cle] = minutage[chrono.cle] * 60000;
      chrono.pause = false;
      dessinerMinuteur();
    });

    // Élément suivant de la page, puis la page suivante quand tout est affiché.
    function avancer() {
      var p = pages[courante];
      if (enPresentation() && p && p.vu < p.etapes.length) { p.vu++; majEtapes(courante, true); return; }
      suivante();
    }

    function reculer() {
      var p = pages[courante];
      if (enPresentation() && p && p.vu > 0) { p.vu--; majEtapes(courante, false); return; }
      if (courante > 0 && pages[courante - 1]) pages[courante - 1].vu = pages[courante - 1].etapes.length;
      precedente();
    }

    function toutAfficher() {
      var p = pages[courante];
      if (!p || p.vu >= p.etapes.length) return;
      p.vu = p.etapes.length;
      majEtapes(courante, true);
    }

    $feuilles.on('click', '.app-voile', function () {
      var p = pages[courante];
      var bloc = $(this).closest('.bloc.app')[0];
      if (!p) return;
      $.each(p.etapes, function (i, els) {
        if ($.inArray(bloc, els) >= 0) { p.vu = Math.max(p.vu, i + 1); return false; }
      });
      majEtapes(courante, true);
    });

    var pages = [];
    var suites = [];        // blocs « suite » créés lors du découpage
    var courante = 0;
    var parVue = 1;
    var largeur = 0;
    var taille = '';
    var titre = $source.data('titre') || document.title;

    function estTitre(el) { return el && /^H[23]$/.test(el.tagName); }

    var pageApp = false;    // pages créées pour une application seule (texte agrandi)

    function nouvellePage(partie) {
      var $p = $('<article>', { 'class': pageApp ? 'feuille page-app' : 'feuille', 'aria-roledescription': 'page' });
      var $tete = $('<header>', { 'class': 'feuille-tete' })
        .append($('<span>', { text: '\u00a0' })).append($('<span>', { text: '\u00a0' }));
      var $corps = $('<div>', { 'class': 'feuille-corps' });
      var $pied = $('<footer>', { 'class': 'feuille-pied', text: '\u00a0' });
      $p.append($tete, $corps, $pied).appendTo($feuilles);
      var page = { $p: $p, $corps: $corps, $tete: $tete, $pied: $pied, partie: partie };
      pages.push(page);
      return page;
    }

    function tient(page) {
      var c = page.$corps[0];
      return c.scrollHeight <= c.clientHeight + 1;
    }

    // Découpe un bloc trop long pour une page : ses derniers éléments (points de liste,
    // figure, paragraphe…) passent, dans le même ordre, dans un bloc « suite » sur la page suivante.
    var mouvements = [];    // chaque déplacement, pour tout remettre en place avant de repaginer

    function decoupable(el) {
      return /^(OL|UL)$/.test(el.tagName) || (el.tagName === 'DIV' && !$(el).hasClass('tag'));
    }

    function premierContenu(el) {
      return $(el).children().not('.tag, .app-voile').first()[0];
    }

    // Déplace le dernier morceau de « src » au début de « dst » (structure identique).
    function retirerDernier(src, dst, miroirs) {
      for (;;) {
        var enfants = $(src).children().not('.tag, .app-voile').toArray();
        if (enfants.length >= 2) {
          var dernier = enfants[enfants.length - 1];
          var tag = $(dst).children('.tag')[0];
          if (tag) $(dernier).insertAfter(tag); else $(dst).prepend(dernier);
          mouvements.push({ el: dernier, parent: src });
          return true;
        }
        if (enfants.length !== 1 || !decoupable(enfants[0])) return false;
        var enfant = enfants[0];
        var miroir = premierContenu(dst);
        if (!miroir || $(miroir).data('miroir') !== enfant) {
          miroir = enfant.cloneNode(false);
          miroir.removeAttribute('id');
          $(miroir).data('miroir', enfant);
          var tete = $(dst).children('.tag')[0];
          if (tete) $(miroir).insertAfter(tete); else $(dst).prepend(miroir);
          miroirs.push({ source: enfant, copie: miroir });
        }
        src = enfant;
        dst = miroir;
      }
    }

    function decouper(page, el, partie) {
      var $bloc = $(el);
      if (!$bloc.hasClass('bloc')) { page.$p.addClass('deborde'); return page; }
      var etiquette = $.trim($bloc.children('.tag').first().text().replace(/\s*\(suite\)$/, ''));
      var $suite = $('<div>', { 'class': $bloc.attr('class').replace(/\s*\b(suite|etape-cache|voilee|etape-anime)\b/g, '') + ' suite' })
        .attr('data-cle', $bloc.attr('data-cle'))
        .data('source', $bloc.data('source') || $bloc[0])
        .append($('<div>', { 'class': 'tag', text: etiquette + ' (suite)' }));
      var miroirs = [];
      var deplace = false;
      while (!tient(page) && retirerDernier($bloc[0], $suite[0], miroirs)) deplace = true;
      // Une liste numérotée continue sa numérotation.
      $.each(miroirs, function (_, m) {
        if (m.source.tagName === 'OL') {
          $(m.copie).attr('start', (parseInt($(m.source).attr('start'), 10) || 1) + $(m.source).children('li').length);
        }
      });
      if (!tient(page)) page.$p.addClass('deborde');
      if (!deplace) return page;
      suites.push($suite[0]);
      page = nouvellePage(partie);
      page.$corps.append($suite);
      return tient(page) ? page : decouper(page, $suite[0], partie);
    }

    function defaire() {
      $feuilles.find('.etape-cache, .voilee, .etape-anime').removeClass(CLASSES_ETAPE);
      for (var k = mouvements.length - 1; k >= 0; k--) $(mouvements[k].parent).append(mouvements[k].el);
      mouvements = [];
      $(suites).remove();
      suites = [];
      $.each(unites, function (_, u) { $(u.el).detach(); });
      $feuilles.empty();
      pages = [];
    }

    // Une seule page à la fois, centrée (cahier comme en présentation).
    function mesurer() {
      var w = $scene.width();
      var h = $scene.height();
      var presentation = $root.hasClass('presentation');
      var marge = w < 640 ? 10 : 24;
      parVue = 1;
      largeur = presentation
        ? Math.min(w - 2 * marge, Math.round(h * 1.6))
        : Math.min(w - 2 * marge, Math.max(780, Math.round(h * 1.25)), 1000);
      $feuilles.css({ '--page-w': largeur + 'px', '--page-left': Math.round((w - largeur) / 2) + 'px' });
      return w + 'x' + h;
    }

    function paginer() {
      var ancre = pages.length ? premiereUnite(courante) : null;
      defaire();
      taille = mesurer();
      var page = nouvellePage('');
      var presentation = $root.hasClass('presentation');
      var seule = false;      // la page porte une application : rien d'autre n'y entre
      for (var i = 0; i < unites.length; i++) {
        var u = unites[i];
        // Au vidéoprojecteur, chaque application a sa propre page (avec son sous-titre éventuel).
        var app = presentation && $(u.el).is('.bloc.app');
        if (app && page.$corps.children().length) {
          var titreAvant = page.$corps.children().last()[0];
          var lotTitre = estTitre(titreAvant) && !seule && page.$corps.children().length > 1 ? [titreAvant] : [];
          $(lotTitre).detach();
          page = nouvellePage(u.partie);
          page.$corps.append(lotTitre);
        } else if ((u.rupture || seule) && page.$corps.children().length) {
          page = nouvellePage(u.partie);
        }
        seule = app;
        if (!page.partie) page.partie = u.partie;
        page.$corps.append(u.el);
        if (app) {
          page.$p.addClass('page-app');
          pageApp = true;
          if (!tient(page)) page = decouper(page, u.el, u.partie);
          pageApp = false;
          continue;
        }
        if (tient(page)) continue;
        // Ne tient pas : on passe à la page suivante (avec le titre qui précède, s'il y en a un).
        var precedent = $(u.el).prev()[0];
        var avecTitre = estTitre(precedent);
        if (page.$corps.children().length > (avecTitre ? 2 : 1)) {
          var lot = avecTitre ? [precedent, u.el] : [u.el];
          $(lot).detach();
          page = nouvellePage(u.partie);
          page.$corps.append(lot);
          if (tient(page)) continue;
        }
        page = decouper(page, u.el, u.partie);
      }
      var total = pages.length;
      $.each(pages, function (k, p) {
        var partie = partieParId[p.partie];
        p.$tete.children().eq(0).text(partie ? partie.num + ' · ' + partie.label : 'Couverture');
        p.$tete.children().eq(1).text(titre);
        p.$pied.text((k + 1) + ' / ' + total);
        p.$p.attr('aria-label', 'Page ' + (k + 1) + ' sur ' + total);
        p.$corps.children().each(function (i) { this.style.setProperty('--i', Math.min(i, 8)); });
      });
      // Chaque morceau « suite » d'une application a aussi son bouton.
      $(suites).filter('.app').each(function () {
        if (!$(this).children('.app-voile').length) {
          $(this).append($('<button>', { type: 'button', 'class': 'app-voile', text: 'Afficher la suite' }));
        }
      });
      $.each(pages, function (_, p) { calculerEtapes(p); });
      var cible = 0;
      if (ancre) {
        $.each(pages, function (k, p) { if ($.contains(p.$p[0], ancre)) { cible = k; return false; } });
      }
      return cible;
    }

    function premiereUnite(index) {
      var p = pages[index];
      if (!p) return null;
      var first = p.$corps.children().first();
      return first.data('source') || first[0] || null;
    }

    // Tourner la page : la feuille courante se soulève et tourne autour de sa reliure (à gauche)
    // en découvrant la suivante ; pour revenir, la feuille précédente se rabat par-dessus.
    var DUREE_TOUR = 1300;   // ms, identique à --duree-tour (cours.css)
    var finTour = null;
    var mouvementReduit = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function terminerTour() {
      clearTimeout(finTour);
      finTour = null;
      $feuilles.children('.feuille').removeClass('tourne revient dessous');
    }

    function afficher(index, sansAnimation) {
      var total = pages.length;
      index = Math.max(0, Math.min(index, total - 1));
      var avant = courante;
      var $ancienne = $feuilles.children('.feuille.visible');
      terminerTour();
      courante = index;
      var $nouvelle = pages[index].$p;
      var tourner = !sansAnimation && !mouvementReduit && $ancienne.length && $ancienne[0] !== $nouvelle[0];
      if (tourner) {
        if (index > avant) {
          $ancienne.addClass('tourne');      // la page courante part vers la gauche
          $nouvelle.addClass('dessous');
        } else {
          $ancienne.addClass('dessous');
          $nouvelle.addClass('revient');     // la page précédente revient par-dessus
        }
        finTour = setTimeout(terminerTour, DUREE_TOUR + 50);
      }
      $.each(pages, function (k, p) {
        var visible = k === index;
        // Les éléments d'une page qui apparaît entrent l'un après l'autre.
        if (visible && !p.$p.hasClass('visible')) {
          p.$p.removeClass('entree');
          p.$p[0].offsetWidth;
          p.$p.addClass('entree');
        }
        p.$p.toggleClass('visible', visible).attr('aria-hidden', visible ? null : 'true');
        p.$p[0].inert = !visible;
        if (visible) p.$corps.scrollTop(0);
      });
      majEtapes(index, false);
      $prev.prop('disabled', index === 0);
      $next.prop('disabled', index >= total - 1);
      $num.text('Page ' + (index + 1) + ' / ' + total);
      $select.val(pages[index].partie || '');
      $bar.css('width', ((index + 1) / total) * 100 + '%');
      if (window.history && history.replaceState) {
        history.replaceState(null, '', '#p' + (index + 1));
      }
    }

    function pageDePartie(id) {
      for (var k = 0; k < pages.length; k++) {
        if (pages[k].partie === id) return k;
      }
      return 0;
    }

    function suivante() { if (courante + parVue < pages.length) afficher(courante + parVue); }
    function precedente() { if (courante > 0) afficher(courante - parVue); }

    function depuisAdresse() {
      var h = window.location.hash;
      var m = /^#p(\d+)$/.exec(h);
      if (m) return parseInt(m[1], 10) - 1;
      if (h && partieParId[h.slice(1)]) return pageDePartie(h.slice(1));
      return 0;
    }

    // ---------- Commandes ----------
    $next.on('click', suivante);
    $prev.on('click', precedente);
    $select.on('change', function () { afficher(this.value ? pageDePartie(this.value) : 0); });
    $feuilles.on('click', '.bloc-sommaire a', function (event) {
      event.preventDefault();
      afficher(pageDePartie(this.getAttribute('href').slice(1)));
      $next.trigger('focus');
    });
    $feuilles.on('click', '[data-haut]', function (event) {
      event.preventDefault();
      afficher(0);
      $prev.prop('disabled') ? $next.trigger('focus') : $prev.trigger('focus');
    });
    $(document).on('keydown', function (event) {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if ($(event.target).is('input, select, textarea, [contenteditable]')) return;
      var touche = event.key;
      if ($root.hasClass('noir') && touche !== 'Escape') {   // écran noir : une touche le rallume
        noir(false); event.preventDefault(); return;
      }
      if (touche === 'ArrowRight' || touche === 'PageDown' || touche === ' ' || touche === 'Enter') {
        if ((touche === ' ' || touche === 'Enter') && $(event.target).is('button, a, summary')) return;
        avancer(); event.preventDefault();
      }
      else if (touche === 'ArrowDown' && enPresentation()) { suivante(); event.preventDefault(); }
      else if (touche === 'ArrowUp' && enPresentation()) { precedente(); event.preventDefault(); }
      else if ((touche === 'a' || touche === 'A') && enPresentation()) { toutAfficher(); event.preventDefault(); }
      else if (touche === 'p' || touche === 'P' || touche === 'F5') { presenter(!$root.hasClass('presentation')); event.preventDefault(); }
      else if (touche === 'b' || touche === 'B' || touche === '.') { if ($root.hasClass('presentation')) { noir(true); event.preventDefault(); } }
      else if (touche === 'Escape') { if ($root.hasClass('noir')) noir(false); else if ($root.hasClass('presentation')) presenter(false); }
      else if (touche === 'ArrowLeft' || touche === 'PageUp') { reculer(); event.preventDefault(); }
      else if (touche === 'Home') { afficher(0); event.preventDefault(); }
      else if (touche === 'End') { afficher(pages.length - 1); event.preventDefault(); }
    });

    // Glisser le doigt vers la gauche ou la droite pour tourner la page.
    var depart = null;
    $scene.on('pointerdown', function (event) {
      var e = event.originalEvent;
      if (e.pointerType === 'mouse') return;
      var formule = $(e.target).closest('mjx-container[display="true"]')[0];
      if (formule && formule.scrollWidth > formule.clientWidth) return;   // formule large : on la fait défiler
      depart = { x: e.clientX, y: e.clientY };
    });
    $scene.on('pointerup pointercancel', function (event) {
      var e = event.originalEvent;
      if (!depart) return;
      var dx = e.clientX - depart.x;
      var dy = e.clientY - depart.y;
      depart = null;
      if (event.type !== 'pointerup' || Math.abs(dx) < 50 || Math.abs(dx) < 1.5 * Math.abs(dy)) return;
      if (dx < 0) suivante(); else precedente();
    });

    // ---------- Mode présentation (vidéoprojecteur) ----------
    var $presenter = $('#coursPresenter');
    var $quitter = $('#pageQuitter');
    var repos = null;

    function plein() { return document.fullscreenElement || document.webkitFullscreenElement; }

    function presenter(actif) {
      if (actif && !$presenter.length) return;   // réservé aux professeurs (bouton absent sinon)
      if (actif === $root.hasClass('presentation')) return;
      $root.toggleClass('presentation', actif);
      $presenter.attr('aria-pressed', actif ? 'true' : 'false');
      if (actif) {
        var el = document.documentElement;
        var demande = el.requestFullscreen || el.webkitRequestFullscreen;
        if (demande && !plein()) {
          try { var r = demande.call(el); if (r && r.catch) r.catch(function () {}); } catch (e) { /* refusé */ }
        }
        bouger();
      } else {
        noir(false);
        $root.removeClass('calme');
        clearTimeout(repos);
        var sortir = document.exitFullscreen || document.webkitExitFullscreen;
        if (sortir && plein()) { try { var q = sortir.call(document); if (q && q.catch) q.catch(function () {}); } catch (e) { /* déjà sorti */ } }
      }
      taille = '';
      if (pages.length) afficher(paginer(), true);
    }

    function noir(actif) { $root.toggleClass('noir', !!actif); }

    // En présentation, la barre et le curseur s'effacent quand la souris ne bouge plus.
    function bouger() {
      $root.removeClass('calme');
      clearTimeout(repos);
      if ($root.hasClass('presentation')) repos = setTimeout(function () { $root.addClass('calme'); }, 2500);
    }

    $presenter.on('click', function () { presenter(!$root.hasClass('presentation')); });
    $quitter.on('click', function () { presenter(false); });
    $('#ecranNoir').on('click', function () { noir(false); });
    $(document).on('mousemove pointerdown', bouger);
    $(document).on('fullscreenchange webkitfullscreenchange', function () {
      if (!plein() && $root.hasClass('presentation')) presenter(false);   // sortie par Échap
    });

    // ---------- Construction, puis reconstruction si la taille de l'écran change ----------
    var attente = null;
    function reconstruire() {
      clearTimeout(attente);
      attente = setTimeout(function () {
        var h = $scene.height();
        var nouvelle = $scene.width() + 'x' + h;
        if (nouvelle === taille) return;
        // Barre d'adresse du téléphone : petite variation de hauteur, rien à refaire.
        var ancienne = taille.split('x');
        if (+ancienne[0] === $scene.width() && Math.abs(+ancienne[1] - h) < 60 && parVue === 1
            && !$root.hasClass('presentation')) return;
        var cible = paginer();
        if (enPresentation() && pages[cible]) pages[cible].vu = pages[cible].etapes.length;
        afficher(cible, true);
      }, 200);
    }

    $.when(mathPret, policesPretes()).always(function () {
      var cible = paginer();
      var demande = depuisAdresse();
      afficher(demande || cible, true);
      $root.addClass('pagine-pret');
      $(window).on('resize orientationchange', reconstruire);
      if (document.fonts && document.fonts.addEventListener) {
        document.fonts.addEventListener('loadingdone', function () { taille = ''; reconstruire(); });
      }
    });
  });
})(jQuery);
