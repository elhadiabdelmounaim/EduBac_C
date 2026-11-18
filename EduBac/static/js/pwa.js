/**
 * EduBac installable : enregistrement du service worker, bouton « Installer
 * l'application », invitation discrète, aide pour iPhone, pastille d'icône.
 */
(function () {
  'use strict';
  var ua = navigator.userAgent || '';
  var standalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
    || window.navigator.standalone === true;
  var isIOS = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var isIOSSafari = isIOS && /safari/i.test(ua) && !/crios|fxios|edgios|opios/i.test(ua);
  var deferredPrompt = null;
  var BANNER_KEY = 'edubac-pwa-banner';
  var VISITS_KEY = 'edubac-pwa-visits';

  document.documentElement.classList.toggle('is-standalone', !!standalone);

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { return null; }
    return value;
  }

  /* ---- Service worker (HTTPS, ou localhost en développement) ---- */
  var secure = window.isSecureContext || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  if ('serviceWorker' in navigator && secure) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/service-worker.js', { scope: '/' }).catch(function () {
        /* Le site fonctionne normalement sans service worker. */
      });
    });
  }

  /* ---- Bouton et invitation d'installation ---- */
  function installButtons() { return document.querySelectorAll('[data-pwa-install]'); }
  function canOfferInstall() { return !standalone && (deferredPrompt || isIOS); }

  function refreshButtons() {
    var show = !!canOfferInstall();
    installButtons().forEach(function (button) { button.hidden = !show; });
  }

  function banner() { return document.getElementById('pwaBanner'); }

  function hideBanner(remember) {
    var el = banner();
    if (el) el.hidden = true;
    if (remember) store(BANNER_KEY, String(Date.now()));
  }

  function maybeShowBanner() {
    var el = banner();
    if (!el || !canOfferInstall()) return;
    var dismissed = Number(store(BANNER_KEY) || 0);
    if (dismissed && Date.now() - dismissed < 14 * 86400000) return;
    // Pas dès la première page : seulement après quelques visites.
    if (Number(store(VISITS_KEY) || 0) < 3) return;
    if (document.querySelector('.chat-app, .wb-app, .quiz-taking, [data-no-install-banner]')) return;
    el.hidden = false;
  }

  function openHelp() {
    var dialog = document.getElementById('pwaHelp');
    if (!dialog) return;
    document.getElementById('pwaHelpIos').hidden = !isIOS;
    document.getElementById('pwaHelpOther').hidden = isIOS;
    document.getElementById('pwaHelpNote').hidden = !isIOS || isIOSSafari;
    if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
  }

  function install() {
    hideBanner(true);
    if (deferredPrompt) {
      var prompt = deferredPrompt;
      deferredPrompt = null;
      prompt.prompt();
      prompt.userChoice.finally(refreshButtons);
      return;
    }
    openHelp();
  }

  window.addEventListener('beforeinstallprompt', function (event) {
    event.preventDefault();
    deferredPrompt = event;
    refreshButtons();
    maybeShowBanner();
  });
  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    hideBanner(true);
    refreshButtons();
  });

  document.addEventListener('DOMContentLoaded', function () {
    if (!standalone) store(VISITS_KEY, String(Number(store(VISITS_KEY) || 0) + 1));
    installButtons().forEach(function (button) { button.addEventListener('click', install); });
    var close = document.getElementById('pwaBannerClose');
    if (close) close.addEventListener('click', function () { hideBanner(true); });
    var helpClose = document.getElementById('pwaHelpClose');
    if (helpClose) helpClose.addEventListener('click', function () { document.getElementById('pwaHelp').close(); });
    refreshButtons();
    if (isIOS) maybeShowBanner();
    watchBadge();
  });

  /* ---- Pastille sur l'icône de l'application (notifications non lues) ---- */
  function watchBadge() {
    var badge = document.getElementById('notifBadge');
    if (!badge || !('setAppBadge' in navigator)) return;
    function sync() {
      var count = badge.classList.contains('d-none') ? 0 : parseInt(badge.textContent, 10) || 0;
      var action = count ? navigator.setAppBadge(count) : navigator.clearAppBadge();
      if (action && action.catch) action.catch(function () {});
    }
    new MutationObserver(sync).observe(badge, { childList: true, characterData: true, subtree: true, attributes: true });
    sync();
  }
})();
