/* Tableau mathématique — fonctions de classe :
 *  - mode présentation (« suivez-moi ») : les participants voient la page et la
 *    zone affichées par le professeur ;
 *  - travail à rendre : copie de l'élève, rendu, correction (note, appréciation,
 *    annotations sur la copie), demande de reprise ;
 *  - participation : éléments par auteur, les montrer, les retirer.
 */
(function (root) {
  'use strict';
  var MB = root.MB = root.MB || {};
  var $ = function (id) { return document.getElementById(id); };
  var config = JSON.parse($('mbConfig').textContent);
  var board, api;

  function esc(text) { var d = document.createElement('div'); d.textContent = text == null ? '' : String(text); return d.innerHTML; }
  function date(value) {
    if (!value) return '';
    var d = new Date(value);
    return d.toLocaleDateString('fr-FR') + ' à ' + d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }
  function button(label, onClick, primary) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'mb-btn' + (primary ? ' mb-btn-primary' : ''); b.textContent = label;
    b.addEventListener('click', onClick);
    return b;
  }

  /* ======================= Mode présentation ======================= */
  var Present = {
    active: false,       // ce client présente
    current: null,       // présentation reçue
    following: true,
    lastSent: '',
    timer: null,
    keepAlive: null,

    view: function () {
      var c = board.canvas, v = c.viewportTransform, z = v[0];
      return { page: board.pageUid, cx: (c.width / 2 - v[4]) / z, cy: (c.height / 2 - v[5]) / z, w: c.width / z, h: c.height / z };
    },
    send: function (force) {
      if (!this.active) return;
      var view = this.view();
      var key = [view.page, Math.round(view.cx), Math.round(view.cy), Math.round(view.w), Math.round(view.h)].join('|');
      if (!force && key === this.lastSent) return;
      this.lastSent = key;
      api('POST', config.urls.presentation, view).catch(function (e) { board.ui.toast(e.message, 'error'); });
    },
    viewChanged: function () {
      var self = this;
      if (!this.active) return;
      clearTimeout(this.timer);
      this.timer = setTimeout(function () { self.send(false); }, 250);
    },
    start: function () {
      var self = this;
      this.active = true;
      this.lastSent = '';
      this.send(true);
      // Signal régulier : sans lui, la présentation s'arrête seule (onglet fermé).
      this.keepAlive = setInterval(function () { self.send(true); }, 30000);
      this.render();
    },
    stop: function () {
      this.active = false;
      clearInterval(this.keepAlive);
      clearTimeout(this.timer);
      this.current = null;
      this.render();
      return api('DELETE', config.urls.presentation).catch(function () { /* déjà arrêtée */ });
    },
    receive: function (presentation) {
      var before = this.current;
      this.current = presentation;
      if (presentation && presentation.user === config.me && !this.active && !before && !this.resumed) {
        // Page rechargée pendant sa propre présentation : elle continue.
        this.resumed = true;
        this.start();
        return;
      }
      if (!presentation || presentation.user === config.me) {
        if (!presentation && before && !this.active) this.following = true;
        this.render();
        return;
      }
      if (this.active) { this.active = false; clearInterval(this.keepAlive); }  // un autre a pris la main
      if (!before) this.following = true;
      this.render();
      if (this.following) this.apply();
    },
    apply: function () {
      var p = this.current;
      if (!p || !board.page(p.page)) return;
      var go = p.page !== board.pageUid ? board.showPage(p.page) : Promise.resolve();
      go.then(function () {
        var c = board.canvas, zoom = Math.min(8, Math.max(0.1, Math.min(c.width / p.w, c.height / p.h)));
        c.setViewportTransform([zoom, 0, 0, zoom, c.width / 2 - p.cx * zoom, c.height / 2 - p.cy * zoom]);
        board.ui.zoom(zoom);
        board.ui.cursorsMoved(board);
      });
    },
    render: function () {
      var self = this, banner = $('mbBanner'), text = $('mbBannerText'), actions = $('mbBannerActions');
      var btn = $('mbPresentBtn');
      btn.classList.toggle('is-active', this.active);
      btn.setAttribute('aria-pressed', this.active ? 'true' : 'false');
      btn.querySelector('span').textContent = this.active ? 'Arrêter la présentation' : 'Présenter';
      actions.innerHTML = '';
      if (this.active) {
        text.textContent = 'Vous présentez : les participants voient votre page et votre zone.';
        actions.appendChild(button('Arrêter', function () { self.stop(); }));
      } else if (this.current && this.current.user !== config.me) {
        text.textContent = this.following ? this.current.name + ' présente — vous suivez sa vue.'
          : this.current.name + ' présente.';
        actions.appendChild(this.following
          ? button('Ne plus suivre', function () { self.following = false; self.render(); })
          : button('Suivre', function () { self.following = true; self.render(); self.apply(); }, true));
      }
      banner.hidden = !this.active && !(this.current && this.current.user !== config.me);
      banner.dataset.kind = 'present';
    },
  };

  /* ======================= Travail à rendre ======================= */
  var STATUS = { draft: 'En cours', submitted: 'Rendu', returned: 'Corrigé' };
  var Work = {
    refresh: function () {
      var doc = board.documentInfo || {}, btn = $('mbWorkBtn'), label = $('mbWorkBtnText');
      var banner = $('mbWorkBanner');
      btn.hidden = true;
      banner.hidden = true;
      banner.classList.remove('mb-banner-prepared');
      if (doc.submission_status) {
        // Copie d'un élève.
        var mine = doc.owner === config.me;
        btn.hidden = false;
        if (mine) {
          label.textContent = doc.submission_status === 'draft' ? 'Rendre mon travail' : (doc.submission_status === 'submitted' ? 'Rendu' : 'Voir la correction');
          banner.innerHTML = doc.submission_status === 'draft'
            ? 'Votre copie' + (doc.source_title ? ' de « ' + esc(doc.source_title) + ' »' : '') + ' : écrivez votre réponse, puis cliquez sur « Rendre mon travail ».'
            + (doc.feedback ? ' <strong>À reprendre :</strong> ' + esc(doc.feedback) : '')
            : doc.submission_status === 'submitted' ? 'Travail rendu le ' + esc(date(doc.submitted_at)) + ' — en attente de correction (lecture seule).'
              : 'Travail corrigé' + (doc.grade ? ' — note : <strong>' + esc(doc.grade) + '</strong>' : '') + '. Les annotations du professeur sont sur le tableau.';
        } else {
          label.textContent = doc.submission_status === 'returned' ? 'Correction rendue' : 'Corriger';
          banner.innerHTML = 'Copie de <strong>' + esc(doc.owner_name) + '</strong>' +
            (doc.submitted_at ? ', rendue le ' + esc(date(doc.submitted_at)) : '') +
            (doc.submission_status === 'returned' ? ' — corrigée' + (doc.grade ? ' (' + esc(doc.grade) + ')' : '') : ' — écrivez vos annotations directement sur la copie.');
        }
        if (config.subject) banner.innerHTML += ' <a href="' + esc(config.subject.url) + '">Voir le sujet</a>';
        banner.hidden = false;
        // Pas de partage, de présentation ni de participation sur une copie.
        ['mbShareBtn', 'mbPresentBtn', 'mbPeopleBtn'].forEach(function (id) { $(id).hidden = true; });
      } else if (doc.classroom && doc.class_visible === false && board.canManage()) {
        // Préparé pour la classe : les élèves ne le voient pas encore.
        banner.innerHTML = '<span>Préparé pour la classe <strong>' + esc(doc.classroom_name || '') + '</strong>' +
          (doc.accepts_submissions ? ' (travail à rendre)' : '') + ' — les élèves ne le voient pas encore.</span> ' +
          '<button type="button" class="mb-btn mb-btn-primary" id="mbPublishBtn">Partager maintenant</button>';
        banner.classList.add('mb-banner-prepared');
        banner.hidden = false;
        $('mbPublishBtn').addEventListener('click', function () { Work.publish(this); });
        if (doc.accepts_submissions) { btn.hidden = false; label.textContent = 'Copies des élèves'; }
      } else if (doc.accepts_submissions) {
        btn.hidden = false;
        if (board.canManage()) label.textContent = 'Copies des élèves';
        else label.textContent = config.myCopy ? 'Ouvrir ma copie' : 'Faire ce travail';
        banner.innerHTML = 'Travail à rendre' + (doc.due_at ? ' avant le <strong>' + esc(date(doc.due_at)) + '</strong>' : '') +
          (board.canManage() ? ' — les élèves de la classe en font chacun leur copie.' : ' — cliquez sur « ' + esc(label.textContent) + ' » pour répondre sur votre propre copie.');
        banner.hidden = false;
      }
    },
    publish: function (button) {
      var doc = board.documentInfo || {};
      if (!confirm('Partager « ' + doc.title + ' » avec la classe ' + (doc.classroom_name || '') + ' ? Les élèves seront prévenus.')) return;
      button.disabled = true;
      api('PATCH', config.urls.document, { class_visible: true }).then(function (updated) {
        board.documentInfo = updated;
        board.ui.document(updated, board.access);
        board.ui.toast('Document partagé avec la classe. Les élèves sont prévenus.');
      }).catch(function (e) { button.disabled = false; board.ui.toast(e.message, 'error'); });
    },
    click: function () {
      var doc = board.documentInfo || {};
      if (doc.submission_status) return this.openDialog();
      if (board.canManage()) return this.openCopies();
      if (config.myCopy) { location.href = config.myCopy; return; }
      api('POST', config.urls.copy).then(function (copy) {
        location.href = config.urls.editor.replace('/0/', '/' + copy.id + '/');
      }).catch(function (e) { board.ui.toast(e.message, 'error'); });
    },
    openDialog: function () {
      var doc = board.documentInfo || {}, mine = doc.owner === config.me;
      var state = $('mbWorkState');
      state.innerHTML = '<span class="mb-badge mb-badge-' + esc(doc.submission_status) + '">' + esc(STATUS[doc.submission_status]) + '</span> ' +
        esc(mine ? 'Votre copie' : 'Copie de ' + doc.owner_name) +
        (doc.submitted_at ? ' · rendue le ' + esc(date(doc.submitted_at)) : '') +
        (doc.grade && doc.submission_status === 'returned' ? ' · note : ' + esc(doc.grade) : '');
      $('mbWorkFeedback').hidden = !(mine && doc.feedback);
      $('mbWorkFeedbackText').textContent = doc.feedback || '';
      var correcting = !mine && config.isCorrector && doc.submission_status !== 'draft';
      $('mbWorkCorrect').hidden = !correcting;
      $('mbWorkGrade').value = doc.grade || '';
      $('mbWorkComment').value = doc.feedback || '';
      $('mbWorkSubmit').hidden = !(mine && doc.submission_status === 'draft');
      $('mbWorkReturn').hidden = !correcting;
      $('mbWorkRedo').hidden = !correcting;
      $('mbWorkError').textContent = '';
      $('mbWorkDialog').showModal();
    },
    submit: function () {
      if (board.sync.pending().length) { $('mbWorkError').textContent = 'Enregistrement en cours… réessayez dans un instant.'; board.sync.flush(); return; }
      if (!confirm('Rendre ce travail ? Vous ne pourrez plus le modifier, sauf si le professeur demande une reprise.')) return;
      api('POST', config.urls.submit).then(function () {
        $('mbWorkDialog').close();
        board.ui.toast('Travail rendu. Votre professeur est prévenu.');
        return board.reload();
      }).catch(function (e) { $('mbWorkError').textContent = e.message; });
    },
    correct: function (action) {
      if (board.sync.pending().length) { $('mbWorkError').textContent = 'Vos annotations s’enregistrent… réessayez dans un instant.'; board.sync.flush(); return; }
      api('POST', config.urls.correct, { action: action, grade: $('mbWorkGrade').value, feedback: $('mbWorkComment').value })
        .then(function () {
          $('mbWorkDialog').close();
          board.ui.toast(action === 'redo' ? 'Reprise demandée : l’élève est prévenu.' : 'Correction rendue : l’élève est prévenu.');
          return board.reload();
        }).catch(function (e) { $('mbWorkError').textContent = e.message; });
    },
    openCopies: function () {
      var list = $('mbCopiesList');
      list.innerHTML = '<li>Chargement…</li>';
      $('mbCopiesDialog').showModal();
      api('GET', config.urls.copies).then(function (data) {
        var counts = { none: 0, draft: 0, submitted: 0, returned: 0 };
        data.rows.forEach(function (r) { counts[r.status] = (counts[r.status] || 0) + 1; });
        $('mbCopiesInfo').textContent = counts.submitted + ' à corriger · ' + counts.returned + ' corrigé(s) · ' +
          counts.draft + ' en cours · ' + counts.none + ' pas commencé(s)' + (data.due_at ? ' — à rendre avant le ' + date(data.due_at) : '');
        list.innerHTML = '';
        if (!data.rows.length) list.innerHTML = '<li class="mb-muted">Aucun élève : partagez d’abord ce document avec une classe.</li>';
        data.rows.forEach(function (r) {
          var li = document.createElement('li');
          var label = { none: 'Pas commencé', draft: 'En cours', submitted: 'Rendu', returned: 'Corrigé' }[r.status];
          li.innerHTML = '<span><strong>' + esc(r.name) + '</strong> <span class="mb-badge mb-badge-' + esc(r.status) + '">' + esc(label) + '</span>' +
            (r.grade ? ' · ' + esc(r.grade) : '') + (r.submitted_at && r.status !== 'draft' ? ' <small class="mb-muted">' + esc(date(r.submitted_at)) + '</small>' : '') + '</span>';
          if (r.copy) {
            var a = document.createElement('a');
            a.className = 'mb-btn'; a.href = config.urls.editor.replace('/0/', '/' + r.copy + '/');
            a.textContent = r.status === 'submitted' ? 'Corriger' : 'Ouvrir';
            li.appendChild(a);
          }
          list.appendChild(li);
        });
      }).catch(function (e) { list.innerHTML = '<li class="mb-error">' + esc(e.message) + '</li>'; });
    },
  };

  /* ======================= Participation ======================= */
  var People = {
    open: function () {
      var list = $('mbPeopleList');
      list.innerHTML = '<li>Chargement…</li>';
      $('mbPeopleDialog').showModal();
      api('GET', config.urls.contributions).then(function (rows) {
        list.innerHTML = '';
        if (!rows.length) list.innerHTML = '<li class="mb-muted">Personne n’a encore écrit sur ce tableau.</li>';
        rows.forEach(function (r) {
          var li = document.createElement('li');
          li.innerHTML = '<span><strong>' + esc(r.name) + '</strong> <small class="mb-muted">' + esc(r.role) + '</small><br><small>' +
            r.objects + ' élément(s) sur ' + r.pages.length + ' page(s)' + (r.last_activity ? ' · dernière activité le ' + esc(date(r.last_activity)) : '') + '</small></span>';
          var actions = document.createElement('span');
          actions.className = 'mb-row';
          if (r.objects) {
            actions.appendChild(button('Montrer', function () { $('mbPeopleDialog').close(); People.show(r.user); }));
            if (r.user !== config.me) actions.appendChild(button('Supprimer', function () { People.remove(r); }));
          }
          li.appendChild(actions);
          list.appendChild(li);
        });
      }).catch(function (e) { list.innerHTML = '<li class="mb-error">' + esc(e.message) + '</li>'; });
    },
    show: function (userId) {
      var page = board.page();
      var objs = board.canvas.getObjects().filter(function (o) { return page.objects[o.id] && page.objects[o.id]._by === userId; });
      if (!objs.length) {
        var other = board.pages.filter(function (p) { return Object.keys(p.objects).some(function (k) { return p.objects[k]._by === userId; }); })[0];
        if (other) { board.showPage(other.uid).then(function () { People.show(userId); }); return; }
        board.ui.toast('Aucun élément de cette personne.');
        return;
      }
      board.setTool('select');
      // La sélection permet aussi de les déplacer, recolorer ou supprimer d'un coup.
      board.canvas.setActiveObject(objs.length > 1 ? new root.fabric.ActiveSelection(objs, { canvas: board.canvas }) : objs[0]);
      board.canvas.requestRenderAll();
      board.zoomFit && board.bounds && (function () {
        var b = board.bounds(objs), c = board.canvas;
        var zoom = Math.min(3, Math.max(0.1, Math.min((c.width - 80) / b.width, (c.height - 80) / b.height)));
        c.setViewportTransform([zoom, 0, 0, zoom, c.width / 2 - (b.left + b.width / 2) * zoom, c.height / 2 - (b.top + b.height / 2) * zoom]);
        board.ui.zoom(zoom); board.ui.cursorsMoved(board);
      })();
    },
    remove: function (row) {
      if (!confirm('Supprimer les ' + row.objects + ' élément(s) de ' + row.name + ' sur toutes les pages ? Une version est créée avant, pour pouvoir revenir en arrière.')) return;
      api('POST', config.urls.snapshots, { label: 'Avant suppression des éléments de ' + row.name }).then(function () {
        board.removeAuthor(row.user);
        $('mbPeopleDialog').close();
        board.ui.toast('Éléments supprimés (récupérables dans « Versions »).');
      }).catch(function (e) { board.ui.toast(e.message, 'error'); });
    },
  };

  /* Retire tous les éléments d'un auteur, sur toutes les pages. */
  MB.Board.prototype.removeAuthor = function (userId) {
    var self = this, ops = [];
    this.canvas.discardActiveObject();
    this.pages.forEach(function (page) {
      Object.keys(page.objects).forEach(function (id) {
        if (page.objects[id]._by === userId) ops.push({ kind: 'object.delete', page: page.uid, id: id });
      });
    });
    ops.forEach(function (op) {
      self._applyToMirror(op);
      if (op.page === self.pageUid && self.byId[op.id]) { self.canvas.remove(self.byId[op.id]); delete self.byId[op.id]; }
    });
    this.sync.submit(ops.map(function (op) { return Object.assign({}, op, { op_id: root.MBSync.uid('o') }); }));
    this.canvas.requestRenderAll();
    return ops.length;
  };

  /* ======================= Branchements ======================= */
  document.addEventListener('DOMContentLoaded', function () {
    board = MB.board;
    api = MB.Panels.api;
    MB.Present = Present; MB.Work = Work; MB.People = People;
    var ui = board.ui, original = ui.document;
    ui.document = function (doc, access) {
      original.call(ui, doc, access);
      Work.refresh();
      if (doc.presentation !== undefined && !Present.active) Present.receive(doc.presentation);
    };
    board.sync.on('presentation', function (p) { Present.receive(p); });
    board.canvas.on('after:render', function () { Present.viewChanged(); });
    $('mbPresentBtn').addEventListener('click', function () { if (Present.active) Present.stop(); else Present.start(); });
    root.addEventListener('pagehide', function () {
      if (!Present.active) return;
      fetch(config.urls.presentation, { method: 'DELETE', credentials: 'same-origin', keepalive: true,
        headers: { 'X-CSRFToken': (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '' } });
    });
    $('mbWorkBtn').addEventListener('click', function () { Work.click(); });
    $('mbWorkClose').addEventListener('click', function () { $('mbWorkDialog').close(); });
    $('mbWorkSubmit').addEventListener('click', function () { Work.submit(); });
    $('mbWorkReturn').addEventListener('click', function () { Work.correct('return'); });
    $('mbWorkRedo').addEventListener('click', function () { Work.correct('redo'); });
    $('mbPeopleBtn').addEventListener('click', function () { People.open(); });
  });
})(window);
