/* Tableau mathématique — éditeur (Fabric.js).
 *
 * Miroir local de l'état (pages → objets), appliqué au canevas de la page
 * affichée. Toute action locale produit des opérations envoyées par MBSync ;
 * les opérations des autres participants arrivent par MBSync et sont
 * appliquées au miroir puis au canevas.
 */
(function (root) {
  'use strict';
  var MB = root.MB = root.MB || {};
  var fabric = root.fabric;
  var R = MB.Render;
  var uid = root.MBSync.uid;

  var COLORS = ['#212529', '#e03131', '#1971c2', '#2f9e44', '#f08c00', '#9c36b5', '#ffffff'];
  var GRID = 40;

  function Board(config) {
    this.config = config;
    this.me = config.me;
    this.access = config.access;
    this.pages = [];
    this.pageUid = null;
    this.tool = 'select';
    this.color = '#212529';
    this.width = 3;
    this.undoStack = [];
    this.redoStack = [];
    this.byId = {};          // id → objet Fabric (page affichée)
    this.creating = {};      // id → promesse de création en cours
    this.views = {};         // page → transformation de vue (locale)
    this.clipboard = null;
    this.busy = false;
  }

  /* =================== Initialisation =================== */
  Board.prototype.init = function () {
    var self = this;
    var host = document.getElementById('mbCanvasHost');
    var el = document.getElementById('mbCanvas');
    this.canvas = new fabric.Canvas(el, { preserveObjectStacking: true, selection: true, stopContextMenu: true,
      fireMiddleClick: true, backgroundColor: '#ffffff' });
    this.canvas.freeDrawingBrush = new fabric.PencilBrush(this.canvas);
    this._fit(host);
    new ResizeObserver(function () { self._fit(host); }).observe(host);
    this._patchBackground();
    this._bindCanvas();
    this._bindKeys();

    this.sync = new root.MBSync({ docId: this.config.id, urls: this.config.urls, csrf: this.config.csrf,
      wsPath: this.config.wsPath });
    this.sync.on('status', function (s) { self.ui.status(s); });
    this.sync.on('op', function (op) { self.applyRemote(op); });
    this.sync.on('reset', function () { self.reload(); });
    this.sync.on('rejected', function (list) { self.ui.toast(list[0].message || 'Modification refusée.', 'error'); self.reload(); });
    this.sync.on('presence', function (users) { self.ui.presence(users); });
    this.sync.on('cursor', function (c) { self.ui.cursor(c, self); });
    this.sync.on('document', function (m) { self.onDocument(m); });
    this.sync.on('revoked', function () { self.ui.toast('Votre accès à ce document a été retiré.', 'error'); setTimeout(function () { location.href = self.config.urls.list; }, 1500); });
    return this.reload().then(function () {
      self.sync.start();
      setInterval(function () { self.sync.heartbeat(self.lastCursor); }, 5000);
      self.sync.heartbeat();
    });
  };

  Board.prototype._fit = function (host) {
    this.canvas.setDimensions({ width: host.clientWidth, height: host.clientHeight });
    this.canvas.requestRenderAll();
  };

  Board.prototype.canEdit = function () { return this.access === 'edit' || this.access === 'manage'; };
  Board.prototype.canManage = function () { return this.access === 'manage'; };
  Board.prototype.owns = function (model) {
    return this.canManage() || (this.canEdit() && (!model || model._by === undefined || model._by === this.me));
  };

  /* =================== État complet =================== */
  /* Copie locale de l'état (par utilisateur) : le tableau s'ouvre même sans réseau. */
  Board.prototype._cacheKey = function () { return 'mathboard:state:' + this.config.id + ':' + this.me; };
  Board.prototype.saveLocal = function () {
    var self = this;
    clearTimeout(this._saveLocalTimer);
    this._saveLocalTimer = setTimeout(function () {
      try {
        var text = JSON.stringify({ revision: self.sync.revision, access: self.access, document: self.documentInfo,
          pages: self.pages, saved: Date.now() });
        if (text.length > 4000000) { localStorage.removeItem(self._cacheKey()); return; }
        localStorage.setItem(self._cacheKey(), text);
      } catch (e) { /* stockage plein ou interdit : pas de copie locale */ }
    }, 1500);
  };
  Board.prototype._fetchState = function () {
    var self = this;
    // Copies laissées par un autre compte sur cet appareil : effacées.
    try {
      Object.keys(localStorage).forEach(function (key) {
        if (key.indexOf('mathboard:state:') === 0 && key.split(':')[3] !== String(self.me)) localStorage.removeItem(key);
      });
    } catch (e) { /* stockage indisponible */ }
    return fetch(this.config.urls.state, { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(function (r) {
        if (!r.ok) { var err = new Error('Chargement impossible'); err.status = r.status; throw err; }
        return r.json();
      })
      .catch(function (error) {
        var cached = null;
        if (!error.status) {  // réseau coupé (pas une réponse du serveur)
          try { cached = JSON.parse(localStorage.getItem(self._cacheKey()) || 'null'); } catch (e) { cached = null; }
        }
        if (!cached) throw error;
        self.offlineCopy = true;
        self.ui.toast('Hors ligne : dernière version enregistrée sur cet appareil. Vos modifications seront envoyées au retour du réseau.');
        return cached;
      });
  };

  Board.prototype.reload = function () {
    var self = this;
    return this._fetchState()
      .then(function (state) {
        self.access = state.access;
        self.documentInfo = state.document;
        self.pages = state.pages.map(function (p) { return { uid: p.uid, title: p.title, background: p.background, objects: p.objects }; });
        // Les modifications locales encore en attente sont rejouées sur l'état reçu.
        self.sync.setRevision(state.revision);
        self.sync.pending().forEach(function (op) { self._applyToMirror(op); });
        var keep = self.pages.some(function (p) { return p.uid === self.pageUid; });
        self.ui.document(state.document, state.access);
        self.saveLocal();
        return self.showPage(keep ? self.pageUid : self.pages[0].uid);
      })
      .catch(function (error) { self.ui.toast(error.message, 'error'); });
  };

  Board.prototype.page = function (uidValue) {
    uidValue = uidValue || this.pageUid;
    for (var i = 0; i < this.pages.length; i++) if (this.pages[i].uid === uidValue) return this.pages[i];
    return null;
  };

  Board.prototype.showPage = function (pageUid) {
    var self = this;
    if (this.pageUid) this.views[this.pageUid] = this.canvas.viewportTransform.slice();
    this.pageUid = pageUid;
    this.canvas.discardActiveObject();
    this.canvas.clear();
    this.canvas.backgroundColor = '#ffffff';
    this.byId = {};
    this.creating = {};
    this.canvas.setViewportTransform(this.views[pageUid] || [1, 0, 0, 1, 0, 0]);
    this.sync.setPage && this.sync.setPage(pageUid);
    var page = this.page();
    var models = Object.keys(page.objects).map(function (id) { return page.objects[id]; });
    this.ui.pages(this.pages, pageUid, this);
    return Promise.all(models.map(function (m) { return self._create(m); })).then(function () {
      self._sortZ();
      self.ui.zoom(self.canvas.getZoom());
      self.canvas.requestRenderAll();
    });
  };

  /* =================== Miroir et canevas =================== */
  Board.prototype._applyToMirror = function (op) {
    var page;
    switch (op.kind) {
      case 'object.add':
        page = this.page(op.page); if (page) page.objects[op.object.id] = op.object; break;
      case 'object.update':
        page = this.page(op.page);
        if (page && page.objects[op.id]) page.objects[op.id] = Object.assign({}, page.objects[op.id], op.props);
        break;
      case 'object.delete':
        page = this.page(op.page); if (page) delete page.objects[op.id]; break;
      case 'page.add':
        if (!this.page(op.page.uid)) {
          var index = typeof op.index === 'number' ? op.index : this.pages.length;
          this.pages.splice(index, 0, { uid: op.page.uid, title: op.page.title || '', background: op.page.background || 'blank', objects: {} });
        }
        break;
      case 'page.update':
        page = this.page(op.page); if (page) Object.assign(page, op.props); break;
      case 'page.move':
        page = this.page(op.page);
        if (page) { this.pages.splice(this.pages.indexOf(page), 1); this.pages.splice(op.index, 0, page); }
        break;
      case 'page.delete':
        page = this.page(op.page); if (page && this.pages.length > 1) this.pages.splice(this.pages.indexOf(page), 1); break;
    }
  };

  Board.prototype._permissions = function (obj) {
    var page = this.page();
    var model = page && page.objects[obj.id];
    var allowed = this.owns(model) && this.tool === 'select';
    obj.set({ selectable: allowed, evented: allowed || this.tool === 'eraser', hoverCursor: allowed ? 'move' : 'default' });
  };

  Board.prototype._create = function (model) {
    var self = this;
    var promise = R.toFabric(model).then(function (obj) {
      delete self.creating[model.id];
      var page = self.page();
      if (!page || !page.objects[model.id] || self.byId[model.id]) return null;  // supprimé entre-temps
      self._permissions(obj);
      self.byId[model.id] = obj;
      self.canvas.add(obj);
      if (obj.mbError) self.ui.toast(obj.mbError, 'error');
      return obj;
    }).catch(function () { delete self.creating[model.id]; return null; });
    this.creating[model.id] = promise;
    return promise;
  };

  Board.prototype._applyToCanvas = function (op) {
    var self = this;
    if (op.kind.indexOf('page.') === 0) {
      this.ui.pages(this.pages, this.pageUid, this);
      if (op.kind === 'page.delete' && op.page === this.pageUid) return this.showPage(this.pages[0].uid);
      if (op.kind === 'page.update' && op.page === this.pageUid) this.canvas.requestRenderAll();
      return Promise.resolve();
    }
    if (op.page !== this.pageUid) return Promise.resolve();
    var id = op.kind === 'object.add' ? op.object.id : op.id;
    var pendingCreate = this.creating[id] || Promise.resolve();
    return pendingCreate.then(function () {
      var obj = self.byId[id];
      var page = self.page();
      if (op.kind === 'object.add') {
        if (!obj) return self._create(page.objects[id]).then(function () { self._sortZ(); });
      } else if (op.kind === 'object.delete') {
        if (obj) { self.canvas.remove(obj); delete self.byId[id]; }
      } else if (op.kind === 'object.update' && obj) {
        var model = page.objects[id];
        var contentChanged = R.SPECIAL[model.type] && Object.keys(op.props).some(function (k) {
          return ['left', 'top', 'scaleX', 'scaleY', 'angle', 'flipX', 'flipY', 'opacity', 'z'].indexOf(k) < 0;
        });
        if (contentChanged || model.type === 'path' && op.props.path || model.type === 'image' && op.props.src) {
          var wasActive = self.canvas.getActiveObject() === obj;
          return R.toFabric(model).then(function (fresh) {
            if (self.byId[id] !== obj) return;
            self.canvas.remove(obj);
            self._permissions(fresh);
            self.byId[id] = fresh;
            self.canvas.add(fresh);
            self._sortZ();
            if (wasActive) self.canvas.setActiveObject(fresh);
            self.canvas.requestRenderAll();
          });
        }
        var props = Object.assign({}, op.props);
        delete props.type; delete props.id;
        obj.set(props);
        obj.setCoords();
        if ('z' in props) self._sortZ();
      }
      self.canvas.requestRenderAll();
    });
  };

  Board.prototype._sortZ = function () {
    var self = this;
    var objects = this.canvas.getObjects().slice().sort(function (a, b) {
      return ((a.z || 0) - (b.z || 0)) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
    });
    objects.forEach(function (obj, index) { self.canvas.moveObjectTo(obj, index); });
  };

  Board.prototype.applyRemote = function (op) {
    this._applyToMirror(op);
    this._applyToCanvas(op);
    this.saveLocal();
  };

  /* =================== Actions locales =================== */
  /* commit : le canevas montre déjà le changement ; on l'enregistre (miroir + envoi + historique). */
  Board.prototype.commit = function (ops, inverse) {
    var self = this;
    if (!ops.length) return;
    ops.forEach(function (op) {
      op.page = op.page || self.pageUid;
      if (op.kind === 'object.add') op.object._by = self.me;
      self._applyToMirror(op);
      if (op.kind === 'object.add') delete op.object._by;
    });
    this.sync.submit(ops.map(function (op) { return Object.assign({}, op, { op_id: uid('o') }); }));
    this.saveLocal();
    if (inverse) {
      this.undoStack.push({ undo: inverse, redo: ops.map(clone), page: this.pageUid });
      if (this.undoStack.length > 100) this.undoStack.shift();
      this.redoStack = [];
    }
    this.ui.history(this);
  };

  /* perform : changement décidé par le programme (annuler, coller, insérer) : miroir + canevas + envoi. */
  Board.prototype.perform = function (ops, inverse) {
    var self = this;
    ops.forEach(function (op) { op.page = op.page || self.pageUid; });
    this.commit(ops, inverse);
    return Promise.all(ops.map(function (op) { return self._applyToCanvas(op); }));
  };

  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  Board.prototype.nextZ = function () {
    var page = this.page(), max = 0;
    Object.keys(page.objects).forEach(function (id) { max = Math.max(max, page.objects[id].z || 0); });
    return max + 1;
  };

  Board.prototype.addModel = function (model, select) {
    var self = this;
    model.id = model.id || uid('m');
    model.z = model.z || this.nextZ();
    return this.perform([{ kind: 'object.add', object: model }], [{ kind: 'object.delete', id: model.id }]).then(function () {
      var obj = self.byId[model.id];
      if (obj && select) { self.setTool('select'); self.canvas.setActiveObject(obj); self.canvas.requestRenderAll(); }
      return obj;
    });
  };

  Board.prototype.updateModel = function (id, props) {
    var page = this.page(), prev = page.objects[id];
    if (!prev) return Promise.resolve();
    var before = {};
    Object.keys(props).forEach(function (k) { before[k] = prev[k] === undefined ? null : prev[k]; });
    return this.perform([{ kind: 'object.update', id: id, props: props }], [{ kind: 'object.update', id: id, props: before }]);
  };

  /* Objet modifié sur le canevas (déplacé, redimensionné, texte édité…). */
  Board.prototype._modified = function (objects) {
    var page = this.page(), ops = [], inverse = [];
    objects.forEach(function (obj) {
      if (!obj.id || !page.objects[obj.id]) return;
      var prev = page.objects[obj.id], next = R.fromFabric(obj), props = {}, before = {};
      Object.keys(next).forEach(function (k) {
        if (k === 'id' || k === 'type' || k.charAt(0) === '_') return;
        if (JSON.stringify(next[k]) !== JSON.stringify(prev[k])) { props[k] = next[k]; before[k] = prev[k] === undefined ? null : prev[k]; }
      });
      if (Object.keys(props).length) {
        ops.push({ kind: 'object.update', id: obj.id, props: props, base_rev: prev._rev });
        inverse.push({ kind: 'object.update', id: obj.id, props: before });
      }
    });
    this.commit(ops, inverse);
  };

  Board.prototype.selected = function () {
    var active = this.canvas.getActiveObject();
    if (!active) return [];
    return active.type === 'activeselection' || active.type === 'ActiveSelection' ? active.getObjects().slice() : [active];
  };

  /* Exécute fn avec les objets sélectionnés en coordonnées absolues, puis resélectionne. */
  Board.prototype._withSelection = function (fn) {
    var objects = this.selected();
    if (!objects.length) return;
    this.canvas.discardActiveObject();
    var result = fn(objects);
    var alive = objects.filter(function (o) { return o.canvas; });
    if (alive.length > 1) this.canvas.setActiveObject(new fabric.ActiveSelection(alive, { canvas: this.canvas }));
    else if (alive.length === 1) this.canvas.setActiveObject(alive[0]);
    this.canvas.requestRenderAll();
    return result;
  };

  Board.prototype.deleteSelected = function () {
    var self = this, page = this.page();
    var objects = this.selected().filter(function (o) { return o.id && page.objects[o.id] && self.owns(page.objects[o.id]); });
    if (!objects.length) return;
    this.canvas.discardActiveObject();
    var ops = [], inverse = [];
    objects.forEach(function (obj) {
      inverse.push({ kind: 'object.add', object: clone(page.objects[obj.id]) });
      ops.push({ kind: 'object.delete', id: obj.id });
      self.canvas.remove(obj);
      delete self.byId[obj.id];
    });
    this.commit(ops, inverse);
    this.canvas.requestRenderAll();
  };

  Board.prototype.copy = function (cut) {
    var self = this, page = this.page();
    var objects = this.selected();
    if (!objects.length) return;
    this._withSelection(function (list) {
      self.clipboard = list.filter(function (o) { return page.objects[o.id]; }).map(function (o) {
        var m = R.fromFabric(o); delete m._by; delete m._rev; return m;
      });
    });
    try { localStorage.setItem('mathboard:clipboard', JSON.stringify(this.clipboard)); } catch (e) { /* facultatif */ }
    if (cut) this.deleteSelected();
    this.ui.toast(this.clipboard.length + ' élément(s) copié(s).');
  };

  Board.prototype.paste = function (offset) {
    var self = this, models = this.clipboard;
    if (!models) { try { models = JSON.parse(localStorage.getItem('mathboard:clipboard') || 'null'); } catch (e) { models = null; } }
    if (!models || !models.length || !this.canEdit()) return;
    var shift = offset === undefined ? 24 : offset, z = this.nextZ();
    var fresh = models.map(function (m, i) {
      var copy = clone(m);
      copy.id = uid('m'); copy.z = z + i;
      copy.left = (copy.left || 0) + shift; copy.top = (copy.top || 0) + shift;
      return copy;
    });
    this.clipboard = fresh;
    this.perform(fresh.map(function (m) { return { kind: 'object.add', object: m }; }),
      fresh.map(function (m) { return { kind: 'object.delete', id: m.id }; })).then(function () {
      var objs = fresh.map(function (m) { return self.byId[m.id]; }).filter(Boolean);
      self.setTool('select');
      if (objs.length > 1) self.canvas.setActiveObject(new fabric.ActiveSelection(objs, { canvas: self.canvas }));
      else if (objs.length) self.canvas.setActiveObject(objs[0]);
      self.canvas.requestRenderAll();
    });
  };

  Board.prototype.duplicate = function () { this.copy(false); this.paste(); };

  /* Calques : ordre d'affichage par la propriété z. */
  Board.prototype.arrange = function (where) {
    var self = this, page = this.page();
    var ids = Object.keys(page.objects).sort(function (a, b) { return (page.objects[a].z || 0) - (page.objects[b].z || 0) || (a < b ? -1 : 1); });
    var selected = this.selected().map(function (o) { return o.id; }).filter(function (id) { return page.objects[id] && self.owns(page.objects[id]); });
    if (!selected.length) return;
    var rest = ids.filter(function (id) { return selected.indexOf(id) < 0; });
    var order;
    if (where === 'front') order = rest.concat(selected);
    else if (where === 'back') order = selected.concat(rest);
    else {
      order = ids.slice();
      var list = where === 'forward' ? selected.slice().reverse() : selected;
      list.forEach(function (id) {
        var i = order.indexOf(id), j = where === 'forward' ? i + 1 : i - 1;
        if (j < 0 || j >= order.length || selected.indexOf(order[j]) >= 0) return;
        order[i] = order[j]; order[j] = id;
      });
    }
    var ops = [], inverse = [];
    order.forEach(function (id, index) {
      var z = index + 1;
      if (page.objects[id].z !== z && self.owns(page.objects[id])) {
        ops.push({ kind: 'object.update', id: id, props: { z: z } });
        inverse.push({ kind: 'object.update', id: id, props: { z: page.objects[id].z || 0 } });
        if (self.byId[id]) self.byId[id].z = z;
      }
    });
    this.commit(ops, inverse);
    this._sortZ();
    this.canvas.requestRenderAll();
  };

  Board.prototype.undo = function () { this._replay(this.undoStack, this.redoStack, 'undo'); };
  Board.prototype.redo = function () { this._replay(this.redoStack, this.undoStack, 'redo'); };
  Board.prototype._replay = function (from, to, which) {
    var entry = from.pop();
    if (!entry) return;
    if (entry.page !== this.pageUid) { from.push(entry); this.ui.toast('Cette action concerne une autre page.'); return; }
    this.canvas.discardActiveObject();
    var ops = (which === 'undo' ? entry.undo : entry.redo).map(clone);
    var self = this;
    ops.forEach(function (op) { op.page = entry.page; });
    ops.forEach(function (op) { op.page = op.page || self.pageUid; if (op.kind === 'object.add') op.object._by = self.me; self._applyToMirror(op); if (op.kind === 'object.add') delete op.object._by; });
    this.sync.submit(ops.map(function (op) { return Object.assign({}, op, { op_id: uid('o') }); }));
    to.push(entry);
    ops.forEach(function (op) { self._applyToCanvas(op); });
    this.ui.history(this);
  };

  /* =================== Pages =================== */
  Board.prototype.addPage = function (background) {
    var pageUid = uid('p');
    var index = this.pages.indexOf(this.page()) + 1;
    var op = { kind: 'page.add', page: { uid: pageUid, title: '', background: background || 'grid' }, index: index };
    this._applyToMirror(op);
    this.sync.submit([op]);
    return this.showPage(pageUid);
  };
  Board.prototype.pageOp = function (op) {
    op.page = op.page || this.pageUid;
    this._applyToMirror(op);
    this.sync.submit([op]);
    return this._applyToCanvas(op);
  };

  /* =================== Outils =================== */
  Board.prototype.setTool = function (tool) {
    var self = this;
    if (!this.canEdit() && tool !== 'hand' && tool !== 'select') tool = 'select';
    this.tool = tool;
    this.canvas.isDrawingMode = tool === 'pen';
    this.canvas.selection = tool === 'select' && this.canEdit();
    if (tool === 'pen') {
      this.canvas.freeDrawingBrush.color = this.color;
      this.canvas.freeDrawingBrush.width = this.width;
    }
    this.canvas.defaultCursor = tool === 'hand' ? 'grab' : tool === 'select' ? 'default' : 'crosshair';
    if (tool !== 'select') this.canvas.discardActiveObject();
    this.canvas.getObjects().forEach(function (o) { self._permissions(o); });
    this.canvas.requestRenderAll();
    this.ui.tool(tool);
  };

  Board.prototype.setColor = function (color) {
    var self = this;
    this.color = color;
    this.canvas.freeDrawingBrush.color = color;
    var page = this.page();
    var objects = this.selected().filter(function (o) { return page.objects[o.id] && self.owns(page.objects[o.id]); });
    objects.forEach(function (o) {
      if (o.mb && o.mb.type === 'math') { self.updateModel(o.id, { color: color }); return; }
      if (o.mb) return;
      if (o.type === 'i-text' || o.type === 'IText' || o.type === 'textbox' || o.type === 'Textbox') o.set('fill', color);
      else o.set('stroke', color);
    });
    var plain = objects.filter(function (o) { return !o.mb; });
    if (plain.length) this._withSelection(function () { self._modified(plain); });
  };

  Board.prototype.setWidth = function (width) {
    this.width = width;
    this.canvas.freeDrawingBrush.width = width;
  };

  function arrowPath(x1, y1, x2, y2) {
    var angle = Math.atan2(y2 - y1, x2 - x1), head = 14;
    var a1 = angle + Math.PI - 0.45, a2 = angle + Math.PI + 0.45;
    return 'M ' + x1 + ' ' + y1 + ' L ' + x2 + ' ' + y2 + ' M ' + (x2 + head * Math.cos(a1)) + ' ' + (y2 + head * Math.sin(a1)) +
      ' L ' + x2 + ' ' + y2 + ' L ' + (x2 + head * Math.cos(a2)) + ' ' + (y2 + head * Math.sin(a2));
  }

  /* Contour d'un trait de stylet dont l'épaisseur suit la pression (null si
   * la pression ne varie pas : souris, doigt, stylet sans capteur). */
  function pressureShape(points, color, width) {
    if (!points || points.length < 3) return null;
    var pressures = points.map(function (p) { return p.p; });
    var min = Math.min.apply(null, pressures), max = Math.max.apply(null, pressures);
    if (!(max > 0) || max - min < 0.05) return null;
    var pts = [points[0]];
    points.forEach(function (p) {
      var last = pts[pts.length - 1];
      if (Math.hypot(p.x - last.x, p.y - last.y) >= 1.5) pts.push(p);
    });
    if (pts.length < 3) return null;
    var half = pts.map(function (p, i) {
      var a = pts[Math.max(0, i - 1)].p, b = p.p, c = pts[Math.min(pts.length - 1, i + 1)].p;
      return width * (0.2 + 1.1 * (a + 2 * b + c) / 4) / 2;  // pression lissée
    });
    var left = [], right = [];
    pts.forEach(function (p, i) {
      var prev = pts[Math.max(0, i - 1)], next = pts[Math.min(pts.length - 1, i + 1)];
      var dx = next.x - prev.x, dy = next.y - prev.y, len = Math.hypot(dx, dy) || 1;
      var nx = -dy / len * half[i], ny = dx / len * half[i];
      left.push([p.x + nx, p.y + ny]);
      right.push([p.x - nx, p.y - ny]);
    });
    function f(v) { return Math.round(v * 100) / 100; }
    var d = 'M ' + f(left[0][0]) + ' ' + f(left[0][1]);
    left.slice(1).forEach(function (q) { d += ' L ' + f(q[0]) + ' ' + f(q[1]); });
    // Extrémités arrondies : point de contrôle placé dans le prolongement du trait.
    function cap(tip, from, r) {
      var dx = tip.x - from.x, dy = tip.y - from.y, len = Math.hypot(dx, dy) || 1;
      return f(tip.x + dx / len * r * 1.3) + ' ' + f(tip.y + dy / len * r * 1.3);
    }
    var n = pts.length - 1;
    d += ' Q ' + cap(pts[n], pts[n - 1], half[n]) + ' ' + f(right[n][0]) + ' ' + f(right[n][1]);
    right.reverse().slice(1).forEach(function (q) { d += ' L ' + f(q[0]) + ' ' + f(q[1]); });
    d += ' Q ' + cap(pts[0], pts[1], half[0]) + ' ' + f(left[0][0]) + ' ' + f(left[0][1]) + ' Z';
    return d;
  }
  MB.pressureShape = pressureShape;

  /* Texte arabe : écrit de droite à gauche (première lettre forte arabe). */
  var ARABIC_FIRST = /^[^A-Za-z\u00C0-\u024F\u0590-\u08FF]*[\u0590-\u08FF]/;
  function textDirection(text) {
    if (!text || typeof text.text !== 'string') return;
    var rtl = ARABIC_FIRST.test(text.text);
    if (rtl && text.direction !== 'rtl') text.set({ direction: 'rtl', textAlign: 'right' });
    else if (!rtl && text.direction === 'rtl') text.set({ direction: 'ltr', textAlign: 'left' });
    if (text.canvas) text.canvas.requestRenderAll();
  }
  MB.textDirection = textDirection;

  // Coordonnées écran d'un événement souris ou tactile (un TouchEvent n'a pas de clientX).
  function clientPoint(e) {
    var t = (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]) || e;
    return { x: t.clientX, y: t.clientY };
  }

  Board.prototype._bindCanvas = function () {
    var self = this, canvas = this.canvas;
    var drawing = null, panning = null, erasing = null;

    canvas.on('path:created', function (e) {
      var path = e.path;
      if (self._discardStroke) { self._discardStroke = false; self._penStroke = null; canvas.remove(path); return; }
      // Stylet sensible à la pression : le trait devient une forme d'épaisseur variable.
      var shaped = pressureShape(self._penStroke, path.stroke, path.strokeWidth);
      self._penStroke = null;
      if (shaped) {
        canvas.remove(path);
        path = new fabric.Path(shaped, { fill: path.stroke, stroke: null, strokeWidth: 0, opacity: path.opacity });
        canvas.add(path);
      }
      path.set({ id: uid('m'), z: self.nextZ() });
      self.byId[path.id] = path;
      self._permissions(path);
      self.commit([{ kind: 'object.add', object: R.fromFabric(path) }], [{ kind: 'object.delete', id: path.id }]);
    });

    canvas.on('mouse:down', function (opt) {
      var e = opt.e, point = canvas.getScenePoint(e);
      self._discardStroke = false;
      if (self.tool === 'hand' || e.button === 1 || self.spaceDown) {
        panning = clientPoint(e);
        canvas.defaultCursor = 'grabbing';
        canvas.selection = false;
        return;
      }
      if (!self.canEdit()) return;
      if (self.tool === 'eraser') { erasing = { ops: [], inverse: [] }; self._erase(opt, erasing); return; }
      if (self.tool === 'text') {
        if (opt.target && (opt.target.type === 'i-text' || opt.target.type === 'IText')) return;
        var text = new fabric.IText('', { left: point.x, top: point.y, fontSize: 24, fill: self.color,
          fontFamily: 'system-ui, sans-serif', id: uid('m'), z: self.nextZ() });
        text.mbNew = true;
        canvas.add(text);
        self.byId[text.id] = text;
        canvas.setActiveObject(text);
        text.enterEditing();
        return;
      }
      if (['rect', 'ellipse', 'line', 'arrow', 'triangle'].indexOf(self.tool) >= 0) {
        var common = { left: point.x, top: point.y, stroke: self.color, strokeWidth: self.width, fill: 'transparent',
          id: uid('m'), z: self.nextZ(), strokeUniform: true };
        var shape;
        if (self.tool === 'rect') shape = new fabric.Rect(Object.assign(common, { width: 1, height: 1 }));
        else if (self.tool === 'ellipse') shape = new fabric.Ellipse(Object.assign(common, { rx: 1, ry: 1 }));
        else if (self.tool === 'triangle') shape = new fabric.Triangle(Object.assign(common, { width: 1, height: 1 }));
        else shape = new fabric.Line([point.x, point.y, point.x, point.y], common);
        shape.set({ selectable: false, evented: false });
        canvas.add(shape);
        drawing = { shape: shape, x: point.x, y: point.y };
      }
    });

    canvas.on('mouse:move', function (opt) {
      var e = opt.e, point = canvas.getScenePoint(e);
      self.lastCursor = { x: Math.round(point.x), y: Math.round(point.y) };
      if (!self._cursorTimer) {
        self._cursorTimer = setTimeout(function () {
          self._cursorTimer = null;
          self.sync.send({ type: 'cursor', x: self.lastCursor.x, y: self.lastCursor.y, page: self.pageUid });
        }, 60);
      }
      if (panning) {
        var now = clientPoint(e);
        canvas.relativePan(new fabric.Point(now.x - panning.x, now.y - panning.y));
        panning = now;
        self.ui.cursorsMoved(self);
        return;
      }
      if (erasing) { self._erase(opt, erasing); return; }
      if (!drawing) return;
      var s = drawing.shape, x0 = drawing.x, y0 = drawing.y;
      if (s.type === 'line' || s.type === 'Line') s.set({ x2: point.x, y2: point.y });
      else if (s.type === 'ellipse' || s.type === 'Ellipse') s.set({ left: Math.min(x0, point.x), top: Math.min(y0, point.y), rx: Math.abs(point.x - x0) / 2, ry: Math.abs(point.y - y0) / 2 });
      else s.set({ left: Math.min(x0, point.x), top: Math.min(y0, point.y), width: Math.abs(point.x - x0), height: Math.abs(point.y - y0) });
      s.setCoords();
      canvas.requestRenderAll();
    });

    canvas.on('mouse:up', function () {
      if (panning) { panning = null; self.setTool(self.tool); return; }
      if (erasing) { self.commit(erasing.ops, erasing.inverse); erasing = null; return; }
      if (!drawing) return;
      var s = drawing.shape, tiny = (s.width * s.scaleX < 3 && s.height * s.scaleY < 3);
      drawing = null;
      if (tiny) { canvas.remove(s); return; }
      if (self.tool === 'arrow') {
        var arrow = new fabric.Path(arrowPath(s.x1, s.y1, s.x2, s.y2), { stroke: s.stroke, strokeWidth: s.strokeWidth,
          fill: '', id: s.id, z: s.z, strokeLineCap: 'round', strokeLineJoin: 'round', strokeUniform: true });
        canvas.remove(s);
        canvas.add(arrow);
        s = arrow;
      }
      self.byId[s.id] = s;
      self._permissions(s);
      self.commit([{ kind: 'object.add', object: R.fromFabric(s) }], [{ kind: 'object.delete', id: s.id }]);
    });

    canvas.on('object:modified', function (e) {
      var target = e.target;
      if (target.type === 'activeselection' || target.type === 'ActiveSelection') self._withSelection(function (objs) { self._modified(objs); });
      else self._modified([target]);
    });

    canvas.on('text:changed', function (e) { textDirection(e.target); });
    canvas.on('text:editing:exited', function (e) {
      var text = e.target;
      textDirection(text);
      if (text.mbNew) {
        text.mbNew = false;
        if (!text.text.trim()) { canvas.remove(text); delete self.byId[text.id]; return; }
        self._permissions(text);
        self.commit([{ kind: 'object.add', object: R.fromFabric(text) }], [{ kind: 'object.delete', id: text.id }]);
      } else {
        if (!text.text.trim()) { canvas.setActiveObject(text); self.deleteSelected(); return; }
        self._modified([text]);
      }
    });

    canvas.on('mouse:dblclick', function (opt) {
      var target = opt.target;
      if (!target || !target.mb || !self.canEdit()) return;
      var model = self.page().objects[target.id];
      if (!model || !self.owns(model)) return;
      if (model.type === 'math') MB.Panels.openMath(self, model);
      else if (model.type === 'geometry') MB.Panels.openGeometry(self, model);
    });

    canvas.on('mouse:wheel', function (opt) {
      var e = opt.e;
      e.preventDefault(); e.stopPropagation();
      if (e.ctrlKey || e.metaKey || !e.deltaX && Math.abs(e.deltaY) > 40 && !e.shiftKey) {
        var zoom = Math.min(8, Math.max(0.1, canvas.getZoom() * Math.pow(0.999, e.deltaY)));
        canvas.zoomToPoint(new fabric.Point(e.offsetX, e.offsetY), zoom);
        self.ui.zoom(zoom);
      } else {
        canvas.relativePan(new fabric.Point(-(e.shiftKey ? e.deltaY : e.deltaX), e.shiftKey ? 0 : -e.deltaY));
      }
      self.ui.cursorsMoved(self);
    });

    // Pincement à deux doigts (téléphone, tablette) : zoom + déplacement de la vue.
    // Fabric ne gère qu'un seul doigt ; les événements du pincement sont interceptés
    // en phase de capture, et le geste commencé par le premier doigt est annulé.
    var pinch = null;
    function touchInfo(touches) {
      var r = canvas.upperCanvasEl.getBoundingClientRect(), a = touches[0], b = touches[1];
      return { x: (a.clientX + b.clientX) / 2 - r.left, y: (a.clientY + b.clientY) / 2 - r.top,
        d: Math.max(1, Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)) };
    }
    function cancelSingleTouch() {
      if (canvas.isDrawingMode) { self._discardStroke = true; canvas.clearContext(canvas.contextTop); }
      if (drawing) { canvas.remove(drawing.shape); drawing = null; }
      canvas._groupSelector = null;
      var active = canvas.getActiveObject();
      if (active && active.mbNew && active.isEditing) active.exitEditing();
      canvas.requestRenderAll();
    }
    canvas.wrapperEl.addEventListener('touchstart', function (e) {
      if (e.touches.length < 2) return;
      e.preventDefault(); e.stopPropagation();
      if (!pinch) cancelSingleTouch();
      var info = touchInfo(e.touches), v = canvas.viewportTransform;
      pinch = { start: info, zoom: canvas.getZoom(), tx: v[4], ty: v[5] };
    }, { capture: true, passive: false });
    window.addEventListener('touchmove', function (e) {
      if (!pinch) return;
      e.preventDefault(); e.stopImmediatePropagation();
      if (e.touches.length < 2) return;
      var info = touchInfo(e.touches), s = pinch.start;
      var zoom = Math.min(8, Math.max(0.1, pinch.zoom * info.d / s.d));
      var px = (s.x - pinch.tx) / pinch.zoom, py = (s.y - pinch.ty) / pinch.zoom;
      canvas.setViewportTransform([zoom, 0, 0, zoom, info.x - px * zoom, info.y - py * zoom]);
      self.ui.zoom(zoom);
      self.ui.cursorsMoved(self);
    }, { capture: true, passive: false });
    function endPinch(e) {
      if (!pinch) return;
      if (e.touches.length >= 2) {
        var info = touchInfo(e.touches), v = canvas.viewportTransform;
        pinch = { start: info, zoom: canvas.getZoom(), tx: v[4], ty: v[5] };
      }
      // Seul le dernier relâchement atteint Fabric, qui termine proprement son geste.
      if (e.touches.length) { e.stopImmediatePropagation(); return; }
      pinch = null;
    }
    window.addEventListener('touchend', endPinch, { capture: true });
    window.addEventListener('touchcancel', endPinch, { capture: true });

    // Stylet : pression enregistrée point par point ; dès qu'un stylet a servi,
    // le doigt et la paume ne dessinent plus (ils déplacent la vue).
    var wrapper = canvas.wrapperEl;
    function penPoint(e) {
      if (e.pointerType !== 'pen' || !self._penStroke) return;
      var p = canvas.getScenePoint(e);
      self._penStroke.push({ x: p.x, y: p.y, p: e.pressure || 0 });
    }
    wrapper.addEventListener('pointerdown', function (e) {
      if (e.pointerType !== 'pen') return;
      if (!self.penSeen) {
        self.penSeen = true;
        self.ui.toast('Stylet détecté : le stylet écrit, le doigt déplace la vue.');
      }
      self._penStroke = canvas.isDrawingMode ? [] : null;
      penPoint(e);
    }, true);
    wrapper.addEventListener('pointermove', function (e) {
      if (e.getCoalescedEvents) e.getCoalescedEvents().forEach(penPoint); else penPoint(e);
    }, true);
    var fingerPan = null;
    wrapper.addEventListener('touchstart', function (e) {
      var touch = e.touches[0];
      if (!self.penSeen || e.touches.length !== 1 || touch.touchType === 'stylus' || self.tool === 'select' || self.tool === 'hand') return;
      e.preventDefault(); e.stopPropagation();
      fingerPan = { x: touch.clientX, y: touch.clientY };
    }, { capture: true, passive: false });
    window.addEventListener('touchmove', function (e) {
      if (!fingerPan || pinch || e.touches.length !== 1) return;
      e.preventDefault(); e.stopImmediatePropagation();
      var t = e.touches[0];
      canvas.relativePan(new fabric.Point(t.clientX - fingerPan.x, t.clientY - fingerPan.y));
      fingerPan = { x: t.clientX, y: t.clientY };
      self.ui.cursorsMoved(self);
    }, { capture: true, passive: false });
    window.addEventListener('touchend', function (e) {
      if (!fingerPan || e.touches.length) return;
      fingerPan = null;
      e.stopImmediatePropagation();
    }, { capture: true });

    ['selection:created', 'selection:updated', 'selection:cleared'].forEach(function (name) {
      canvas.on(name, function () { self.ui.selection(self.selected(), self); });
    });
  };

  Board.prototype._erase = function (opt, state) {
    var target = this.canvas.findTarget(opt.e);
    var page = this.page();
    if (!target || !target.id || !page.objects[target.id] || !this.owns(page.objects[target.id])) return;
    state.inverse.push({ kind: 'object.add', object: clone(page.objects[target.id]) });
    state.ops.push({ kind: 'object.delete', id: target.id });
    // Retiré du canevas tout de suite ; le miroir et l'envoi sont faits par commit() au relâchement.
    this.canvas.remove(target);
    delete this.byId[target.id];
    this.canvas.requestRenderAll();
  };

  Board.prototype.zoomBy = function (factor) {
    var c = this.canvas, zoom = Math.min(8, Math.max(0.1, c.getZoom() * factor));
    c.zoomToPoint(new fabric.Point(c.width / 2, c.height / 2), zoom);
    this.ui.zoom(zoom);
    this.ui.cursorsMoved(this);
  };

  Board.prototype.zoomFit = function () {
    var objects = this.canvas.getObjects();
    if (!objects.length) { this.canvas.setViewportTransform([1, 0, 0, 1, 0, 0]); this.ui.zoom(1); return; }
    var b = this.bounds();
    var zoom = Math.min(4, Math.max(0.1, Math.min((this.canvas.width - 60) / b.width, (this.canvas.height - 60) / b.height)));
    this.canvas.setViewportTransform([zoom, 0, 0, zoom, (this.canvas.width - b.width * zoom) / 2 - b.left * zoom,
      (this.canvas.height - b.height * zoom) / 2 - b.top * zoom]);
    this.ui.zoom(zoom);
    this.ui.cursorsMoved(this);
  };

  Board.prototype.bounds = function (objects) {
    objects = objects || this.canvas.getObjects();
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    objects.forEach(function (o) {
      var r = o.getBoundingRect ? o.getBoundingRect(true, true) : null;
      if (!r) return;
      // getBoundingRect(true) : coordonnées de scène (sans la vue).
      minX = Math.min(minX, r.left); minY = Math.min(minY, r.top);
      maxX = Math.max(maxX, r.left + r.width); maxY = Math.max(maxY, r.top + r.height);
    });
    if (!isFinite(minX)) return { left: 0, top: 0, width: 800, height: 600 };
    return { left: minX, top: minY, width: Math.max(1, maxX - minX), height: Math.max(1, maxY - minY) };
  };

  /* Centre de la vue en coordonnées de scène (insertion des nouveaux objets). */
  Board.prototype.viewCenter = function () {
    var v = this.canvas.viewportTransform, z = this.canvas.getZoom();
    return { x: (this.canvas.width / 2 - v[4]) / z, y: (this.canvas.height / 2 - v[5]) / z };
  };

  /* Emplacement libre près du centre de la vue pour un nouvel objet (w × h, coordonnées de scène). */
  Board.prototype.freeSpot = function (w, h) {
    var center = this.viewCenter(), rects = this.canvas.getObjects().map(function (o) { return o.getBoundingRect(); });
    var zoom = this.canvas.getZoom(), stepX = Math.max(40, w / 2), stepY = 40;
    var span = { x: this.canvas.width / zoom / 2, y: this.canvas.height / zoom / 2 };
    function free(left, top) {
      return rects.every(function (r) {
        return left + w + 12 < r.left || r.left + r.width + 12 < left || top + h + 12 < r.top || r.top + r.height + 12 < top;
      });
    }
    var startLeft = center.x - w / 2, startTop = center.y - h / 2;
    for (var dy = 0; dy < span.y * 2; dy += stepY) {
      for (var dx = 0; dx < span.x; dx += stepX) {
        var options = [[startLeft + dx, startTop + dy], [startLeft - dx, startTop + dy]];
        for (var i = 0; i < options.length; i++) if (free(options[i][0], options[i][1])) return { left: options[i][0], top: options[i][1] };
      }
    }
    return { left: startLeft + 30, top: startTop + 30 };
  };

  /* =================== Fond de page =================== */
  Board.prototype._patchBackground = function () {
    var self = this, canvas = this.canvas, original = canvas._renderBackground.bind(canvas);
    canvas._renderBackground = function (ctx) {
      original(ctx);
      var page = self.page();
      if (!page || page.background === 'blank') return;
      var v = canvas.viewportTransform, zoom = v[0];
      var step = GRID; while (step * zoom < 14) step *= 5;
      var left = -v[4] / zoom, top = -v[5] / zoom, right = left + canvas.width / zoom, bottom = top + canvas.height / zoom;
      ctx.save();
      ctx.transform(v[0], v[1], v[2], v[3], v[4], v[5]);
      ctx.lineWidth = 1 / zoom;
      var x, y;
      if (page.background === 'dots') {
        ctx.fillStyle = '#c3cad4';
        for (x = Math.floor(left / step) * step; x < right; x += step)
          for (y = Math.floor(top / step) * step; y < bottom; y += step) { ctx.fillRect(x - 1 / zoom, y - 1 / zoom, 2 / zoom, 2 / zoom); }
      } else {
        ctx.strokeStyle = '#e3e8ef';
        ctx.beginPath();
        if (page.background !== 'lines') for (x = Math.floor(left / step) * step; x < right; x += step) { ctx.moveTo(x, top); ctx.lineTo(x, bottom); }
        for (y = Math.floor(top / step) * step; y < bottom; y += step) { ctx.moveTo(left, y); ctx.lineTo(right, y); }
        ctx.stroke();
      }
      if (page.background === 'axes') {
        ctx.strokeStyle = '#495057'; ctx.lineWidth = 1.5 / zoom;
        ctx.beginPath(); ctx.moveTo(left, 0); ctx.lineTo(right, 0); ctx.moveTo(0, top); ctx.lineTo(0, bottom); ctx.stroke();
        ctx.fillStyle = '#495057'; ctx.font = (12 / zoom) + 'px system-ui, sans-serif';
        for (x = Math.floor(left / step) * step; x < right; x += step) if (x) ctx.fillText(String(x / GRID).replace('.', ','), x + 3 / zoom, 14 / zoom);
        for (y = Math.floor(top / step) * step; y < bottom; y += step) if (y) ctx.fillText(String(-y / GRID).replace('.', ','), 4 / zoom, y - 3 / zoom);
      }
      ctx.restore();
    };
  };

  /* =================== Clavier =================== */
  Board.prototype._bindKeys = function () {
    var self = this;
    document.addEventListener('keydown', function (e) {
      var tag = (e.target.tagName || '').toLowerCase();
      var active = self.canvas.getActiveObject();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'math-field' || e.target.isContentEditable) return;
      if (active && active.isEditing) return;
      if (document.querySelector('dialog[open]')) return;
      var mod = e.ctrlKey || e.metaKey, key = e.key.toLowerCase();
      if (key === ' ') { self.spaceDown = true; return; }
      if (mod && key === 'z' && !e.shiftKey) { e.preventDefault(); self.undo(); }
      else if (mod && (key === 'y' || key === 'z' && e.shiftKey)) { e.preventDefault(); self.redo(); }
      else if (mod && key === 'c') { e.preventDefault(); self.copy(false); }
      else if (mod && key === 'x') { e.preventDefault(); self.copy(true); }
      else if (mod && key === 'v') { e.preventDefault(); self.paste(); }
      else if (mod && key === 'd') { e.preventDefault(); self.duplicate(); }
      else if (mod && key === 'a') { e.preventDefault(); self.selectAll(); }
      else if (key === 'delete' || key === 'backspace') { e.preventDefault(); self.deleteSelected(); }
      else if (key === 'escape') { self.canvas.discardActiveObject(); self.canvas.requestRenderAll(); self.setTool('select'); }
      else if (!mod && MB.SHORTCUTS[key]) self.setTool(MB.SHORTCUTS[key]);
    });
    document.addEventListener('keyup', function (e) { if (e.key === ' ') self.spaceDown = false; });
  };

  Board.prototype.selectAll = function () {
    var self = this, page = this.page();
    this.setTool('select');
    var objs = this.canvas.getObjects().filter(function (o) { return page.objects[o.id] && self.owns(page.objects[o.id]); });
    if (objs.length) this.canvas.setActiveObject(new fabric.ActiveSelection(objs, { canvas: this.canvas }));
    this.canvas.requestRenderAll();
  };

  /* =================== Document =================== */
  Board.prototype.onDocument = function (message) {
    var self = this;
    if (message.access) this.access = message.access;
    this.documentInfo = message.document;
    this.ui.document(message.document, this.access);
    this.canvas.getObjects().forEach(function (o) { self._permissions(o); });
    this.setTool(this.tool);
  };

  /* =================== Export =================== */
  Board.prototype.exportImage = function (format) {
    var c = this.canvas, b = this.bounds(), margin = 24;
    var saved = c.viewportTransform.slice(), w = c.width, h = c.height;
    c.discardActiveObject();
    c.setViewportTransform([1, 0, 0, 1, -b.left + margin, -b.top + margin]);
    c.setDimensions({ width: b.width + 2 * margin, height: b.height + 2 * margin });
    var out = format === 'svg' ? c.toSVG() : c.toDataURL({ format: 'png', multiplier: 2 });
    c.setDimensions({ width: w, height: h });
    c.setViewportTransform(saved);
    c.requestRenderAll();
    return out;
  };

  Board.prototype.pageImages = function () {
    var self = this, current = this.pageUid, images = [];
    return this.pages.reduce(function (chain, page) {
      return chain.then(function () { return self.showPage(page.uid); }).then(function () { images.push(self.exportImage('png')); });
    }, Promise.resolve()).then(function () { return self.showPage(current); }).then(function () { return images; });
  };

  MB.SHORTCUTS = { v: 'select', h: 'hand', p: 'pen', e: 'eraser', t: 'text', r: 'rect', o: 'ellipse', l: 'line', a: 'arrow' };
  MB.COLORS = COLORS;
  MB.Board = Board;
})(window);
