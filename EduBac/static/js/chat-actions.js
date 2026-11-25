/**
 * Outils partagés des messageries EduBac : actions sur les messages
 * (modifier, supprimer, signaler), rendu LaTeX et connexion temps réel.
 */
(function () {
  'use strict';

  var EDIT_WINDOW_MS = 5 * 60 * 1000;

  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (match) return decodeURIComponent(match[1]);
    var input = document.querySelector('[name="csrfmiddlewaretoken"]');
    if (input) return input.value;
    var app = document.querySelector('[data-csrf]');
    return app ? app.getAttribute('data-csrf') : '';
  }

  async function api(url, payload) {
    var response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        'X-CSRFToken': csrfToken(),
      },
      body: JSON.stringify(payload || {}),
    });
    var type = (response.headers.get('content-type') || '').toLowerCase();
    if (!type.includes('application/json')) {
      throw new Error(response.redirected || response.status === 401
        ? 'Votre session a expiré. Reconnectez-vous.'
        : 'Réponse inattendue du serveur. Actualisez la page.');
    }
    var data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Action impossible.');
    return data;
  }

  /** L'auteur peut modifier un message texte pendant 5 minutes. */
  function canEdit(message, userId) {
    if (!message || message.is_deleted || message.is_voice || !message.body) return false;
    if (String(message.sender_id) !== String(userId)) return false;
    var sent = Date.parse(message.created_at);
    return !isNaN(sent) && Date.now() - sent < EDIT_WINDOW_MS;
  }

  function messageUrl(kind, id, action) {
    return '/chat/api/messages/' + kind + '/' + id + '/' + action + '/';
  }

  function editMessage(kind, message) {
    var body = window.prompt('Modifier le message :', message.body || '');
    if (body === null) return Promise.resolve(null);
    body = body.trim();
    if (!body || body === message.body) return Promise.resolve(null);
    return api(messageUrl(kind, message.id, 'edit'), { body: body }).then(function (d) { return d.message; });
  }

  function deleteMessage(kind, message, asModerator) {
    var question = asModerator && !message.mine
      ? 'Supprimer ce message pour toute la conversation ?'
      : 'Supprimer votre message ?';
    if (!window.confirm(question)) return Promise.resolve(null);
    return api(messageUrl(kind, message.id, 'delete')).then(function (d) { return d.message; });
  }

  var REASONS = [
    ['harassment', 'Harcèlement ou insulte'],
    ['inappropriate', 'Contenu inapproprié'],
    ['spam', 'Spam ou hors sujet'],
    ['cheating', 'Triche (réponses de quiz)'],
    ['other', 'Autre'],
  ];

  var reportDialog = null;

  function buildReportDialog() {
    var dialog = document.createElement('dialog');
    dialog.className = 'chat-report-dialog';
    dialog.setAttribute('aria-labelledby', 'chatReportTitle');
    var form = document.createElement('form');
    form.method = 'dialog';
    var title = document.createElement('h2');
    title.id = 'chatReportTitle';
    title.textContent = 'Signaler ce message';
    var help = document.createElement('p');
    help.className = 'small text-muted';
    help.textContent = 'Le message et les quelques messages précédents seront transmis au professeur '
      + 'ou à l’administration. La personne signalée n’est pas informée de votre nom.';
    var fieldset = document.createElement('fieldset');
    var legend = document.createElement('legend');
    legend.className = 'small fw-semibold';
    legend.textContent = 'Motif';
    fieldset.append(legend);
    REASONS.forEach(function (reason, index) {
      var label = document.createElement('label');
      label.className = 'chat-report-reason';
      var radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'reason';
      radio.value = reason[0];
      if (index === 0) radio.checked = true;
      label.append(radio, ' ', reason[1]);
      fieldset.append(label);
    });
    var details = document.createElement('textarea');
    details.name = 'details';
    details.maxLength = 1000;
    details.rows = 3;
    details.className = 'form-control mt-2';
    details.placeholder = 'Précisions (facultatif)';
    details.setAttribute('aria-label', 'Précisions');
    var error = document.createElement('p');
    error.className = 'text-danger small mt-2';
    error.hidden = true;
    error.setAttribute('role', 'alert');
    var actions = document.createElement('div');
    actions.className = 'chat-dialog-actions';
    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'btn btn-outline-secondary btn-sm';
    cancel.textContent = 'Annuler';
    cancel.addEventListener('click', function () { dialog.close(); });
    var submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-danger btn-sm';
    submit.textContent = 'Envoyer le signalement';
    actions.append(cancel, submit);
    form.append(title, help, fieldset, details, error, actions);
    dialog.append(form);
    document.body.append(dialog);
    dialog._error = error;
    dialog._form = form;
    return dialog;
  }

  function reportMessage(kind, message) {
    reportDialog = reportDialog || buildReportDialog();
    var dialog = reportDialog;
    dialog._form.reset();
    dialog._error.hidden = true;
    return new Promise(function (resolve) {
      dialog._form.onsubmit = function (event) {
        event.preventDefault();
        var data = new FormData(dialog._form);
        api(messageUrl(kind, message.id, 'report'), {
          reason: data.get('reason'),
          details: data.get('details') || '',
        }).then(function () {
          dialog.close();
          window.alert('Merci. Le signalement a été transmis.');
          resolve(true);
        }).catch(function (err) {
          dialog._error.textContent = err.message;
          dialog._error.hidden = false;
        });
      };
      dialog.addEventListener('close', function () { resolve(false); }, { once: true });
      dialog.showModal();
    });
  }

  function renderMath(element) {
    if (!element) return;
    if (typeof window.renderMath === 'function') {
      window.renderMath(element);
    } else {
      document.addEventListener('DOMContentLoaded', function () {
        if (typeof window.renderMath === 'function') window.renderMath(element);
      }, { once: true });
    }
  }

  /**
   * Connexion WebSocket avec repli : `refresh` est appelé à chaque événement
   * et périodiquement (3 s sans WebSocket, 30 s avec, pour rattraper un oubli).
   */
  function liveUpdates(path, onEvent, refresh) {
    var socket = null;
    var connected = false;
    var timer = null;
    var retry = 1000;

    function schedule() {
      if (timer) window.clearInterval(timer);
      timer = window.setInterval(function () {
        if (!document.hidden || !connected) refresh();
      }, connected ? 30000 : 3000);
    }

    function connect() {
      if (!path || !window.WebSocket) return;
      try {
        var proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        socket = new WebSocket(proto + '//' + window.location.host + path);
      } catch (e) {
        return;
      }
      socket.onopen = function () { connected = true; retry = 1000; schedule(); refresh(); };
      socket.onmessage = function (event) {
        var data;
        try { data = JSON.parse(event.data); } catch (e) { return; }
        onEvent(data);
      };
      socket.onclose = function () {
        var wasConnected = connected;
        connected = false;
        if (wasConnected) schedule();
        window.setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30000);
      };
    }

    schedule();
    connect();
    window.addEventListener('pagehide', function () {
      if (timer) window.clearInterval(timer);
      if (socket) { socket.onclose = null; socket.close(); }
    }, { once: true });
    return { isConnected: function () { return connected; } };
  }

  /* ------------------------------------------------------------------
   * Présentation partagée des fils de discussion
   * ------------------------------------------------------------------ */

  var GROUP_WINDOW_MS = 5 * 60 * 1000;
  var AVATAR_TONES = 8;

  /** Teinte stable (0..7) dérivée d'un nom, pour les avatars à initiale. */
  function avatarTone(seed) {
    var text = String(seed || '');
    var hash = 0;
    for (var i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
    return Math.abs(hash) % AVATAR_TONES;
  }

  function paintAvatars(root) {
    (root || document).querySelectorAll('[data-avatar-seed]').forEach(function (el) {
      if (!el.hasAttribute('data-tone')) el.setAttribute('data-tone', String(avatarTone(el.getAttribute('data-avatar-seed'))));
    });
  }

  function toDate(iso) {
    if (!iso) return null;
    var date = new Date(iso);
    return isNaN(date.getTime()) ? null : date;
  }

  function dayKey(date) {
    return date.getFullYear() + '-' + (date.getMonth() + 1) + '-' + date.getDate();
  }

  function capitalize(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
  }

  /** « Aujourd'hui », « Hier » ou la date complète. */
  function dayLabel(date) {
    var today = new Date();
    var yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    if (dayKey(date) === dayKey(today)) return 'Aujourd’hui';
    if (dayKey(date) === dayKey(yesterday)) return 'Hier';
    return capitalize(date.toLocaleDateString('fr-FR', {
      weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
    }));
  }

  function timeLabel(iso, fallback) {
    var date = toDate(iso);
    if (!date) return fallback || '';
    return date.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }

  /** Heure courte pour la liste : 14:05, Hier, lundi ou 12/11/2026. */
  function listTimeLabel(iso) {
    var date = toDate(iso);
    if (!date) return '';
    var now = new Date();
    if (dayKey(date) === dayKey(now)) return timeLabel(iso);
    var yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (dayKey(date) === dayKey(yesterday)) return 'Hier';
    var days = (now - date) / 86400000;
    if (days < 6) return capitalize(date.toLocaleDateString('fr-FR', { weekday: 'long' }));
    return date.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  var TICK_SVG = {
    sent: '<svg viewBox="0 0 16 11" aria-hidden="true" focusable="false"><path d="M1.5 5.8 5 9.2l9.5-8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    read: '<svg viewBox="0 0 20 11" aria-hidden="true" focusable="false"><path d="M1.5 5.8 5 9.2l9.5-8M8.6 8.4l.8.8 9.1-8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  };

  /** Indicateur de statut : seuls « envoyé » et « lu » existent côté serveur. */
  function receipt(state) {
    var span = document.createElement('span');
    var read = state === 'read';
    span.className = 'chat-ticks' + (read ? ' is-read' : '');
    span.innerHTML = TICK_SVG[read ? 'read' : 'sent'];
    var label = read ? 'Lu' : 'Envoyé';
    span.title = label;
    span.setAttribute('role', 'img');
    span.setAttribute('aria-label', label);
    return span;
  }

  /** Texte du message : liens http(s) cliquables, sans jamais interpréter de HTML. */
  function renderText(element, text) {
    element.textContent = '';
    // Liens web, et liens internes vers un tableau partagé (/tableau/12/).
    var pattern = /\bhttps?:\/\/[^\s<>"']+|(?:^|(?<=\s))\/tableau\/\d+\//gi;
    var last = 0;
    var match;
    text = String(text || '');
    while ((match = pattern.exec(text))) {
      var url = match[0].replace(/[.,;:!?)]+$/, '');
      if (match.index > last) element.append(text.slice(last, match.index));
      var link = document.createElement('a');
      link.href = url;
      var internal = url.charAt(0) === '/';
      link.textContent = internal ? 'Ouvrir le tableau' : url;
      if (!internal) { link.target = '_blank'; link.rel = 'noopener noreferrer'; }
      link.className = 'chat-link' + (internal ? ' chat-link-board' : '');
      element.append(link);
      last = match.index + url.length;
      pattern.lastIndex = last;
    }
    if (last < text.length) element.append(text.slice(last));
  }

  function lastRowOf(container) {
    var rows = container.querySelectorAll('.chat-bubble-row');
    return rows.length ? rows[rows.length - 1] : null;
  }

  /**
   * Insère (ou remplace) la ligne d'un message : séparateur de jour,
   * regroupement des messages consécutifs d'un même auteur, animation.
   */
  function placeMessage(container, row, message, existing, animate) {
    var date = toDate(message.created_at);
    var key = date ? dayKey(date) : '';
    row.setAttribute('data-day', key);
    row.setAttribute('data-sender', String(message.sender_id));
    row.setAttribute('data-ts', date ? String(date.getTime()) : '0');
    if (existing) {
      if (existing.classList.contains('is-continuation')) row.classList.add('is-continuation');
      existing.replaceWith(row);
      return row;
    }
    var previous = lastRowOf(container);
    if (!previous || previous.getAttribute('data-day') !== key) {
      if (date) {
        var separator = document.createElement('div');
        separator.className = 'chat-day-sep';
        separator.setAttribute('role', 'separator');
        var label = document.createElement('span');
        label.textContent = dayLabel(date);
        separator.append(label);
        container.append(separator);
      }
    } else if (
      previous.getAttribute('data-sender') === String(message.sender_id)
      && !previous.classList.contains('is-announcement')
      && !message.is_announcement
      && date
      && date.getTime() - Number(previous.getAttribute('data-ts')) < GROUP_WINDOW_MS
    ) {
      row.classList.add('is-continuation');
    }
    if (animate) {
      row.classList.add('is-new');
      row.addEventListener('animationend', function () { row.classList.remove('is-new'); }, { once: true });
    }
    container.append(row);
    return row;
  }

  /**
   * Défilement : reste en bas si l'utilisateur y est déjà, sinon affiche
   * un bouton « derniers messages » avec le nombre de nouveaux messages.
   */
  function scroller(container, button) {
    var unseen = 0;
    var count = button ? button.querySelector('.chat-jump-count') : null;
    function nearBottom() {
      return container.scrollHeight - container.scrollTop - container.clientHeight < 120;
    }
    function render() {
      if (!button) return;
      button.hidden = nearBottom();
      if (count) {
        count.hidden = !unseen;
        count.textContent = unseen > 99 ? '99+' : String(unseen);
      }
    }
    function toBottom(smooth) {
      unseen = 0;
      container.scrollTo({ top: container.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
      render();
    }
    container.addEventListener('scroll', function () {
      if (nearBottom()) unseen = 0;
      render();
    }, { passive: true });
    if (button) button.addEventListener('click', function () { toBottom(true); });
    return {
      nearBottom: nearBottom,
      toBottom: toBottom,
      /** À appeler avant d'insérer de nouveaux messages. */
      follow: function (incoming, mine) {
        var stick = mine || nearBottom();
        return function () {
          if (stick) toBottom(false);
          else { unseen += incoming; render(); }
        };
      },
    };
  }

  /**
   * Barre de saisie : hauteur automatique, bascule micro ↔ envoyer,
   * Entrée envoie sur ordinateur (retour à la ligne sur écran tactile).
   */
  function composer(form, input, hasAttachment) {
    var coarse = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    function refresh() {
      input.style.height = 'auto';
      input.style.height = Math.min(input.scrollHeight, 140) + 'px';
      var filled = !!input.value.trim() || !!(hasAttachment && hasAttachment());
      form.classList.toggle('has-content', filled);
    }
    input.addEventListener('input', refresh);
    input.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
      if (coarse) return;
      event.preventDefault();
      if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event('submit', { cancelable: true }));
    });
    refresh();
    return { refresh: refresh };
  }

  // ─── Citation (réponse à un message) ───────────────────────────────────────
  /** Citation affichée dans la bulle ; un clic amène au message d'origine (`idPrefix` + id). */
  function replyQuote(reply, idPrefix) {
    var quote = document.createElement('button');
    quote.type = 'button';
    quote.className = 'chat-reply-quote';
    quote.title = 'Voir le message d’origine';
    var name = document.createElement('strong');
    name.textContent = reply.sender_name || '';
    var text = document.createElement('span');
    text.textContent = reply.body || '';
    quote.append(name, text);
    // Formule rendue seulement si la citation n'a pas coupé un « $…$ ».
    if (((reply.body || '').match(/\$/g) || []).length % 2 === 0) renderMath(text);
    quote.addEventListener('click', function () {
      var original = document.getElementById(idPrefix + reply.id);
      if (!original) return;
      original.scrollIntoView({ behavior: 'smooth', block: 'center' });
      original.classList.add('is-highlighted');
      setTimeout(function () { original.classList.remove('is-highlighted'); }, 1600);
    });
    return quote;
  }

  /** Extrait montré dans la bande « Répondre à … » au-dessus de la saisie. */
  function replyExcerpt(message) {
    return (message.body || message.attachment_name || (message.is_voice ? 'Message vocal' : 'Message')).slice(0, 80);
  }

  // ─── Réactions ──────────────────────────────────────────────────────────────
  var REACTIONS = [
    ['👍', 'J’aime'], ['❤️', 'J’adore'], ['😂', 'Drôle'], ['😮', 'Surprenant'],
    ['✅', 'Compris'], ['❓', 'Pas compris'],
  ];
  var picker = null;

  function react(kind, message, emoji) {
    return api(messageUrl(kind, message.id, 'react'), { emoji: emoji }).then(function (d) { return d.message; });
  }

  function reactAndRender(kind, message, emoji, onUpdated) {
    react(kind, message, emoji).then(onUpdated).catch(function (error) {
      window.alert(error.message || 'Réaction impossible.');
    });
  }

  function closePicker() {
    if (picker) { picker.hidden = true; picker._anchor = null; }
  }

  /** Palette des six réactions, ouverte près du bouton « Réagir ». */
  function openPicker(anchor, kind, message, onUpdated) {
    if (!picker) {
      picker = document.createElement('div');
      picker.className = 'chat-reaction-picker';
      picker.setAttribute('role', 'menu');
      picker.hidden = true;
      document.body.append(picker);
      document.addEventListener('click', function (event) {
        if (picker.hidden || picker.contains(event.target) || (picker._anchor && picker._anchor.contains(event.target))) return;
        closePicker();
      });
      document.addEventListener('keydown', function (event) { if (event.key === 'Escape') closePicker(); });
      window.addEventListener('scroll', closePicker, true);
    }
    if (picker._anchor === anchor && !picker.hidden) { closePicker(); return; }
    picker.replaceChildren();
    var current = (message.reactions || []).filter(function (r) { return r.mine; }).map(function (r) { return r.emoji; })[0];
    REACTIONS.forEach(function (item) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'chat-reaction-choice' + (item[0] === current ? ' is-mine' : '');
      button.setAttribute('role', 'menuitem');
      button.title = item[1];
      button.setAttribute('aria-label', item[1]);
      button.dataset.emoji = item[0];
      button.append(document.createTextNode(item[0]));
      if (item[0] === '✅' || item[0] === '❓') {
        var small = document.createElement('small');
        small.textContent = item[1];
        button.append(small);
      }
      button.addEventListener('click', function () {
        closePicker();
        reactAndRender(kind, message, item[0], onUpdated);
      });
      picker.append(button);
    });
    picker._anchor = anchor;
    picker.hidden = false;
    var box = anchor.getBoundingClientRect();
    var width = picker.offsetWidth, height = picker.offsetHeight;
    var left = Math.min(Math.max(8, box.left + box.width / 2 - width / 2), window.innerWidth - width - 8);
    var top = box.top - height - 8;
    if (top < 8) top = box.bottom + 8;
    picker.style.left = left + 'px';
    picker.style.top = top + 'px';
    var first = picker.querySelector('button');
    if (first) first.focus({ preventScroll: true });
  }

  function reactionButton(kind, message, onUpdated) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'chat-act-react';
    button.title = 'Réagir';
    button.setAttribute('aria-label', 'Réagir');
    button.setAttribute('aria-haspopup', 'menu');
    var i = document.createElement('i');
    i.className = 'bi bi-emoji-smile';
    i.setAttribute('aria-hidden', 'true');
    button.append(i);
    button.addEventListener('click', function (event) {
      event.stopPropagation();
      openPicker(button, kind, message, onUpdated);
    });
    return button;
  }

  /**
   * Pastilles « 👍 3 · ✅ 12 » sous la bulle. Le professeur voit aussi qui n'a pas compris
   * (les élèves ne reçoivent jamais les noms).
   */
  function reactionChips(kind, message, onUpdated, canReact) {
    var list = message.is_deleted ? [] : (message.reactions || []);
    if (!list.length) return null;
    var box = document.createElement('div');
    box.className = 'chat-reactions';
    list.forEach(function (r) {
      var chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'chat-reaction' + (r.mine ? ' is-mine' : '');
      chip.dataset.emoji = r.emoji;
      chip.setAttribute('aria-pressed', r.mine ? 'true' : 'false');
      var who = r.names && r.names.length ? ' : ' + r.names.join(', ') : '';
      chip.title = r.label + ' (' + r.count + ')' + who;
      chip.setAttribute('aria-label', r.label + ', ' + r.count + (r.mine ? ', dont vous' : ''));
      chip.append(document.createTextNode(r.emoji + ' '));
      var count = document.createElement('span');
      count.textContent = String(r.count);
      chip.append(count);
      if (canReact) {
        chip.addEventListener('click', function (event) {
          event.stopPropagation();
          reactAndRender(kind, message, r.emoji, onUpdated);
        });
      } else {
        chip.disabled = true;
      }
      box.append(chip);
    });
    var lost = list.filter(function (r) { return r.emoji === '❓' && r.names && r.names.length; })[0];
    if (lost) {
      var line = document.createElement('div');
      line.className = 'chat-reaction-who';
      line.textContent = '❓ Pas compris : ' + lost.names.join(', ');
      box.append(line);
    }
    return box;
  }

  /** Barre d'actions trop large pour tenir à côté d'une longue bulle : on la place au-dessus. */
  function keepActionsInside(container, row) {
    var bar = row && row.querySelector('.chat-msg-actions');
    if (!bar) return;
    row.classList.remove('chat-actions-above');
    var box = container.getBoundingClientRect();
    var stack = row.querySelector('.chat-bubble-stack').getBoundingClientRect();
    var mine = row.classList.contains('mine');
    var room = mine ? stack.left - box.left : box.right - stack.right;
    if (room < bar.offsetWidth + 10) row.classList.add('chat-actions-above');
  }

  /** Sur écran tactile, toucher une bulle affiche ses actions. */
  function enableTapActions(container) {
    var check = function (event) {
      var row = event.target.closest && event.target.closest('.chat-bubble-row');
      if (row && container.contains(row)) keepActionsInside(container, row);
    };
    container.addEventListener('mouseover', check);
    container.addEventListener('focusin', check);
    container.addEventListener('click', function (event) {
      if (event.target.closest('a, button, input, audio, .chat-voice, .chat-reactions')) return;
      var row = event.target.closest('.chat-bubble-row');
      container.querySelectorAll('.chat-bubble-row.is-selected').forEach(function (other) {
        if (other !== row) other.classList.remove('is-selected');
      });
      if (row && event.target.closest('.chat-bubble')) row.classList.toggle('is-selected');
    });
  }

  window.EduBacChat = {
    api: api,
    canEdit: canEdit,
    editMessage: editMessage,
    deleteMessage: deleteMessage,
    reportMessage: reportMessage,
    renderMath: renderMath,
    liveUpdates: liveUpdates,
    avatarTone: avatarTone,
    paintAvatars: paintAvatars,
    dayLabel: dayLabel,
    timeLabel: timeLabel,
    listTimeLabel: listTimeLabel,
    receipt: receipt,
    renderText: renderText,
    placeMessage: placeMessage,
    scroller: scroller,
    composer: composer,
    enableTapActions: enableTapActions,
    replyQuote: replyQuote,
    replyExcerpt: replyExcerpt,
    reactionButton: reactionButton,
    reactionChips: reactionChips,
  };
})();
