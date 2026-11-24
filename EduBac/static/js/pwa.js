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

/**
 * Notifications sur le téléphone (Web Push) : bouton d'activation, réabonnement
 * silencieux, invitation dans l'application installée.
 */
(function () {
  'use strict';
  var config = window.EDUBAC_PUSH;
  if (!config) return;
  var ua = navigator.userAgent || '';
  var isIOS = /iphone|ipad|ipod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var standalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
  var supported = !!(config.publicKey && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window && window.isSecureContext);
  var BANNER_KEY = 'edubac-push-banner';

  function keyBytes(base64) {
    var padded = (base64 + '===='.slice(base64.length % 4)).replace(/-/g, '+').replace(/_/g, '/');
    var raw = atob(padded), bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    return bytes;
  }

  function send(url, body) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': config.csrfToken, Accept: 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) { if (!r.ok) throw new Error('refus'); return r.json(); });
  }

  function registration() { return navigator.serviceWorker.ready; }

  function currentSubscription() {
    return registration().then(function (reg) { return reg.pushManager.getSubscription(); });
  }

  function subscribe() {
    return registration().then(function (reg) {
      return reg.pushManager.getSubscription().then(function (existing) {
        return existing || reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(config.publicKey) });
      });
    }).then(function (subscription) {
      return send(config.subscribeUrl, subscription.toJSON()).then(function () { return subscription; });
    });
  }

  var SYNC_KEY = 'edubac-push-sync';
  function synchroniser(subscription) {
    var empreinte = [config.subscribeUrl, config.compte || '', subscription.endpoint].join('|');
    var dernier = null;
    try { dernier = JSON.parse(localStorage.getItem(SYNC_KEY) || 'null'); } catch (e) {}
    if (dernier && dernier.e === empreinte && Date.now() - dernier.t < 86400000) return;
    send(config.subscribeUrl, subscription.toJSON()).then(function () {
      try { localStorage.setItem(SYNC_KEY, JSON.stringify({ e: empreinte, t: Date.now() })); } catch (e) {}
    }).catch(function () {});
  }

  function unsubscribe() {
    return currentSubscription().then(function (subscription) {
      if (!subscription) return null;
      return send(config.unsubscribeUrl, { endpoint: subscription.endpoint }).catch(function () {})
        .then(function () { return subscription.unsubscribe(); });
    });
  }

  function render(state) {
    var labels = {
      on: ['Activées sur cet appareil', 'Désactiver', false],
      off: ['Recevez une alerte à chaque nouveau message, même EduBac fermé.', 'Activer', false],
      denied: ['Bloquées : autorisez EduBac dans les réglages du téléphone.', 'Activer', true],
      ios: ['Sur iPhone : installez d’abord EduBac sur l’écran d’accueil (Partager → Sur l’écran d’accueil), puis ouvrez-le depuis son icône.', 'Activer', true],
      busy: ['Activation…', '…', true],
    }[state];
    var t = config.textes && config.textes[state];
    if (t) labels = [t[0] || labels[0], t[1] || labels[1], t.length > 2 ? t[2] : labels[2]];
    document.querySelectorAll('[data-push-panel]').forEach(function (panel) { panel.hidden = false; });
    document.querySelectorAll('[data-push-status]').forEach(function (el) { el.textContent = labels[0]; });
    document.querySelectorAll('[data-push-toggle]').forEach(function (button) {
      button.textContent = labels[1];
      button.disabled = labels[2];
      button.dataset.pushState = state;
    });
    document.querySelectorAll('[data-push-test]').forEach(function (button) { button.hidden = state !== 'on'; });
    if (state !== 'off') hideBanner(false);
  }

  function runTest(event) {
    var button = event.currentTarget;
    var status = document.querySelector('[data-push-status]');
    button.disabled = true;
    fetch(button.dataset.url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'X-CSRFToken': config.csrfToken, Accept: 'application/json' },
    }).then(function (r) { return r.json(); }).then(function (data) {
      if (status) status.textContent = data.message || 'Réponse inattendue du serveur.';
    }).catch(function () {
      if (status) status.textContent = 'Le serveur n’a pas répondu : réessayez.';
    }).then(function () { button.disabled = false; });
  }

  function hideBanner(remember) {
    var banner = document.getElementById('pushBanner');
    if (banner) banner.hidden = true;
    if (remember) { try { localStorage.setItem(BANNER_KEY, String(Date.now())); } catch (e) {} }
  }

  function refresh() {
    if (!supported) { if (isIOS && !standalone && config.publicKey) render('ios'); return; }
    if (Notification.permission === 'denied') { render('denied'); return; }
    currentSubscription().then(function (subscription) {
      if (subscription && Notification.permission === 'granted') {
        render('on');
        // Garde le serveur à jour (réinstallation, changement de compte sur l'appareil),
        // mais pas à chaque page : une fois par jour, ou tout de suite si quelque chose a changé.
        synchroniser(subscription);
      } else {
        render('off');
        maybeBanner();
      }
    }).catch(function () { render('off'); });
  }

  function maybeBanner() {
    var banner = document.getElementById('pushBanner');
    if (!banner || !standalone) return;  // invitation dans l'application installée seulement
    var last = 0;
    try { last = Number(localStorage.getItem(BANNER_KEY) || 0); } catch (e) {}
    if (Date.now() - last < 7 * 86400000) return;
    var install = document.getElementById('pwaBanner');
    if (install && !install.hidden) return;
    banner.hidden = false;
  }

  function toggle(event) {
    var state = event.currentTarget.dataset.pushState;
    if (state === 'on') {
      unsubscribe().then(function () { render('off'); });
      return;
    }
    render('busy');
    Notification.requestPermission().then(function (permission) {
      if (permission !== 'granted') { render(permission === 'denied' ? 'denied' : 'off'); return null; }
      return subscribe().then(function () { render('on'); hideBanner(true); });
    }).catch(function () {
      render('off');
      document.querySelectorAll('[data-push-status]').forEach(function (el) {
        el.textContent = 'Activation impossible : le serveur a refusé l’enregistrement de cet appareil. Réessayez plus tard ou prévenez votre professeur.';
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-push-toggle]').forEach(function (button) { button.addEventListener('click', toggle); });
    document.querySelectorAll('[data-push-test]').forEach(function (button) { button.addEventListener('click', runTest); });
    var close = document.getElementById('pushBannerClose');
    if (close) close.addEventListener('click', function () { hideBanner(true); });
    if (supported) {
      navigator.serviceWorker.addEventListener('message', function (event) {
        if (event.data && event.data.type === 'edubac-push-resubscribe' && Notification.permission === 'granted') {
          subscribe().catch(function () {});
        }
      });
    }
    refresh();
  });
})();
