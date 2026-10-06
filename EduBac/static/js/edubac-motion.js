/**
 * EduBac: quiet jQuery entrances and mathematical drift.
 * Animate numeric drivers, writing only translate/transform and opacity;
 * card hover transforms and layout coordinates remain untouched.
 */
(function ($) {
  'use strict';
  if (!$) return;

  $(function () {
    var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    var mobile = window.matchMedia('(max-width: 767.98px)');
    var $control = $('#edubacMotionToggle');
    var $background = $('.edubac-motion-background');
    var decorations = [];
    var entrances = [];
    var observer;
    var paused = false;
    try { paused = localStorage.getItem('edubac-motion-paused') === 'true'; } catch (e) {}

    function canMove() {
      return !paused && !reduced.matches && !document.hidden;
    }

    function finishEntrance(item) {
      $(item.driver).stop(true, false);
      item.el.style.opacity = item.opacity;
      item.el.style.translate = item.translate;
      item.done = true;
    }

    function enter(item) {
      if (item.done) return;
      item.done = true;
      if (!canMove()) return;
      $(item.driver).animate({ progress: 1 }, {
        duration: 420,
        easing: 'swing',
        queue: false,
        step: function (value) {
          item.el.style.opacity = String(0.86 + value * 0.14);
          item.el.style.translate = '0 ' + ((1 - value) * 10) + 'px';
        },
        complete: function () { finishEntrance(item); }
      });
    }

    function drift(item) {
      if (!canMove()) return;
      $(item.driver).animate({ progress: item.target }, {
        duration: Math.max(1, Math.abs(item.target - item.driver.progress) * item.duration),
        easing: 'swing',
        queue: false,
        step: function (value) {
          item.el.style.transform = 'translate(' +
            (Math.sin(value * Math.PI) * item.x) + 'px, ' +
            (-value * item.y) + 'px)';
        },
        complete: function () {
          item.target = item.target === 1 ? 0 : 1;
          drift(item);
        }
      });
    }

    function synchronize() {
      var moving = canMove();
      $('body').attr('data-edubac-motion', moving ? 'running' : 'paused');
      $control.prop('hidden', false).prop('disabled', reduced.matches)
        .attr('aria-pressed', String(paused || reduced.matches))
        .text(reduced.matches ? 'Animations réduites' :
          (paused ? 'Reprendre les animations' : 'Mettre les animations en pause'));
      decorations.forEach(function (item) {
        $(item.driver).stop(true, false);
        if (reduced.matches) {
          item.el.style.transform = item.transform;
          item.driver.progress = 0;
          item.target = 1;
        }
        if (moving) drift(item);
      });
      if (!moving) entrances.forEach(finishEntrance);
    }

    function makeDecorations() {
      decorations.forEach(function (item) {
        $(item.driver).stop(true, false);
        item.el.style.transform = item.transform;
      });
      decorations = [];
      $background.empty();
      var symbols = ['∑', 'π', '√', '∞', '∫', 'Δ', '≈', 'ℕ'];
      var positions = [[5, 9], [87, 23], [12, 54], [78, 72],
        [42, 15], [60, 44], [30, 82], [91, 91]];
      var count = mobile.matches ? 3 : symbols.length;
      for (var i = 0; i < count; i++) {
        $('<span class="edubac-motion-symbol" aria-hidden="true"></span>')
          .text(symbols[i]).css({ left: positions[i][0] + '%', top: positions[i][1] + '%' })
          .appendTo($background);
      }
      $('.edubac-motion-symbol, .hero-symbols span').each(function (index) {
        decorations.push({
          el: this, transform: this.style.transform,
          driver: { progress: 0 }, target: 1,
          duration: 9000 + (index % 4) * 1700,
          x: (index % 2 ? -1 : 1) * (mobile.matches ? 4 : 7),
          y: mobile.matches ? 7 : 12
        });
      });
      synchronize();
    }

    // Only the outermost entrance animates: no nested card/wrapper double motion.
    var selector = '.fade-up, .card, .level-card, .stat-pill, .quick-card, .auth-card';
    $('main').find(selector).filter(function () {
      return !$(this).parentsUntil('main').filter(selector).length;
    }).each(function () {
      entrances.push({
        el: this, opacity: this.style.opacity, translate: this.style.translate,
        driver: { progress: 0 }, done: false
      });
    });
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          var item = entrances.find(function (candidate) { return candidate.el === entry.target; });
          if (item) enter(item);
          observer.unobserve(entry.target);
        });
      }, { threshold: 0.08 });
      entrances.forEach(function (item) { observer.observe(item.el); });
    } else {
      entrances.forEach(enter);
    }

    $control.on('click.edubacMotion', function () {
      paused = !paused;
      try { localStorage.setItem('edubac-motion-paused', String(paused)); } catch (e) {}
      synchronize();
    });
    $(document).on('visibilitychange.edubacMotion', synchronize);
    function listen(query, callback) {
      if (query.addEventListener) query.addEventListener('change', callback);
      else query.addListener(callback);
    }
    listen(reduced, synchronize);
    listen(mobile, makeDecorations);
    makeDecorations();
  });
})(window.jQuery);
