/**
 * Tableau collaboratif EduBac.
 *
 * whiteboard.js garde le dessin et les outils ; ce module :
 * - envoie les modifications élément par élément (ajout, modification, suppression) ;
 * - reçoit celles des autres (WebSocket si disponible, sinon interrogation HTTP) ;
 * - conserve les modifications hors ligne et les renvoie à la reconnexion ;
 * - affiche participants, curseurs, permissions, main levée, espaces de travail.
 */
(function () {
  'use strict';
  var app = document.getElementById('wbApp');
  var board = window.EduBacBoard;
  if (!app || !app.dataset.syncUrl || !board || !board._collab) return;

  var C = board._collab;
  var model = window.EduBacObjects;
  var me = Number(app.dataset.currentUser);
  var boardId = app.dataset.boardId;
  var isManager = app.dataset.isManager === '1';
  var csrf = app.dataset.csrf;
  var urls = {
    sync: app.dataset.syncUrl, settings: app.dataset.settingsUrl, control: app.dataset.controlUrl,
    grant: app.dataset.grantUrl, hand: app.dataset.handUrl, zones: app.dataset.zonesUrl,
    share: app.dataset.shareLiveUrl, shareOptions: app.dataset.shareOptionsUrl,
  };
  var clientId = model.id().slice(0, 60);
  var pendingKey = 'edubac-wb-pending-' + boardId;
  var ZONE_WIDTH = 1600;

  var revision = -1;
  var baseline = new Map();
  var baselineBackground = null;
  var remoteQueue = [];
  var inflight = false;
  var flushTimer = null;
  var pollTimer = null;
  var failures = 0;
  var lastActivity = Date.now();
  var cursor = null;
  var cursorChanged = false;
  var lastCursorSent = 0;
  var socket = null;
  var socketOpen = false;
  var state = null;
  var highlightAuthor = null;
  var cursors = new Map();

  var $ = function (id) { return document.getElementById(id); };
  var panel = $('wbPeoplePanel');
  var peopleList = $('wbPeopleList');
  var cursorLayer = $('wbCursorLayer');
  var banner = $('wbControlBanner');
  var toastEl = $('wbToast');

  /* ---------------------------------------------------------------- utils */
  function tone(seed) {
    var text = String(seed || ''), hash = 0;
    for (var i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
    return Math.abs(hash) % 8;
  }
  var TONES = ['#1b7f72', '#3a6db3', '#8456bf', '#bd5f25', '#ad3760', '#2d8a4c', '#8c6f0c', '#4d5d6d'];
  function colorFor(id) { return TONES[tone('u' + id)]; }

  function toast(text) {
    if (!toastEl) return;
    toastEl.textContent = text;
    toastEl.hidden = false;
    toastEl.classList.remove('is-visible');
    void toastEl.offsetWidth;
    toastEl.classList.add('is-visible');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { toastEl.hidden = true; }, 4200);
  }

  function post(url, payload, keepalive) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin', keepalive: !!keepalive,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Accept: 'application/json' },
      body: JSON.stringify(payload || {}),
    }).then(function (response) {
      var type = (response.headers.get('content-type') || '').toLowerCase();
      if (!type.includes('application/json')) throw new Error('Session expirée : rechargez la page.');
      return response.json().then(function (data) {
        if (!response.ok) throw new Error(data.error || 'Action impossible.');
        return data;
      });
    });
  }

  function json(o) { return JSON.stringify(model.serialize(o)); }

  /* ----------------------------------------------------- local ↔ server diff */
  function snapshot() {
    var map = new Map();
    C.objects().forEach(function (o) { if (o.id) map.set(o.id, json(o)); });
    return map;
  }

  function localOps() {
    // Nouveaux éléments : l'auteur est connu tout de suite (le serveur le confirme).
    C.objects().forEach(function (o) { if (o.by == null && o.id && !baseline.has(o.id)) o.by = me; });
    var current = snapshot(), ops = [];
    current.forEach(function (value, id) {
      if (baseline.get(id) !== value) ops.push({ op: baseline.has(id) ? 'update' : 'add', object: JSON.parse(value) });
    });
    baseline.forEach(function (value, id) { if (!current.has(id)) ops.push({ op: 'delete', id: id }); });
    var background = C.background();
    if (baselineBackground !== null && background !== baselineBackground) ops.push({ op: 'background', background: background });
    if (state && state.caps && (state.caps.manage || state.caps.control) && !current.size && baseline.size > 1) {
      ops = [{ op: 'clear' }];
    }
    return { ops: ops, current: current, background: background };
  }

  function resetBaseline(objects, background) {
    baseline = new Map();
    objects.forEach(function (o) { if (o && o.id) baseline.set(o.id, json(o)); });
    baselineBackground = background || C.background();
  }

  /** Applique des opérations à une liste d'objets sérialisés. */
  function applyToList(list, ops) {
    ops.forEach(function (op) {
      if (op.op === 'add' || op.op === 'update') {
        var i = list.findIndex(function (o) { return o.id === op.object.id; });
        if (i === -1) list.push(JSON.parse(JSON.stringify(op.object)));
        else list[i] = JSON.parse(JSON.stringify(op.object));
      } else if (op.op === 'delete') {
        for (var k = list.length - 1; k >= 0; k--) if (list[k].id === op.id) list.splice(k, 1);
      } else if (op.op === 'clear') {
        list.length = 0;
      }
    });
    return list;
  }

  function applyRemote(ops) {
    if (!ops.length) return;
    var objects = C.objects().slice();
    var changed = false;
    ops.forEach(function (op) {
      if (op.revision <= revision) return;
      revision = op.revision;
      if (op.client === clientId) return; // déjà appliqué localement
      changed = true;
      if (op.op === 'add' || op.op === 'update') {
        var i = objects.findIndex(function (o) { return o.id === op.object.id; });
        var copy = JSON.parse(JSON.stringify(op.object));
        if (i === -1) objects.push(copy); else objects[i] = copy;
        baseline.set(copy.id, json(copy));
      } else if (op.op === 'delete') {
        objects = objects.filter(function (o) { return o.id !== op.id; });
        baseline.delete(op.id);
      } else if (op.op === 'clear') {
        objects = [];
        baseline.clear();
      } else if (op.op === 'background') {
        C.background(op.background);
        baselineBackground = op.background;
      }
    });
    if (!changed) return;
    var others = ops.filter(function (op) { return op.client !== clientId; });
    // L'annulation locale ne doit jamais défaire le travail des autres.
    C.remapHistory(function (saved) {
      try { return JSON.stringify(applyToList(JSON.parse(saved), others)); } catch (e) { return saved; }
    });
    C.setObjects(objects);
  }

  function drainRemote() {
    if (!remoteQueue.length || C.busy()) return;
    var ops = remoteQueue;
    remoteQueue = [];
    applyRemote(ops);
  }

  function queueRemote(ops) {
    var last = remoteQueue.length ? remoteQueue[remoteQueue.length - 1].revision : revision;
    ops.forEach(function (op) { if (op.revision > last) { remoteQueue.push(op); last = op.revision; } });
    drainRemote();
  }

  /* ------------------------------------------------------------------ sync */
  function savePending(ops) {
    try {
      if (ops && ops.length) localStorage.setItem(pendingKey, JSON.stringify({ at: Date.now(), ops: ops }));
      else localStorage.removeItem(pendingKey);
    } catch (e) { /* stockage indisponible : on garde la page ouverte */ }
  }

  function restorePending() {
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(pendingKey) || 'null'); } catch (e) { saved = null; }
    if (!saved || !Array.isArray(saved.ops) || Date.now() - saved.at > 86400000) return;
    var objects = applyToList(C.objects().map(model.serialize), saved.ops.filter(function (op) { return op.op !== 'clear'; }));
    saved.ops.forEach(function (op) { if (op.op === 'background') C.background(op.background); });
    C.setObjects(objects);
    toast('Vos modifications non envoyées ont été récupérées.');
  }

  function scheduleFlush(delay) {
    lastActivity = Date.now();
    clearTimeout(flushTimer);
    flushTimer = setTimeout(sync, delay == null ? 150 : delay);
  }

  function nextPollDelay() {
    if (document.hidden) return 15000;
    if (socketOpen) return 10000;
    if (failures) return Math.min(15000, 2000 * failures);
    return Date.now() - lastActivity < 20000 ? 1200 : 3000;
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(sync, nextPollDelay());
  }

  function setConnection(kind) {
    var el = $('wbConnection');
    if (!el) return;
    var labels = {
      live: ['En direct', 'is-live', 'Synchronisation instantanée'],
      sync: ['Synchronisé', 'is-sync', 'Synchronisation automatique toutes les secondes'],
      offline: ['Hors ligne', 'is-offline', 'Vos modifications seront envoyées à la reconnexion'],
      saving: ['Envoi…', 'is-sync', 'Envoi des modifications'],
    }[kind];
    el.textContent = labels[0];
    el.className = 'wb-connection ' + labels[1];
    el.title = labels[2];
  }

  function sync() {
    if (inflight || !C.contentReady() || revision < 0) { schedulePoll(); return; }
    clearTimeout(flushTimer);
    var diff = localOps();
    var payload = { since: revision, client: clientId, ops: diff.ops.slice(0, 200) };
    if (cursorChanged && !socketOpen) { payload.cursor = cursor || false; cursorChanged = false; }
    inflight = true;
    if (payload.ops.length) setConnection('saving');
    post(urls.sync, payload).then(function (data) {
      failures = 0;
      // Accusé de réception : la base de référence suit ce qui a été envoyé.
      payload.ops.forEach(function (op) {
        if (op.op === 'delete') baseline.delete(op.id);
        else if (op.op === 'clear') baseline.clear();
        else if (op.op === 'background') baselineBackground = op.background;
        else baseline.set(op.object.id, JSON.stringify(op.object));
      });
      if (data.rejected && data.rejected.length) handleRejected(data.rejected);
      if (data.reset) {
        var pending = localOps().ops;
        revision = data.revision;
        resetBaseline(data.content.objects, data.content.background);
        C.background(data.content.background);
        var objects = applyToList(data.content.objects.slice(), pending.filter(function (op) { return op.op !== 'clear'; }));
        C.remapHistory(function () { return JSON.stringify(objects); });
        C.setObjects(objects);
      } else {
        queueRemote(data.ops || []);
        if (!remoteQueue.length) revision = Math.max(revision, data.revision);
      }
      savePending(diff.ops.length > payload.ops.length ? localOps().ops : []);
      applyState(data.state);
      setConnection(socketOpen ? 'live' : 'sync');
      if (diff.ops.length > payload.ops.length) scheduleFlush(50);
    }).catch(function (error) {
      failures += 1;
      setConnection('offline');
      savePending(localOps().ops);
      if (failures === 1 && error.message && /Session/.test(error.message)) toast(error.message);
    }).finally(function () {
      inflight = false;
      schedulePoll();
    });
  }

  function handleRejected(rejected) {
    var objects = C.objects().slice();
    rejected.forEach(function (item) {
      if (!item.id) return;
      objects = objects.filter(function (o) { return o.id !== item.id; });
      if (item.object) { objects.push(item.object); baseline.set(item.id, JSON.stringify(item.object)); }
      else baseline.delete(item.id);
    });
    C.setObjects(objects);
    toast(rejected[0].reason || 'Modification refusée.');
  }

  /* ------------------------------------------------------------- websocket */
  function connectSocket() {
    if (!window.WebSocket || !app.dataset.wsPath) return;
    try {
      socket = new WebSocket((location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + location.host + app.dataset.wsPath);
    } catch (e) { return; }
    socket.onopen = function () { socketOpen = true; setConnection('live'); schedulePoll(); };
    socket.onclose = function () {
      var was = socketOpen;
      socketOpen = false;
      if (was) { setConnection('sync'); scheduleFlush(0); }
      setTimeout(connectSocket, was ? 2000 : 15000);
    };
    socket.onmessage = function (event) {
      var data;
      try { data = JSON.parse(event.data); } catch (e) { return; }
      if (data.type === 'cursor') { showCursor(data.user_id, data.name, data.x, data.y); return; }
      if (data.type === 'ops' && data.ops && data.ops.length && data.ops[0].revision === revision + 1) {
        queueRemote(data.ops);
        return;
      }
      if (data.type === 'ops' || data.type === 'revision' || data.type === 'state') scheduleFlush(0);
    };
  }

  /* --------------------------------------------------------------- cursors */
  function boardPoint(event) {
    var canvas = C.canvas, rect = canvas.getBoundingClientRect();
    if (!rect.width) return null;
    return {
      x: Math.round((event.clientX - rect.left) * canvas.width / rect.width),
      y: Math.round((event.clientY - rect.top) * canvas.height / rect.height),
    };
  }

  C.canvas.addEventListener('pointermove', function (event) {
    var point = boardPoint(event);
    if (!point) return;
    cursor = point;
    cursorChanged = true;
    lastActivity = Date.now();
    var now = Date.now();
    if (socketOpen && now - lastCursorSent > 60) {
      lastCursorSent = now;
      socket.send(JSON.stringify({ type: 'cursor', x: point.x, y: point.y }));
    }
  });
  C.canvas.addEventListener('pointerleave', function () { cursor = null; cursorChanged = true; });

  function showCursor(userId, name, x, y) {
    if (!cursorLayer || userId === me) return;
    var entry = cursors.get(userId);
    if (!entry) {
      var el = document.createElement('div');
      el.className = 'wb-cursor';
      el.style.setProperty('--cursor-color', colorFor(userId));
      el.innerHTML = '<svg viewBox="0 0 16 20" aria-hidden="true"><path d="M1 1l13 9-6 1.4L5 18z"/></svg><span></span>';
      cursorLayer.appendChild(el);
      entry = { el: el };
      cursors.set(userId, entry);
    }
    entry.el.querySelector('span').textContent = name;
    entry.el.style.left = (x / C.canvas.width * 100) + '%';
    entry.el.style.top = (y / C.canvas.height * 100) + '%';
    entry.seen = Date.now();
    entry.el.hidden = false;
  }

  setInterval(function () {
    cursors.forEach(function (entry, id) {
      if (Date.now() - entry.seen > 8000) { entry.el.remove(); cursors.delete(id); }
    });
  }, 2000);

  /* ------------------------------------------------- zones and highlights */
  function myZone() {
    return state && state.caps ? state.caps.zone : null;
  }

  C.redraw && board._collab.setHooks({
    changed: function () { scheduleFlush(); },
    flush: function () { scheduleFlush(0); },
    loaded: function (data) {
      revision = typeof data.revision === 'number' ? data.revision : 0;
      resetBaseline(C.objects(), C.background());
      restorePending();
      scheduleFlush(0);
    },
    placeX: function (x) {
      var zone = myZone();
      if (zone == null || !state.zones.length) return x;
      return zone * ZONE_WIDTH / state.zones.length + x;
    },
    decorate: function (ctx, canvas, objects) {
      if (state && state.zones && state.zones.length) {
        var count = state.zones.length, width = ZONE_WIDTH / count, mine = myZone();
        ctx.save();
        for (var i = 0; i < count; i++) {
          var x0 = i * width;
          if (i === mine) { ctx.fillStyle = 'rgba(29, 79, 163,0.06)'; ctx.fillRect(x0, 0, width, canvas.height); }
          if (i > 0) {
            ctx.strokeStyle = 'rgba(29, 79, 163,0.45)'; ctx.lineWidth = 2; ctx.setLineDash([10, 8]);
            ctx.beginPath(); ctx.moveTo(x0, 0); ctx.lineTo(x0, canvas.height); ctx.stroke();
          }
          ctx.setLineDash([]);
          ctx.fillStyle = i === mine ? '#1d4fa3' : 'rgba(34,48,63,0.75)';
          ctx.font = '600 18px system-ui, sans-serif';
          ctx.fillText(state.zones[i].label + (i === mine ? ' · votre espace' : ''), x0 + 14, 28);
        }
        ctx.restore();
      }
      if (highlightAuthor != null) {
        ctx.save();
        ctx.strokeStyle = colorFor(highlightAuthor); ctx.lineWidth = 3; ctx.setLineDash([6, 5]);
        objects.forEach(function (o) {
          if (o.by !== highlightAuthor) return;
          var b = model.bounds(o);
          ctx.strokeRect(b.x - 10, b.y - 10, Math.max(8, b.w) + 20, Math.max(8, b.h) + 20);
        });
        ctx.restore();
      }
    },
  });

  /* ------------------------------------------------------------ UI : état */
  var lastCaps = '', lastPeople = '';
  function applyState(next) {
    if (!next) return;
    var before = state;
    state = next;
    var capsKey = JSON.stringify(next.caps);
    if (capsKey !== lastCaps) { lastCaps = capsKey; C.setCapabilities(next.caps); }
    var participate = next.caps.draw || next.caps.text || next.caps.images || next.caps.manage || next.caps.control;
    ['wbToolbar', 'wbBottombar'].forEach(function (id) { var el = $(id); if (el) el.hidden = !participate; });
    app.classList.toggle('wb-app--can-edit', !!participate);
    renderBanner(next);
    renderStudentStatus(next);
    renderSettings(next.settings);
    // Noms des participants : affichés à côté des réponses d'exercice dans un repère.
    window.EduBacBoardNames = {};
    next.participants.forEach(function (p) { window.EduBacBoardNames[p.id] = p.name; });
    var peopleKey = JSON.stringify([next.participants.map(function (p) {
      return [p.id, p.online, p.hand, p.contributions, p.granted, p.controller, p.zone];
    }), next.zones, highlightAuthor]);
    if (peopleKey !== lastPeople) { lastPeople = peopleKey; renderPeople(next); }
    if (!socketOpen) {
      next.participants.forEach(function (p) {
        if (p.cursor && p.online) showCursor(p.id, p.name, p.cursor.x, p.cursor.y);
      });
    }
    if (before && before.caps && next.caps) {
      if (!before.caps.control && next.caps.control) toast('C’est à vous ! Vous avez la main sur le tableau.');
      else if (before.caps.control && !next.caps.control) toast('L’enseignant a repris la main.');
      else if (!isManager && !(before.caps.draw || before.caps.text) && (next.caps.draw || next.caps.text)) toast('Vous pouvez maintenant participer.');
      else if (!before.caps.locked && next.caps.locked && !isManager) toast('Le tableau est verrouillé.');
    }
    if (before && JSON.stringify(before.zones) !== JSON.stringify(next.zones)) C.redraw();
  }

  function renderBanner(next) {
    if (!banner) return;
    var controller = next.participants.find(function (p) { return p.controller; });
    var text = '';
    if (next.caps.locked && !isManager) text = '🔒 Tableau verrouillé par l’enseignant.';
    else if (next.caps.control) text = '✋ C’est à vous ! Vous avez la main sur le tableau.';
    else if (controller) text = controller.name + ' a la main sur le tableau.';
    banner.hidden = !text;
    banner.querySelector('span').textContent = text;
    var takeBack = banner.querySelector('button');
    if (takeBack) takeBack.hidden = !(isManager && controller);
  }

  function renderStudentStatus(next) {
    var el = $('wbMyStatus');
    if (!el) return;
    var caps = next.caps, parts = [];
    if (caps.locked) el.textContent = 'Lecture seule — tableau verrouillé.';
    else if (caps.control) el.textContent = 'Vous avez la main : tous les outils sont disponibles.';
    else if (caps.draw || caps.text || caps.images) {
      if (caps.draw) parts.push('dessiner');
      if (caps.text) parts.push('écrire');
      if (caps.images) parts.push('ajouter des images');
      el.textContent = 'Vous pouvez ' + parts.join(', ') + '.' +
        (caps.zone != null && next.zones[caps.zone] ? ' Votre espace : ' + next.zones[caps.zone].label + '.' : '');
    } else el.textContent = 'Lecture seule. Levez la main pour demander à participer.';
    var hand = $('wbHandBtn');
    if (hand) {
      var meRow = next.participants.find(function (p) { return p.me; });
      var raised = !!(meRow && meRow.hand);
      hand.hidden = caps.control || caps.locked;
      hand.setAttribute('aria-pressed', String(raised));
      hand.querySelector('span').textContent = raised ? 'Main levée' : 'Lever la main';
    }
  }

  function renderSettings(settings) {
    var form = $('wbPermForm');
    if (!form || !settings) return;
    ['students_can_edit', 'allow_draw', 'allow_text', 'allow_images', 'allow_delete', 'is_locked'].forEach(function (name) {
      var input = form.elements[name];
      if (input && document.activeElement !== input) input.checked = !!settings[name];
    });
    form.classList.toggle('is-participation-off', !settings.students_can_edit);
    var zones = $('wbZoneCount');
    if (zones && document.activeElement !== zones) zones.value = String(state.zones.length);
  }

  function renderPeople(next) {
    if (!peopleList) return;
    var online = next.participants.filter(function (p) { return p.online; }).length;
    var count = $('wbPeopleCount');
    if (count) count.textContent = String(online);
    var hands = next.participants.filter(function (p) { return p.hand; }).length;
    var handBadge = $('wbHandCount');
    if (handBadge) { handBadge.hidden = !hands || !isManager; handBadge.textContent = String(hands); }
    if (panel && panel.contains(document.activeElement) && document.activeElement.tagName === 'SELECT') return;
    peopleList.replaceChildren();
    var sorted = next.participants.slice().sort(function (a, b) {
      return (b.teacher - a.teacher) || (b.hand - a.hand) || (b.online - a.online) || a.name.localeCompare(b.name);
    });
    sorted.forEach(function (p) {
      var row = document.createElement('li');
      row.className = 'wb-person' + (p.online ? ' is-online' : '') + (p.hand ? ' has-hand' : '');
      var avatar = document.createElement('span');
      avatar.className = 'wb-person-avatar';
      avatar.style.background = colorFor(p.id);
      avatar.textContent = (p.name || '?').slice(0, 1).toUpperCase();
      var body = document.createElement('span');
      body.className = 'wb-person-body';
      var name = document.createElement('strong');
      name.textContent = p.name + (p.me ? ' (vous)' : '');
      var meta = document.createElement('small');
      var bits = [p.teacher ? 'Enseignant' : (p.online ? 'En ligne' : 'Hors ligne')];
      if (!p.teacher) bits.push(p.contributions + ' contribution' + (p.contributions > 1 ? 's' : ''));
      if (p.controller) bits.push('a la main');
      else if (p.granted) bits.push('autorisé');
      if (p.zone != null && next.zones[p.zone]) bits.push(next.zones[p.zone].label);
      meta.textContent = bits.join(' · ');
      body.append(name, meta);
      row.append(avatar, body);
      if (p.hand) {
        var hand = document.createElement('span');
        hand.className = 'wb-person-hand';
        hand.title = 'Demande à participer';
        hand.textContent = '✋';
        row.append(hand);
      }
      if (isManager && !p.teacher) row.append(personActions(p, next));
      peopleList.append(row);
    });
  }

  function personActions(p, next) {
    var box = document.createElement('div');
    box.className = 'wb-person-actions';
    function action(label, title, handler, pressed) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.title = title;
      if (pressed != null) b.setAttribute('aria-pressed', String(pressed));
      b.addEventListener('click', handler);
      box.append(b);
      return b;
    }
    action(p.controller ? 'Reprendre' : 'Donner la main',
      p.controller ? 'Reprendre le contrôle du tableau' : 'Inviter ' + p.name + ' à résoudre au tableau',
      function () { run(urls.control, { user_id: p.controller ? null : p.id }); }, p.controller);
    action(p.granted ? 'Retirer' : 'Autoriser',
      p.granted ? 'Retirer l’autorisation d’écrire' : 'Autoriser ' + p.name + ' à écrire et dessiner',
      function () { run(urls.grant, { user_id: p.id, allowed: !p.granted }); }, p.granted);
    action(highlightAuthor === p.id ? 'Masquer' : 'Voir', 'Mettre en évidence les contributions de ' + p.name, function () {
      highlightAuthor = highlightAuthor === p.id ? null : p.id;
      C.redraw();
      lastPeople = '';
      applyState(state);
    }, highlightAuthor === p.id);
    if (next.zones.length) {
      var select = document.createElement('select');
      select.setAttribute('aria-label', 'Espace de travail de ' + p.name);
      var none = document.createElement('option'); none.value = ''; none.textContent = 'Tout le tableau';
      select.append(none);
      next.zones.forEach(function (zone, i) {
        var option = document.createElement('option'); option.value = String(i); option.textContent = zone.label;
        if (p.zone === i) option.selected = true;
        select.append(option);
      });
      select.addEventListener('change', function () { assignZone(p.id, select.value === '' ? null : Number(select.value)); });
      box.append(select);
    }
    return box;
  }

  function run(url, payload) {
    return post(url, payload).then(function (data) { applyState(data.state); return data; })
      .catch(function (error) { toast(error.message); });
  }

  function zonesPayload(count, assign) {
    var zones = [];
    for (var i = 0; i < count; i++) {
      var old = state.zones[i] || {};
      zones.push({ label: old.label || 'Groupe ' + (i + 1), members: (old.members || []).slice() });
    }
    if (assign) {
      zones.forEach(function (z) { z.members = z.members.filter(function (id) { return id !== assign.user; }); });
      if (assign.zone != null && zones[assign.zone]) zones[assign.zone].members.push(assign.user);
    }
    return zones;
  }

  function assignZone(userId, zone) {
    run(urls.zones, { zones: zonesPayload(state.zones.length, { user: userId, zone: zone }) });
  }

  /* ------------------------------------------------- controls (enseignant) */
  var permForm = $('wbPermForm');
  if (permForm) {
    permForm.addEventListener('change', function (event) {
      var input = event.target;
      if (!input.name || input.type !== 'checkbox') return;
      var payload = {};
      payload[input.name] = input.checked;
      run(urls.settings, payload);
    });
  }
  var zoneCount = $('wbZoneCount');
  if (zoneCount) {
    zoneCount.addEventListener('change', function () {
      var count = Number(zoneCount.value);
      var zones = zonesPayload(count);
      if (count > 1) {
        // Répartition initiale : élèves en ligne puis les autres, à tour de rôle.
        var students = state.participants.filter(function (p) { return !p.teacher; })
          .sort(function (a, b) { return (b.online - a.online) || a.name.localeCompare(b.name); });
        zones.forEach(function (z) { z.members = []; });
        students.forEach(function (s, i) { zones[i % count].members.push(s.id); });
      }
      run(urls.zones, { zones: count > 1 ? zones : [] });
    });
  }
  if (banner) {
    var takeBack = banner.querySelector('button');
    if (takeBack) takeBack.addEventListener('click', function () { run(urls.control, { user_id: null }); });
  }

  var handBtn = $('wbHandBtn');
  if (handBtn) {
    handBtn.addEventListener('click', function () {
      var raised = handBtn.getAttribute('aria-pressed') !== 'true';
      run(urls.hand, { raised: raised }).then(function () {
        if (raised) toast('Demande envoyée à l’enseignant.');
      });
    });
  }

  /* ----------------------------------------------------- panel & fullscreen */
  var peopleToggle = $('wbPeopleToggle');
  function setPanel(open) {
    if (!panel) return;
    panel.hidden = !open;
    app.classList.toggle('wb-app--people-open', open);
    if (peopleToggle) peopleToggle.setAttribute('aria-expanded', String(open));
    try { localStorage.setItem('edubac-wb-people', open ? '1' : '0'); } catch (e) {}
    C.redraw();
  }
  if (peopleToggle) peopleToggle.addEventListener('click', function () { setPanel(panel.hidden); });
  var panelClose = $('wbPeopleClose');
  if (panelClose) panelClose.addEventListener('click', function () { setPanel(false); });
  var openByDefault = window.matchMedia && window.matchMedia('(min-width: 1100px)').matches;
  try { var stored = localStorage.getItem('edubac-wb-people'); if (stored) openByDefault = stored === '1' && openByDefault; } catch (e) {}
  setPanel(!!openByDefault);

  var fullscreen = $('wbFullscreen');
  if (fullscreen) {
    fullscreen.addEventListener('click', function () {
      if (document.fullscreenElement) { document.exitFullscreen(); return; }
      if (app.requestFullscreen) app.requestFullscreen().catch(function () { app.classList.toggle('wb-app--fullscreen'); });
      else app.classList.toggle('wb-app--fullscreen');
    });
    document.addEventListener('fullscreenchange', function () {
      var on = document.fullscreenElement === app;
      app.classList.toggle('wb-app--fullscreen', on);
      fullscreen.setAttribute('aria-pressed', String(on));
      fullscreen.querySelector('i').className = on ? 'bi bi-fullscreen-exit' : 'bi bi-arrows-fullscreen';
      setTimeout(C.redraw, 50);
    });
  }

  /* ------------------------------------------------------- partage en direct */
  var shareDialog = $('wbLiveShareDialog');
  var shareOpen = $('wbLiveShare');
  if (shareDialog && shareOpen) {
    var shareForm = shareDialog.querySelector('form');
    var classSelect = $('wbLiveClass');
    var studentBox = $('wbLiveStudents');
    var shareError = $('wbLiveShareError');
    var options = null;

    function renderStudents() {
      var classroom = options.classes.find(function (c) { return String(c.id) === classSelect.value; });
      studentBox.replaceChildren();
      (classroom ? classroom.students : []).forEach(function (s) {
        var label = document.createElement('label');
        var box = document.createElement('input');
        box.type = 'checkbox'; box.value = String(s.id); box.checked = s.selected;
        label.append(box, ' ', s.name);
        studentBox.append(label);
      });
      if (!studentBox.childElementCount) studentBox.textContent = 'Aucun élève dans cette classe.';
    }
    function syncMode() {
      var selected = shareForm.elements.mode.value === 'selected';
      studentBox.hidden = !selected;
      $('wbLivePost').closest('label').hidden = selected;
    }
    shareOpen.addEventListener('click', function () {
      shareError.textContent = '';
      fetch(urls.shareOptions, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          options = data;
          classSelect.replaceChildren();
          data.classes.forEach(function (c) {
            var option = document.createElement('option');
            option.value = String(c.id); option.textContent = c.name + ' (' + c.students.length + ')';
            classSelect.append(option);
          });
          if (data.classroom_id) classSelect.value = String(data.classroom_id);
          shareForm.elements.mode.value = data.mode;
          renderStudents();
          syncMode();
          shareDialog.showModal();
        })
        .catch(function () { toast('Impossible de charger les classes.'); });
    });
    classSelect.addEventListener('change', renderStudents);
    shareForm.addEventListener('change', function (event) { if (event.target.name === 'mode') syncMode(); });
    shareDialog.querySelectorAll('[data-close]').forEach(function (b) { b.addEventListener('click', function () { shareDialog.close(); }); });
    shareForm.addEventListener('submit', function (event) {
      event.preventDefault();
      var ids = Array.from(studentBox.querySelectorAll('input:checked')).map(function (i) { return Number(i.value); });
      post(urls.share, {
        classroom_id: Number(classSelect.value) || null,
        mode: shareForm.elements.mode.value,
        student_ids: ids,
        post_to_chat: $('wbLivePost').checked,
        notify: true,
      }).then(function (data) {
        shareDialog.close();
        applyState(data.state);
        toast('Tableau partagé. Les élèves ont été prévenus.');
      }).catch(function (error) { shareError.textContent = error.message; });
    });
  }

  /* ------------------------------------------------------------- démarrage */
  document.addEventListener('visibilitychange', function () { if (!document.hidden) scheduleFlush(0); });
  setInterval(drainRemote, 300);
  window.addEventListener('online', function () { scheduleFlush(0); });
  window.addEventListener('pagehide', function () {
    var pending = localOps().ops;
    if (!pending.length) return;
    savePending(pending);
    var body = JSON.stringify({ since: revision, client: clientId, ops: pending.slice(0, 200) });
    if (body.length < 60000) post(urls.sync, JSON.parse(body), true).then(function () { savePending([]); }).catch(function () {});
  });
  setConnection('sync');
  connectSocket();
  window.EduBacCollab = {
    syncNow: function () { scheduleFlush(0); },
    state: function () { return state; },
    revision: function () { return revision; },
  };
})();
