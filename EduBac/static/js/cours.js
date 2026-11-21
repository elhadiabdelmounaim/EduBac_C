/* Cours en ligne (HTML), présenté comme un cahier : le contenu est réparti en pages
   à la taille de l'écran, tournées avec les boutons, les flèches du clavier ou un
   glissement du doigt (deux pages côte à côte sur grand écran).
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

    var pages = [];
    var suites = [];        // blocs « suite » créés lors du découpage
    var courante = 0;
    var parVue = 1;
    var largeur = 0;
    var ecart = 16;
    var taille = '';
    var titre = $source.data('titre') || document.title;

    function estTitre(el) { return el && /^H[23]$/.test(el.tagName); }

    function nouvellePage(partie) {
      var $p = $('<article>', { 'class': 'feuille', 'aria-roledescription': 'page' });
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
      return $(el).children().not('.tag').first()[0];
    }

    // Déplace le dernier morceau de « src » au début de « dst » (structure identique).
    function retirerDernier(src, dst, miroirs) {
      for (;;) {
        var enfants = $(src).children().not('.tag').toArray();
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
      var $suite = $('<div>', { 'class': $bloc.attr('class').replace(/\s*\bsuite\b/, '') + ' suite' })
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
      for (var k = mouvements.length - 1; k >= 0; k--) $(mouvements[k].parent).append(mouvements[k].el);
      mouvements = [];
      $(suites).remove();
      suites = [];
      $.each(unites, function (_, u) { $(u.el).detach(); });
      $feuilles.empty();
      pages = [];
    }

    function mesurer() {
      var w = $scene.width();
      var h = $scene.height();
      parVue = (w >= 1100 && h >= 480) ? 2 : 1;
      ecart = parVue === 2 ? 30 : 16;
      var marge = w < 640 ? 10 : 24;
      largeur = parVue === 2
        ? Math.floor((Math.min(w, 1500) - 2 * marge - ecart) / 2)
        : Math.min(w - 2 * marge, 780);
      $feuilles.css({ '--page-w': largeur + 'px', '--gap': ecart + 'px' });
      return w + 'x' + h;
    }

    function paginer() {
      var ancre = pages.length ? premiereUnite(courante) : null;
      defaire();
      taille = mesurer();
      var page = nouvellePage('');
      for (var i = 0; i < unites.length; i++) {
        var u = unites[i];
        if (u.rupture && page.$corps.children().length) page = nouvellePage(u.partie);
        if (!page.partie) page.partie = u.partie;
        page.$corps.append(u.el);
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
        p.$p.toggleClass('gauche', parVue === 2 && k % 2 === 0);
      });
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

    function afficher(index, sansAnimation) {
      var total = pages.length;
      index = Math.max(0, Math.min(index, total - 1));
      index -= index % parVue;
      courante = index;
      var w = $scene.width();
      var gauche = (w - (parVue * largeur + (parVue - 1) * ecart)) / 2;
      if (sansAnimation) $feuilles.css('transition', 'none');
      $feuilles.css('transform', 'translateX(' + Math.round(gauche - index * (largeur + ecart)) + 'px)');
      if (sansAnimation) { $feuilles[0].offsetWidth; $feuilles.css('transition', ''); }
      $.each(pages, function (k, p) {
        var visible = k >= index && k < index + parVue;
        p.$p.toggleClass('visible', visible).attr('aria-hidden', visible ? null : 'true');
        p.$p[0].inert = !visible;
        if (visible) p.$corps.scrollTop(0);
      });
      var derniere = Math.min(index + parVue, total);
      $prev.prop('disabled', index === 0);
      $next.prop('disabled', derniere >= total);
      $num.text(derniere - index > 1 ? 'Pages ' + (index + 1) + '–' + derniere + ' / ' + total
                                     : 'Page ' + (index + 1) + ' / ' + total);
      $select.val(pages[index].partie || '');
      $bar.css('width', (derniere / total) * 100 + '%');
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
      if (touche === 'ArrowRight' || touche === 'PageDown') { suivante(); event.preventDefault(); }
      else if (touche === 'ArrowLeft' || touche === 'PageUp') { precedente(); event.preventDefault(); }
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
        if (+ancienne[0] === $scene.width() && Math.abs(+ancienne[1] - h) < 60 && parVue === 1) return;
        afficher(paginer(), true);
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
