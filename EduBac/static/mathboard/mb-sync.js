/* Tableau mathématique — synchronisation et enregistrement automatique.
 *
 * - Chaque modification locale devient une opération (op_id unique) placée dans
 *   une file conservée dans localStorage : rien n'est perdu en cas de coupure,
 *   de rechargement ou de fermeture de l'onglet.
 * - Envoi groupé et différé (250 ms), nouvel essai progressif en cas d'échec.
 * - Réception : WebSocket si disponible (reconnexion automatique), sinon
 *   interrogation HTTP ; après chaque reconnexion, rattrapage par ?since=.
 * - Événements : status, op, reset, presence, cursor, rejected, document.
 */
(function (root) {
  'use strict';

  function uid(prefix) {
    var rnd = (root.crypto && root.crypto.randomUUID) ? root.crypto.randomUUID().replace(/-/g, '')
      : (Date.now().toString(36) + Math.random().toString(36).slice(2, 12));
    return (prefix || '') + rnd.slice(0, 20);
  }

  /* Jeton lu à chaque envoi : il change à la connexion. */
  function csrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function Sync(options) {
    this.docId = options.docId;
    this.urls = options.urls;
    this.csrf = options.csrf;
    this.wsPath = options.wsPath;
    this.clientId = uid('c');
    this.revision = options.revision || 0;
    this.handlers = {};
    this.storageKey = 'mathboard:pending:' + this.docId;
    this.queue = this._load();
    this.inflight = null;
    this.retryDelay = 1000;
    this.flushTimer = null;
    this.pollTimer = null;
    this.socket = null;
    this.socketOpen = false;
    this.socketRetry = 1000;
    this.stopped = false;
    this.lastError = '';
  }

  Sync.uid = uid;

  Sync.prototype.on = function (name, fn) { (this.handlers[name] = this.handlers[name] || []).push(fn); return this; };
  Sync.prototype.emit = function (name, data) { (this.handlers[name] || []).forEach(function (fn) { fn(data); }); };

  Sync.prototype._load = function () {
    try { var saved = JSON.parse(localStorage.getItem(this.storageKey) || '[]'); return Array.isArray(saved) ? saved : []; }
    catch (e) { return []; }
  };
  Sync.prototype._save = function () {
    var all = (this.inflight || []).concat(this.queue);
    try {
      if (all.length) localStorage.setItem(this.storageKey, JSON.stringify(all));
      else localStorage.removeItem(this.storageKey);
    } catch (e) { /* stockage plein ou interdit : la file reste en mémoire */ }
  };

  Sync.prototype.pending = function () { return (this.inflight || []).concat(this.queue); };

  Sync.prototype.status = function () {
    var count = this.pending().length;
    var state;
    if (!navigator.onLine) state = 'offline';
    else if (this.lastError) state = 'error';
    else if (count) state = 'saving';
    else state = 'saved';
    this.emit('status', { state: state, pending: count, error: this.lastError, live: this.socketOpen });
  };

  Sync.prototype.start = function () {
    var self = this;
    root.addEventListener('online', function () { self.retryDelay = 1000; self.flush(); self.pull(); self.status(); });
    root.addEventListener('offline', function () { self.status(); });
    document.addEventListener('visibilitychange', function () { if (!document.hidden) self.pull(); });
    this._connect();
    this._schedulePoll();
    if (this.queue.length) this.flush();
    this.status();
  };

  Sync.prototype.stop = function () {
    this.stopped = true;
    clearTimeout(this.pollTimer);
    if (this.socket) this.socket.close();
  };

  /* ---------- envoi ---------- */
  Sync.prototype.submit = function (ops) {
    var self = this;
    (Array.isArray(ops) ? ops : [ops]).forEach(function (op) {
      if (!op.op_id) op.op_id = uid('o');
      self.queue.push(op);
    });
    this._save();
    this.status();
    clearTimeout(this.flushTimer);
    this.flushTimer = setTimeout(function () { self.flush(); }, 250);
  };

  Sync.prototype._request = function (method, url, body) {
    var headers = { 'Accept': 'application/json' };
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; headers['X-CSRFToken'] = csrfToken() || this.csrf; }
    return fetch(url, { method: method, credentials: 'same-origin', headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body) })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok) { var err = new Error(data.detail || ('HTTP ' + response.status)); err.status = response.status; err.data = data; throw err; }
          return data;
        });
      });
  };

  Sync.prototype.flush = function () {
    var self = this;
    if (this.inflight || !this.queue.length || this.stopped) return;
    if (!navigator.onLine) { this.status(); return; }
    this.inflight = this.queue.splice(0, 100);
    this._save();
    this.status();
    this._request('POST', this.urls.ops, { client_id: this.clientId, ops: this.inflight })
      .then(function (data) {
        var rejected = (data.results || []).filter(function (r) { return r.status === 'rejected'; });
        self.inflight = null;
        self.lastError = '';
        self.retryDelay = 1000;
        self._save();
        if (rejected.length) self.emit('rejected', rejected);
        self.pull();
        self.status();
        if (self.queue.length) self.flush();
      })
      .catch(function (error) {
        var batch = self.inflight;
        self.inflight = null;
        var sessionProblem = error.status === 401 || (error.status === 403 && /CSRF|authentification|identification/i.test(error.message));
        if (sessionProblem) {
          // Session expirée ou jeton périmé : on garde TOUT (localStorage) ; renvoyé après reconnexion.
          self.queue = batch.concat(self.queue);
          self._save();
          self.lastError = 'Session expirée : reconnectez-vous, vos modifications sont conservées.';
          setTimeout(function () { self.lastError = ''; self.flush(); }, 15000);
        } else if (error.status === 403 || error.status === 404) {
          // Droits retirés : ces modifications ne seront jamais acceptées.
          self.lastError = error.message || 'Modification non autorisée.';
          self._save();
          self.emit('rejected', batch.map(function (op) { return { op_id: op.op_id, code: 'forbidden', message: self.lastError }; }));
          self.emit('reset', {});
        } else if (error.status === 400) {
          self.lastError = '';
          self._save();
          self.emit('rejected', batch.map(function (op) { return { op_id: op.op_id, code: 'invalid', message: error.message }; }));
          self.emit('reset', {});
        } else {
          // Réseau ou serveur indisponible : on garde tout et on réessaie.
          self.queue = batch.concat(self.queue);
          self._save();
          self.lastError = navigator.onLine ? 'Enregistrement impossible pour le moment.' : '';
          setTimeout(function () { self.lastError = ''; self.flush(); }, self.retryDelay);
          self.retryDelay = Math.min(self.retryDelay * 2, 15000);
        }
        self.status();
      });
  };

  /* ---------- réception ---------- */
  Sync.prototype.pull = function () {
    var self = this;
    if (this.pulling || this.stopped) return this.pulling;
    this.pulling = this._request('GET', this.urls.ops + '?since=' + this.revision)
      .then(function (data) {
        self.pulling = null;
        if ('presentation' in data) self.emit('presentation', data.presentation);
        if (data.settings && data.settings !== self.settingsKey) {
          // Droits ou état du travail changés (copie rendue, corrigée, partage modifié) : rechargement.
          var first = self.settingsKey === undefined;
          self.settingsKey = data.settings;
          if (!first) { self.emit('reset', { revision: data.revision }); return; }
        }
        if (data.reset) { self.emit('reset', { revision: data.revision }); return; }
        self._applyRemote(data.ops || []);
        self.revision = Math.max(self.revision, data.revision || 0);
      })
      .catch(function () { self.pulling = null; });
    return this.pulling;
  };

  Sync.prototype._applyRemote = function (ops) {
    var self = this;
    ops.forEach(function (op) {
      if (op.revision <= self.revision) return;
      if (op.revision !== self.revision + 1) { self.pull(); return; }
      self.revision = op.revision;
      if (op.kind === 'document.restore') { self.emit('reset', { revision: op.revision }); return; }
      if (op.client_id !== self.clientId) self.emit('op', op);
    });
  };

  Sync.prototype.setRevision = function (revision) { this.revision = revision; };

  Sync.prototype._schedulePoll = function () {
    var self = this;
    clearTimeout(this.pollTimer);
    if (this.stopped) return;
    var delay = this.socketOpen ? 20000 : (document.hidden ? 8000 : 2000);
    this.pollTimer = setTimeout(function () { self.pull(); self._schedulePoll(); }, delay);
  };

  /* ---------- WebSocket (facultatif) ---------- */
  Sync.prototype._connect = function () {
    var self = this;
    if (!this.wsPath || !root.WebSocket || this.stopped) return;
    var socket;
    try { socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + this.wsPath); }
    catch (e) { return; }
    this.socket = socket;
    socket.onopen = function () {
      self.socketOpen = true;
      self.socketRetry = 1000;
      socket.send(JSON.stringify({ type: 'hello', client_id: self.clientId, page: self.page || '' }));
      self.pull();
      self._schedulePoll();
      self.status();
    };
    socket.onmessage = function (event) {
      var message;
      try { message = JSON.parse(event.data); } catch (e) { return; }
      if (message.type === 'ops') self._applyRemote(message.ops || []);
      else if (message.type === 'presence') self.emit('presence', message.users || []);
      else if (message.type === 'cursor') { if (message.client_id !== self.clientId) self.emit('cursor', message); }
      else if (message.type === 'document') self.emit('document', message);
      else if (message.type === 'revoked') self.emit('revoked', message);
      else if (message.type === 'presentation') self.emit('presentation', message.presentation);
    };
    socket.onclose = function (event) {
      var wasOpen = self.socketOpen;
      self.socketOpen = false;
      self.socket = null;
      self._schedulePoll();
      self.status();
      if (self.stopped || event.code === 4403 || event.code === 4401) return;
      // Serveur sans WebSocket (WSGI) : l'interrogation HTTP suffit, on réessaie rarement.
      var delay = wasOpen ? self.socketRetry : Math.max(self.socketRetry, 30000);
      setTimeout(function () { self._connect(); }, delay);
      self.socketRetry = Math.min(self.socketRetry * 2, 30000);
    };
  };

  Sync.prototype.send = function (message) {
    if (this.socketOpen && this.socket) { this.socket.send(JSON.stringify(message)); return true; }
    return false;
  };

  Sync.prototype.setPage = function (page) {
    this.page = page;
    this.send({ type: 'page', page: page });
  };

  /* Présence par HTTP quand WebSocket est absent. */
  Sync.prototype.heartbeat = function (cursor) {
    var self = this;
    if (this.socketOpen) return;
    this._request('POST', this.urls.presence, { client_id: this.clientId, page: this.page || '', cursor: cursor || null })
      .then(function (users) { self.emit('presence', users); })
      .catch(function () { /* présence non essentielle */ });
  };

  root.MBSync = Sync;
})(window);
