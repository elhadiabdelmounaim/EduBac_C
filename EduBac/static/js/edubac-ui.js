/**
 * EduBac UI interactions
 */
(function ($) {
  'use strict';

  function initFadeUp() {
    var $els = $('.fade-up');
    if (!$els.length) return;
    function reveal() {
      var wh = $(window).height();
      var st = $(window).scrollTop();
      $els.each(function () {
        var $el = $(this);
        if ($el.hasClass('is-visible')) return;
        if ($el.offset().top < st + wh - 40) {
          $el.addClass('is-visible');
        }
      });
    }
    $els.each(function (i) {
      var $el = $(this);
      if ($el.offset().top < $(window).height()) {
        setTimeout(function () { $el.addClass('is-visible'); }, i * 60);
      }
    });
    $(window).on('scroll.edubac resize.edubac', reveal);
    reveal();
  }

  function initRipple() {
    $(document).on('click', '.btn-edubac, .btn-accent', function (e) {
      var $btn = $(this);
      var offset = $btn.offset();
      var x = e.pageX - offset.left;
      var y = e.pageY - offset.top;
      var $ripple = $('<span class="ripple"></span>');
      var size = Math.max($btn.outerWidth(), $btn.outerHeight());
      $ripple.css({
        width: size,
        height: size,
        left: x - size / 2,
        top: y - size / 2
      });
      $btn.append($ripple);
      setTimeout(function () { $ripple.remove(); }, 650);
    });
  }

  function initPasswordToggle() {
    $(document).on('click', '.password-toggle', function () {
      var id = $(this).data('target');
      var $input = id ? $('#' + id) : $(this).siblings('input');
      var $icon = $(this).find('i');
      if (!$input.length) return;
      if ($input.attr('type') === 'password') {
        $input.attr('type', 'text');
        $icon.removeClass('bi-eye').addClass('bi-eye-slash');
      } else {
        $input.attr('type', 'password');
        $icon.removeClass('bi-eye-slash').addClass('bi-eye');
      }
    });
  }

  function initSmoothCards() {
    $('.card, .level-card, .stat-pill').addClass('fade-up');
  }

  function initActiveSidebar() {
    var path = window.location.pathname;
    $('.sidebar-nav .nav-link').each(function () {
      var href = $(this).attr('href');
      if (href && path.indexOf(href) === 0 && href !== '/') {
        $(this).addClass('active');
      }
    });
  }

  function initActiveBottomNav() {
    var path = window.location.pathname;
    $('.bottom-nav .bn-item').each(function () {
      var href = $(this).attr('href') || '';
      if (!href) return;
      // Match dashboard root or path prefix
      if (path === href || (href !== '/' && path.indexOf(href) === 0)) {
        $(this).addClass('active');
      }
    });
    // Prefer more specific match
    var $active = $('.bottom-nav .bn-item.active');
    if ($active.length > 1) {
      $active.removeClass('active');
      var best = null, bestLen = -1;
      $('.bottom-nav .bn-item').each(function () {
        var href = $(this).attr('href') || '';
        if (href && path.indexOf(href) === 0 && href.length > bestLen) {
          best = this;
          bestLen = href.length;
        }
      });
      if (best) $(best).addClass('active');
    }
  }

  function initAlertsAutoHide() {
    $('.messages .alert, main .alert-dismissible').each(function (i) {
      var $a = $(this);
      setTimeout(function () {
        $a.fadeOut(400, function () { $(this).remove(); });
      }, 5000 + i * 400);
    });
  }

  function initFormLoading() {
    $(document).on('submit', 'form[data-loading]', function () {
      $('.edubac-loading').addClass('show');
    });
  }

  /** Lightweight confetti for achievements */
  function celebrate(x, y) {
    var colors = ['#1a6b6b', '#70A974', '#DD8826', '#2A0C3D', '#F3E6A7', '#5ec4c4'];
    for (var i = 0; i < 28; i++) {
      var el = document.createElement('div');
      el.className = 'confetti-piece';
      el.style.left = (x || window.innerWidth / 2) + (Math.random() * 80 - 40) + 'px';
      el.style.top = (y || 120) + 'px';
      el.style.background = colors[i % colors.length];
      el.style.animationDelay = (Math.random() * 0.25) + 's';
      el.style.transform = 'rotate(' + (Math.random() * 360) + 'deg)';
      document.body.appendChild(el);
      setTimeout(function (node) { node.remove(); }, 2000, el);
    }
  }

  function initCelebrateTriggers() {
    // Trigger on badge cards if data-celebrate
    $('[data-celebrate]').addClass('celebrate-pop');
    if ($('[data-celebrate]').length) {
      setTimeout(function () { celebrate(); }, 300);
    }
    window.EduBacCelebrate = celebrate;
  }

  function initTableLabels() {
    // Auto data-label for mobile table-to-cards
    $('table.table-to-cards').each(function () {
      var headers = [];
      $(this).find('thead th').each(function () {
        headers.push($(this).text().trim());
      });
      $(this).find('tbody tr').each(function () {
        $(this).find('td').each(function (i) {
          if (!$(this).attr('data-label') && headers[i]) {
            $(this).attr('data-label', headers[i]);
          }
        });
      });
    });
  }

  $(function () {
    initSmoothCards();
    initFadeUp();
    initRipple();
    initPasswordToggle();
    initActiveSidebar();
    initActiveBottomNav();
    initAlertsAutoHide();
    initFormLoading();
    initCelebrateTriggers();
    initTableLabels();

    $('.table-hover tbody tr').css('cursor', 'default');
  });
})(jQuery);
