/* Tableau mathématique — interface : barre d'outils, pages, présence, curseurs,
 * statut d'enregistrement, et fenêtres (formule + calcul, figure, assistant IA,
 * versions, partage, export / import). */
(function (root) {
  'use strict';
  var MB = root.MB = root.MB || {};
  var R = MB.Render;
  var $ = function (id) { return document.getElementById(id); };
  var config = JSON.parse($('mbConfig').textContent);
  var board;

  function api(method, url, body) {
    var headers = { Accept: 'application/json' };
    // Jeton CSRF pour toute écriture, avec ou sans corps (POST vide, DELETE).
    if (method !== 'GET') headers['X-CSRFToken'] = csrf();
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    return fetch(url, { method: method, credentials: 'same-origin', headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body) }).then(function (r) {
      if (r.status === 204) return null;
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var detail = data.detail || (data && typeof data === 'object' && Object.keys(data).map(function (k) { return [].concat(data[k]).join(' '); }).join(' '));
          throw new Error(detail || 'Erreur ' + r.status);
        }
        return data;
      });
    });
  }
  function csrf() { var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ''; }
  function esc(text) { var d = document.createElement('div'); d.textContent = text == null ? '' : String(text); return d.innerHTML; }
  function initials(name) { return String(name || '?').split(/\s+/).map(function (w) { return w.charAt(0); }).join('').slice(0, 2).toUpperCase(); }

  /* ======================= Contrôleur d'interface ======================= */
  var toastTimer;
  var cursors = {};
  var UI = {
    status: function (s) {
      var el = $('mbStatus'), text;
      el.dataset.state = s.state;
      if (s.state === 'offline') text = 'Hors ligne — ' + s.pending + ' modification' + (s.pending > 1 ? 's' : '') + ' en attente';
      else if (s.state === 'error') text = '⚠ ' + (s.error || 'Erreur d’enregistrement') + ' — nouvel essai…';
      else if (s.state === 'saving') text = 'Enregistrement…';
      else text = '✓ Enregistré';
      el.textContent = text + (s.state === 'saved' ? (s.live ? ' · en direct' : ' · synchronisé') : '');
    },
    toast: function (message, kind) {
      var el = $('mbToast');
      el.textContent = message;
      el.dataset.kind = kind || 'info';
      el.hidden = false;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(function () { el.hidden = true; }, 4000);
    },
    document: function (doc, access) {
      $('mbApp').dataset.access = access;
      var title = $('mbTitle');
      if (document.activeElement !== title) title.value = doc.title;
      title.readOnly = access !== 'manage';
      var role = $('mbRole');
      role.hidden = access === 'manage' || access === 'edit';
      role.textContent = 'Lecture seule';
      if (doc.classroom_name) role.title = 'Partagé avec ' + doc.classroom_name;
      document.querySelectorAll('[data-needs]').forEach(function (el) {
        var need = el.dataset.needs;
        el.hidden = need === 'manage' ? access !== 'manage' : access === 'view';
      });
    },
    presence: function (users) {
      var seen = {}, html = '';
      users.forEach(function (u) {
        if (seen[u.user]) return;
        seen[u.user] = true;
        html += '<span class="mb-avatar" style="background:' + esc(u.color) + '" title="' + esc(u.name) + '">' + esc(initials(u.name)) + '</span>';
      });
      $('mbPresence').innerHTML = html;
      $('mbPresence').setAttribute('aria-label', users.length + ' participant(s) connecté(s)');
      UI.colors = {};
      users.forEach(function (u) { UI.colors[u.client_id] = u; });
    },
    cursor: function (c, b) {
      var el = cursors[c.client_id];
      if (!el) {
        el = document.createElement('div');
        el.className = 'mb-cursor';
        $('mbCursors').appendChild(el);
        cursors[c.client_id] = el;
      }
      var who = (UI.colors || {})[c.client_id] || {};
      el.innerHTML = '<i class="bi bi-cursor-fill" style="color:' + esc(who.color || '#1971c2') + '"></i><span style="background:' + esc(who.color || '#1971c2') + '">' + esc(who.name || 'Participant') + '</span>';
      el.dataset.x = c.x; el.dataset.y = c.y; el.dataset.page = c.page; el.dataset.seen = Date.now();
      UI.placeCursor(el, b);
    },
    placeCursor: function (el, b) {
      var v = b.canvas.viewportTransform;
      el.hidden = el.dataset.page !== b.pageUid || Date.now() - el.dataset.seen > 10000;
      el.style.transform = 'translate(' + (el.dataset.x * v[0] + v[4]) + 'px,' + (el.dataset.y * v[3] + v[5]) + 'px)';
    },
    cursorsMoved: function (b) { Object.keys(cursors).forEach(function (k) { UI.placeCursor(cursors[k], b); }); },
    pages: function (pages, current, b) {
      var host = $('mbPages');
      host.innerHTML = '';
      pages.forEach(function (page, index) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'mb-page' + (page.uid === current ? ' is-active' : '');
        btn.setAttribute('role', 'tab');
        btn.setAttribute('aria-selected', page.uid === current ? 'true' : 'false');
        btn.textContent = (index + 1) + (page.title ? ' · ' + page.title : '');
        btn.title = b.canManage() ? 'Double-clic : renommer' : '';
        btn.addEventListener('click', function () { if (page.uid !== b.pageUid) b.showPage(page.uid); });
        btn.addEventListener('dblclick', function () {
          if (!b.canManage()) return;
          var title = prompt('Titre de la page', page.title || '');
          if (title !== null) b.pageOp({ kind: 'page.update', page: page.uid, props: { title: title.slice(0, 200) } });
        });
        host.appendChild(btn);
      });
      if (b.canManage() && pages.length > 1) {
        [['bi-chevron-left', 'Déplacer la page à gauche', -1], ['bi-chevron-right', 'Déplacer la page à droite', 1]].forEach(function (spec) {
          var move = document.createElement('button');
          move.type = 'button'; move.className = 'mb-icon-btn'; move.setAttribute('aria-label', spec[1]); move.title = spec[1];
          move.innerHTML = '<i class="bi ' + spec[0] + '"></i>';
          move.addEventListener('click', function () {
            var index = pages.findIndex(function (p) { return p.uid === b.pageUid; }) + spec[2];
            if (index >= 0 && index < pages.length) b.pageOp({ kind: 'page.move', index: index });
          });
          host.appendChild(move);
        });
        var del = document.createElement('button');
        del.type = 'button'; del.className = 'mb-icon-btn is-danger'; del.setAttribute('aria-label', 'Supprimer la page'); del.title = 'Supprimer la page';
        del.innerHTML = '<i class="bi bi-trash"></i>';
        del.addEventListener('click', function () {
          if (confirm('Supprimer cette page et son contenu ? (récupérable depuis « Versions »)')) b.pageOp({ kind: 'page.delete' });
        });
        host.appendChild(del);
      }
      var page = b.page();
      if (page) $('mbBackground').value = page.background;
    },
    tool: function (tool) {
      document.querySelectorAll('.mb-tool[data-tool]').forEach(function (btn) {
        btn.classList.toggle('is-active', btn.dataset.tool === tool);
        btn.setAttribute('aria-pressed', btn.dataset.tool === tool ? 'true' : 'false');
      });
    },
    zoom: function (zoom) { $('mbZoomValue').textContent = Math.round(zoom * 100) + ' %'; },
    history: function (b) { $('mbUndo').disabled = !b.undoStack.length; $('mbRedo').disabled = !b.redoStack.length; },
    selection: function (objects, b) {
      var bar = $('mbSelectionBar');
      bar.hidden = !objects.length || !b.canEdit();
      var special = objects.length === 1 && objects[0].mb;
      bar.querySelector('[data-act="edit"]').hidden = !special;
      // Écriture manuscrite (mb-ink.js) : conversion, forme, écriture originale.
      var ink = MB.Ink ? MB.Ink.selectionState(objects) : {};
      bar.querySelector('[data-act="to-text"]').hidden = !(ink.strokes && ink.recognition);
      bar.querySelector('[data-act="to-math"]').hidden = !(ink.strokes && ink.recognition);
      bar.querySelector('[data-act="shape"]').hidden = !ink.strokes;
      bar.querySelector('[data-act="restore"]').hidden = !ink.restore;
    },
  };
  MB.UI = UI;

  /* ======================= Formule et calcul ======================= */
  var mathEditing = null, lastCalc = null;
  function openMath(b, model) {
    mathEditing = model || null;
    var field = $('mbMathField');
    field.value = model ? model.latex : '';
    $('mbMathSize').value = String(model && model.fontSize || 28);
    $('mbMathSave').textContent = model ? 'Mettre à jour' : 'Insérer';
    $('mbMathError').textContent = '';
    $('mbCalcResult').innerHTML = '';
    $('mbCalcInsertRow').hidden = true;
    showCalcFields();
    $('mbMathDialog').showModal();
    setTimeout(function () { field.focus(); }, 50);
  }
  function showCalcFields() {
    var action = $('mbCalcAction').value;
    document.querySelectorAll('[data-calc]').forEach(function (row) { row.hidden = row.dataset.calc !== action; });
  }
  function renderLatexInto(el, latex) {
    return R.latexToSvg(latex, '#1f2937', 22).then(function (out) {
      el.innerHTML = '<img alt="" src="' + R.svgDataUrl(out.svg) + '">';
      el.querySelector('img').alt = latex;
    }).catch(function () { el.textContent = latex; });
  }
  function runCalc() {
    var action = $('mbCalcAction').value, latex = $('mbMathField').value.trim();
    var result = $('mbCalcResult');
    if (!latex) { result.textContent = 'Écrivez d’abord une expression.'; return; }
    result.textContent = 'Calcul en cours…';
    $('mbCalcInsertRow').hidden = true;
    api('POST', config.urls.calc, {
      action: action, latex: latex, variable: $('mbCalcVar').value, order: $('mbCalcOrder').value,
      lower: $('mbCalcLower').value, upper: $('mbCalcUpper').value, point: $('mbCalcPoint').value,
      direction: $('mbCalcDir').value, other_latex: action === 'equal' ? $('mbMathOther').value : '',
    }).then(function (data) {
      if (!data.ok) { result.innerHTML = '<span class="mb-error">' + esc(data.error) + '</span>'; return; }
      lastCalc = data;
      var latexOut = data.table ? R.vartableLatex(data.table) : data.latex;
      lastCalc.display = latexOut;
      renderLatexInto(result, latexOut);
      $('mbCalcInsertRow').hidden = false;
      $('mbCalcUse').hidden = !!data.table;
    }).catch(function (error) { result.innerHTML = '<span class="mb-error">' + esc(error.message) + '</span>'; });
  }
  function insertMath(latex) {
    var size = Number($('mbMathSize').value) || 28;
    return R.latexToSvg(latex, '#000', size).catch(function () { return { width: 220, height: 40 }; }).then(function (out) {
      var spot = board.freeSpot(out.width, out.height);
      return board.addModel({ type: 'math', latex: latex, color: board.color === '#ffffff' ? '#212529' : board.color,
        fontSize: size, left: spot.left, top: spot.top }, true);
    });
  }
  function saveMath() {
    var latex = $('mbMathField').value.trim();
    if (!latex) { $('mbMathError').textContent = 'La formule est vide.'; return; }
    R.latexToSvg(latex).then(function () {
      if (mathEditing) board.updateModel(mathEditing.id, { latex: latex, fontSize: Number($('mbMathSize').value) || 28 });
      else insertMath(latex);
      $('mbMathDialog').close();
    }).catch(function (error) { $('mbMathError').textContent = error.message; });
  }

  /* ======================= Figure (JSXGraph) ======================= */
  var geoEditing = null, geoBoard = null, geoTimer = null;
  var SNIPPETS = [
    ['Point', 'A = (1, 2)'], ['Segment', 's = Segment(A, B)'], ['Droite', 'd = Droite(A, B)'],
    ['Demi-droite', 'r = DemiDroite(A, B)'], ['Cercle', 'c = Cercle(A, B)'], ['Triangle', 't = Triangle(A, B, C)'],
    ['Angle', 'a = Angle(B, A, C)'], ['Vecteur', 'u = Vecteur(A, B)'], ['Milieu', 'M = Milieu(A, B)'],
    ['Perpendiculaire', 'p = Perpendiculaire(C, d)'], ['Parallèle', 'q = Parallele(C, d)'],
    ['Intersection', 'I = Intersection(d, c)'], ['Fonction', 'f(x) = x^2 - 2x - 1'], ['Tangente', 'T = Tangente(f, 1)'],
    ['Verticale', 'Verticale(2) [pointillé rouge]'], ['Texte', 'Texte((1, 1), "Légende")'],
  ];
  function geoView() {
    return { xmin: Number($('mbGeoXmin').value), xmax: Number($('mbGeoXmax').value), ymin: Number($('mbGeoYmin').value),
      ymax: Number($('mbGeoYmax').value), axes: $('mbGeoAxes').checked, grid: $('mbGeoGrid').checked };
  }
  function geoRebuild() {
    var JXG = root.JXG, view = geoView();
    if (!(view.xmax > view.xmin && view.ymax > view.ymin)) { $('mbGeoError').textContent = 'Fenêtre invalide : min doit être inférieur à max.'; return; }
    $('mbGeoError').textContent = '';
    if (geoBoard) JXG.JSXGraph.freeBoard(geoBoard);
    JXG.Options.text.display = 'internal';
    geoBoard = JXG.JSXGraph.initBoard('mbGeoBoard', R.boardAttributes(view, true));
    var script = $('mbGeoScript').value;
    var result = R.buildGeometry(geoBoard, script, { interactive: true });
    $('mbGeoErrors').innerHTML = result.errors.map(function (e) { return '<li>Ligne ' + e.line + ' : ' + esc(e.message) + '</li>'; }).join('');
    Object.keys(result.objects).forEach(function (name) {
      var obj = result.objects[name];
      if (obj.mbKind !== 'point' || obj.mbLine === undefined || obj.elType !== 'point') return;
      obj.on('up', function () {
        var lines = $('mbGeoScript').value.split('\n');
        var fmt = function (v) { return String(Math.round(v * 10) / 10); };
        var suffix = (/\[[^\]]*\]\s*$/.exec(lines[obj.mbLine]) || [''])[0];
        lines[obj.mbLine] = name + ' = (' + fmt(obj.X()) + ', ' + fmt(obj.Y()) + ')' + (suffix ? ' ' + suffix : '');
        $('mbGeoScript').value = lines.join('\n');
      });
    });
  }
  function openGeometry(b, model) {
    geoEditing = model || null;
    var view = (model && model.view) || { xmin: -5, xmax: 5, ymin: -4, ymax: 4, axes: true, grid: true };
    $('mbGeoScript').value = model ? model.script : 'f(x) = x^2 - 2x - 1\nA = (-1, 2)\nB = (3, 2)\ns = Segment(A, B)';
    $('mbGeoXmin').value = view.xmin; $('mbGeoXmax').value = view.xmax; $('mbGeoYmin').value = view.ymin; $('mbGeoYmax').value = view.ymax;
    $('mbGeoAxes').checked = view.axes !== false; $('mbGeoGrid').checked = view.grid !== false;
    $('mbGeoSave').textContent = model ? 'Mettre à jour' : 'Insérer';
    $('mbGeoDialog').showModal();
    setTimeout(geoRebuild, 30);
  }
  function geoFunction() {
    var name = ($('mbGeoFn').value || 'f').trim();
    var match = new RegExp('^\\s*' + name.replace(/[^\w']/g, '') + "\\s*\\(\\s*x\\s*\\)\\s*=\\s*([^\\[#\\n]+)", 'm').exec($('mbGeoScript').value);
    if (!match) { $('mbGeoError').textContent = 'Définissez d’abord ' + name + '(x) = … dans la construction.'; return null; }
    return { name: name, expression: match[1].trim() };
  }
  function geoAsymptotes() {
    var fn = geoFunction();
    if (!fn) return;
    $('mbGeoError').textContent = 'Calcul exact des asymptotes…';
    api('POST', config.urls.calc, { action: 'asymptotes', expression: fn.expression }).then(function (data) {
      if (!data.ok) { $('mbGeoError').textContent = data.error; return; }
      var unique = [], seen = {}, n = 0;
      data.vertical.forEach(function (a) {
        if (!seen['x=' + a]) { seen['x=' + a] = true; unique.push('Verticale(' + a + ') [pointillé rouge]'); }
      });
      data.horizontal.concat(data.oblique).forEach(function (h) {
        // Même droite en +∞ et en −∞ : une seule ligne.
        var expr = (h.slope !== undefined ? (h.slope + '*x + ' + h.intercept) : String(h.value)).replace('+ -', '- ');
        if (seen[expr]) return;
        seen[expr] = true;
        n += 1;
        unique.push('as' + n + '(x) = ' + expr + ' [pointillé rouge]');
      });
      $('mbGeoError').textContent = unique.length ? '' : 'Aucune asymptote pour ' + fn.name + '.';
      if (unique.length) { $('mbGeoScript').value += '\n# Asymptotes de ' + fn.name + '\n' + unique.join('\n'); geoRebuild(); }
    }).catch(function (e) { $('mbGeoError').textContent = e.message; });
  }
  function geoVariations() {
    var fn = geoFunction();
    if (!fn) return;
    $('mbGeoError').textContent = 'Calcul exact du tableau de variations…';
    api('POST', config.urls.calc, { action: 'variations', expression: fn.expression, name: fn.name }).then(function (data) {
      if (!data.ok) { $('mbGeoError').textContent = data.error; return; }
      $('mbGeoError').textContent = 'Tableau de variations ajouté au tableau.';
      var latex = R.vartableLatex(data.table);
      R.latexToSvg(latex, '#000', 24).then(function (out) {
        var spot = board.freeSpot(out.width, out.height + 380);  // place aussi pour la figure à venir
        board.addModel({ type: 'math', latex: latex, color: '#212529', fontSize: 24, left: spot.left, top: spot.top + 380 }, false);
      });
    }).catch(function (e) { $('mbGeoError').textContent = e.message; });
  }
  function saveGeometry() {
    var script = $('mbGeoScript').value, view = geoView();
    var model = { type: 'geometry', script: script, view: view, width: 480, height: 360 };
    R.geometryToSvg(model).then(function (out) {
      if (out.errors.length) { $('mbGeoError').textContent = 'Corrigez les lignes signalées avant d’enregistrer.'; return; }
      if (geoEditing) board.updateModel(geoEditing.id, { script: script, view: view });
      else {
        var spot = board.freeSpot(480, 360);
        board.addModel(Object.assign(model, { left: spot.left, top: spot.top }), true);
      }
      $('mbGeoDialog').close();
    }).catch(function (e) { $('mbGeoError').textContent = e.message; });
  }

  /* ======================= Assistant IA ======================= */
  var aiBlocks = [];
  function selectedLatex() {
    var objects = board.selected();
    var page = board.page();
    for (var i = 0; i < objects.length; i++) {
      var model = page.objects[objects[i].id];
      if (model && model.type === 'math') return model.latex;
    }
    return '';
  }
  function openAi() {
    var panel = $('mbAiPanel');
    panel.hidden = !panel.hidden;
    var latex = selectedLatex();
    $('mbAiContext').textContent = latex ? 'Formule sélectionnée : ' + latex : 'Astuce : sélectionnez une formule pour que l’assistant la prenne en compte.';
    if (!panel.hidden) $('mbAiQuestion').focus();
  }
  function askAi(action) {
    var out = $('mbAiResult');
    $('mbAiVerify').hidden = action !== 'verify' && $('mbAiVerify').hidden;
    if (action === 'verify' && $('mbAiVerify').hidden) { $('mbAiVerify').hidden = false; $('mbAiAnswer').focus(); return; }
    out.innerHTML = '<p class="mb-muted">Réflexion en cours…</p>';
    $('mbAiInsert').hidden = true;
    api('POST', config.urls.ai.replace('ACTION', action), {
      question: $('mbAiQuestion').value, latex: selectedLatex(), page: board.pageUid,
      student_answer: action === 'verify' ? $('mbAiAnswer').value : '', expected: action === 'verify' ? $('mbAiExpected').value : '',
    }).then(function (data) {
      aiBlocks = data.blocks || [];
      var html = '';
      if (data.verification) {
        var v = data.verification;
        html += '<p class="mb-verdict" data-ok="' + (v.correct === true ? 'yes' : v.correct === false ? 'no' : 'unknown') + '">' +
          (v.correct === true ? '✓ Réponse juste' : v.correct === false ? '✗ Réponse à revoir' : 'Vérification incertaine') +
          (v.method === 'sympy' ? ' (vérifié par calcul exact)' : '') + '</p>';
        if (v.details) html += '<p>' + esc(v.details) + '</p>';
      }
      if (data.reply) html += '<p class="fw-semibold">' + esc(data.reply) + '</p>';
      out.innerHTML = html;
      aiBlocks.forEach(function (block) {
        var el = document.createElement(block.type === 'math' ? 'div' : 'p');
        if (block.type === 'math') { el.className = 'mb-ai-math'; renderLatexInto(el, block.content); } else el.textContent = block.content;
        out.appendChild(el);
      });
      $('mbAiInsert').hidden = !aiBlocks.length || !board.canEdit();
    }).catch(function (error) { out.innerHTML = '<p class="mb-error">' + esc(error.message) + '</p>'; });
  }
  function insertAi() {
    var center = board.viewCenter(), spot = board.freeSpot(520, 160), y = spot.top, chain = Promise.resolve();
    center = { x: spot.left + 200 };
    aiBlocks.forEach(function (block) {
      chain = chain.then(function () {
        var model = block.type === 'math'
          ? { type: 'math', latex: block.content, color: '#212529', fontSize: 24, left: center.x - 200, top: y }
          : { type: 'textbox', text: block.content, left: center.x - 200, top: y, width: 520, fontSize: 18, fill: '#212529', fontFamily: 'system-ui, sans-serif' };
        return board.addModel(model, false).then(function (obj) { y += obj ? obj.getScaledHeight() + 14 : 40; });
      });
    });
    chain.then(function () { UI.toast('Réponse insérée dans le tableau.'); });
  }

  /* ======================= Versions ======================= */
  function loadVersions() {
    var list = $('mbVersionsList');
    list.innerHTML = '<li class="mb-muted">Chargement…</li>';
    api('GET', config.urls.snapshots).then(function (items) {
      var kinds = { auto: 'Automatique', manual: 'Manuelle', before_restore: 'Avant restauration' };
      list.innerHTML = items.length ? '' : '<li class="mb-muted">Aucune version pour le moment.</li>';
      items.forEach(function (item) {
        var li = document.createElement('li');
        var date = new Date(item.created_at).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
        li.innerHTML = '<div><strong>' + esc(item.label || kinds[item.kind] || 'Version') + '</strong><br><span class="mb-muted small">' + esc(date) +
          ' · révision ' + item.revision + (item.created_by_name ? ' · ' + esc(item.created_by_name) : '') + '</span></div>';
        if (board.canManage()) {
          var btn = document.createElement('button');
          btn.type = 'button'; btn.className = 'mb-btn'; btn.textContent = 'Restaurer';
          btn.addEventListener('click', function () {
            if (!confirm('Restaurer cette version ? L’état actuel sera d’abord sauvegardé.')) return;
            api('POST', config.urls.snapshots + item.id + '/restaurer/', {}).then(function () {
              $('mbVersionsDialog').close(); UI.toast('Version restaurée.'); board.reload();
            }).catch(function (e) { UI.toast(e.message, 'error'); });
          });
          li.appendChild(btn);
        }
        list.appendChild(li);
      });
    }).catch(function (e) { list.innerHTML = '<li class="mb-error">' + esc(e.message) + '</li>'; });
  }

  /* ======================= Partage ======================= */
  function openShare() {
    var doc = board.documentInfo || {};
    var cls = $('mbShareClass'), lvl = $('mbShareLevel');
    cls.innerHTML = '<option value="">Aucune (document personnel)</option>' + config.classrooms.map(function (c) {
      return '<option value="' + c.id + '">' + esc(c.name) + '</option>'; }).join('');
    lvl.innerHTML = '<option value="">—</option>' + config.levels.map(function (l) {
      return '<option value="' + esc(l.code) + '">' + esc(l.label) + '</option>'; }).join('');
    cls.value = doc.classroom || ''; lvl.value = doc.level || '';
    $('mbShareChapter').value = doc.chapter || ''; $('mbShareEdit').checked = !!doc.students_can_edit;
    $('mbShareTask').checked = !!doc.accepts_submissions;
    $('mbShareDue').value = doc.due_at ? localInput(new Date(doc.due_at)) : '';
    $('mbShareDueRow').hidden = !doc.accepts_submissions;
    $('mbShareVisible').checked = doc.class_visible !== false;
    $('mbShareVisibleRow').hidden = !doc.classroom;
    $('mbShareError').textContent = '';
    loadMembers();
    $('mbShareDialog').showModal();
  }
  function localInput(date) {
    function two(n) { return (n < 10 ? '0' : '') + n; }
    return date.getFullYear() + '-' + two(date.getMonth() + 1) + '-' + two(date.getDate()) + 'T' + two(date.getHours()) + ':' + two(date.getMinutes());
  }
  function loadMembers() {
    var list = $('mbMembersList');
    api('GET', config.urls.members).then(function (members) {
      list.innerHTML = members.length ? '' : '<li class="mb-muted">Aucun membre invité.</li>';
      members.forEach(function (m) {
        var li = document.createElement('li');
        li.innerHTML = '<span>' + esc(m.name) + ' <span class="mb-muted small">@' + esc(m.username) + '</span></span>';
        var role = document.createElement('select');
        role.className = 'form-select form-select-sm mb-short-select';
        role.setAttribute('aria-label', 'Rôle de ' + m.name);
        role.innerHTML = '<option value="viewer">Lecture</option><option value="editor">Modification</option><option value="manager">Gestion</option>';
        role.value = m.role;
        role.addEventListener('change', function () { api('PATCH', config.urls.members + m.id + '/', { role: role.value }).catch(function (e) { $('mbShareError').textContent = e.message; }); });
        var del = document.createElement('button');
        del.type = 'button'; del.className = 'mb-icon-btn is-danger'; del.setAttribute('aria-label', 'Retirer ' + m.name);
        del.innerHTML = '<i class="bi bi-x-lg"></i>';
        del.addEventListener('click', function () { api('DELETE', config.urls.members + m.id + '/').then(loadMembers); });
        li.appendChild(role); li.appendChild(del);
        list.appendChild(li);
      });
    }).catch(function (e) { list.innerHTML = '<li class="mb-error">' + esc(e.message) + '</li>'; });
  }

  /* ======================= Export / import ======================= */
  function download(name, href) {
    var a = document.createElement('a'); a.href = href; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  }
  function exportAs(kind) {
    var title = ($('mbTitle').value || 'tableau').replace(/[^\w\-]+/g, '_');
    if (kind === 'png') download(title + '.png', board.exportImage('png'));
    else if (kind === 'svg') {
      var url = URL.createObjectURL(new Blob([board.exportImage('svg')], { type: 'image/svg+xml' }));
      download(title + '.svg', url); setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
    } else if (kind === 'pdf') {
      var win = root.open('', '_blank');
      if (!win) { UI.toast('Autorisez les fenêtres pour exporter en PDF.', 'error'); return; }
      win.document.write('<p style="font-family:sans-serif">Préparation du PDF…</p>');
      board.pageImages().then(function (images) {
        win.document.open();
        win.document.write('<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>' + esc($('mbTitle').value) +
          '</title><style>@page{margin:12mm}body{margin:0}img{display:block;max-width:100%;max-height:96vh;margin:0 auto;page-break-after:always}</style></head><body>' +
          images.map(function (src) { return '<img src="' + src + '" alt="">'; }).join('') + '</body></html>');
        win.document.close();
        setTimeout(function () { win.focus(); win.print(); }, 400);
      });
    }
  }
  function importImage(file) {
    if (!file) return;
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) { UI.toast('Formats acceptés : PNG, JPEG, WebP.', 'error'); return; }
    var reader = new FileReader();
    reader.onload = function () {
      var img = new Image();
      img.onload = function () {
        var max = 1600, scale = Math.min(1, max / Math.max(img.width, img.height));
        var c = document.createElement('canvas');
        c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        var type = file.type === 'image/png' ? 'image/png' : 'image/jpeg';
        var fit = Math.min(1, 600 / Math.max(c.width, c.height)), spot = board.freeSpot(c.width * fit, c.height * fit);
        function place(src) { board.addModel({ type: 'image', src: src, left: spot.left, top: spot.top, scaleX: fit, scaleY: fit }, true); }
        function embedded() {
          // Hors ligne : l'image voyage dans l'opération (2 Mo au plus).
          var src = c.toDataURL(type, 0.85);
          if (src.length > 1900000) src = c.toDataURL('image/jpeg', 0.7);
          if (src.length > 1900000) { UI.toast('Image trop lourde, même compressée.', 'error'); return; }
          place(src);
        }
        if (!navigator.onLine) { embedded(); return; }
        // En ligne : fichier enregistré sur le serveur, l'objet ne garde que son adresse.
        c.toBlob(function (blob) {
          var form = new FormData();
          form.append('image', blob, 'image.' + (type === 'image/png' ? 'png' : 'jpg'));
          fetch(config.urls.images, { method: 'POST', credentials: 'same-origin', body: form,
            headers: { 'X-CSRFToken': csrf(), Accept: 'application/json' } })
            .then(function (r) { return r.json().then(function (d) { if (!r.ok) throw new Error(d.detail || 'Envoi impossible'); return d; }); })
            .then(function (data) { place(data.src); })
            .catch(function (error) { if (!navigator.onLine) embedded(); else UI.toast(error.message, 'error'); });
        }, type, 0.9);
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  }

  /* ======================= Branchements ======================= */
  function bind() {
    document.querySelectorAll('.mb-tool[data-tool]').forEach(function (btn) {
      btn.addEventListener('click', function () { board.setTool(btn.dataset.tool); });
    });
    var colors = document.querySelector('.mb-colors');
    MB.COLORS.forEach(function (color) {
      var swatch = document.createElement('button');
      swatch.type = 'button'; swatch.className = 'mb-swatch'; swatch.style.background = color;
      swatch.setAttribute('aria-label', 'Couleur ' + color); swatch.title = color;
      swatch.addEventListener('click', function () {
        colors.querySelectorAll('.mb-swatch').forEach(function (s) { s.classList.remove('is-active'); });
        swatch.classList.add('is-active');
        board.setColor(color);
      });
      colors.appendChild(swatch);
    });
    colors.firstChild.classList.add('is-active');
    $('mbWidth').addEventListener('input', function () { board.setWidth(Number(this.value)); });
    $('mbUndo').addEventListener('click', function () { board.undo(); });
    $('mbRedo').addEventListener('click', function () { board.redo(); });
    $('mbAddPage').addEventListener('click', function () { board.addPage('grid'); });
    $('mbBackground').addEventListener('change', function () { board.pageOp({ kind: 'page.update', props: { background: this.value } }); board.canvas.requestRenderAll(); });
    $('mbZoomIn').addEventListener('click', function () { board.zoomBy(1.2); });
    $('mbZoomOut').addEventListener('click', function () { board.zoomBy(1 / 1.2); });
    $('mbZoomValue').addEventListener('click', function () { board.zoomFit(); });
    $('mbSelectionBar').addEventListener('click', function (e) {
      var btn = e.target.closest('button[data-act]');
      if (!btn) return;
      var act = btn.dataset.act;
      if (MB.Ink && MB.Ink.action(act)) return;
      if (act === 'delete') board.deleteSelected();
      else if (act === 'copy') board.copy(false);
      else if (act === 'duplicate') board.duplicate();
      else if (act === 'edit') {
        var obj = board.selected()[0], model = obj && board.page().objects[obj.id];
        if (model && model.type === 'math') openMath(board, model); else if (model) openGeometry(board, model);
      } else board.arrange(act);
    });
    $('mbTitle').addEventListener('change', function () {
      var title = this.value.trim();
      if (!title) { this.value = board.documentInfo.title; return; }
      api('PATCH', config.urls.document, { title: title }).then(function (doc) { board.documentInfo = doc; UI.toast('Titre enregistré.'); })
        .catch(function (e) { UI.toast(e.message, 'error'); });
    });

    // Formule
    $('mbMathBtn').addEventListener('click', function () { openMath(board, null); });
    $('mbCalcAction').addEventListener('change', showCalcFields);
    $('mbCalcRun').addEventListener('click', runCalc);
    $('mbCalcInsert').addEventListener('click', function () { if (lastCalc) { insertMath(lastCalc.display); UI.toast('Résultat inséré.'); } });
    $('mbCalcUse').addEventListener('click', function () { if (lastCalc) $('mbMathField').value = lastCalc.latex; });
    $('mbMathSave').addEventListener('click', saveMath);
    $('mbMathCancel').addEventListener('click', function () { $('mbMathDialog').close(); });

    // Figure
    $('mbGeoBtn').addEventListener('click', function () { openGeometry(board, null); });
    var snippets = $('mbGeoSnippets');
    SNIPPETS.forEach(function (s) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'mb-snippet'; b.textContent = s[0]; b.title = s[1];
      b.addEventListener('click', function () {
        var area = $('mbGeoScript');
        area.value = area.value.replace(/\s*$/, '') + '\n' + s[1];
        geoRebuild();
      });
      snippets.appendChild(b);
    });
    $('mbGeoScript').addEventListener('input', function () { clearTimeout(geoTimer); geoTimer = setTimeout(geoRebuild, 400); });
    ['mbGeoXmin', 'mbGeoXmax', 'mbGeoYmin', 'mbGeoYmax', 'mbGeoAxes', 'mbGeoGrid'].forEach(function (id) { $(id).addEventListener('change', geoRebuild); });
    $('mbGeoAsym').addEventListener('click', geoAsymptotes);
    $('mbGeoVar').addEventListener('click', geoVariations);
    $('mbGeoSave').addEventListener('click', saveGeometry);
    $('mbGeoCancel').addEventListener('click', function () { $('mbGeoDialog').close(); });

    // IA (désactivée par réglage : ni bouton ni panneau)
    if (config.aiEnabled && $('mbAiBtn')) {
      $('mbAiBtn').addEventListener('click', openAi);
      $('mbAiClose').addEventListener('click', function () { $('mbAiPanel').hidden = true; });
      document.querySelectorAll('[data-ai]').forEach(function (btn) { btn.addEventListener('click', function () { askAi(btn.dataset.ai); }); });
      $('mbAiInsert').addEventListener('click', insertAi);
    }

    // Versions
    $('mbVersionsBtn').addEventListener('click', function () { loadVersions(); $('mbVersionsDialog').showModal(); });
    $('mbVersionCreate').addEventListener('click', function () {
      api('POST', config.urls.snapshots, { label: $('mbVersionLabel').value }).then(function () {
        $('mbVersionLabel').value = ''; loadVersions(); UI.toast('Version créée.');
      }).catch(function (e) { UI.toast(e.message, 'error'); });
    });

    // Partage
    $('mbShareBtn').addEventListener('click', openShare);
    $('mbShareSave').addEventListener('click', function () {
      api('PATCH', config.urls.document, { classroom: $('mbShareClass').value ? Number($('mbShareClass').value) : null,
        level: $('mbShareLevel').value, chapter: $('mbShareChapter').value, students_can_edit: $('mbShareEdit').checked,
        class_visible: $('mbShareVisible').checked,
        accepts_submissions: $('mbShareTask').checked,
        due_at: $('mbShareTask').checked && $('mbShareDue').value ? new Date($('mbShareDue').value).toISOString() : null })
        .then(function (doc) { board.documentInfo = doc; UI.document(doc, board.access); UI.toast('Réglages enregistrés.'); $('mbShareError').textContent = ''; })
        .catch(function (e) { $('mbShareError').textContent = e.message; });
    });
    $('mbShareTask').addEventListener('change', function () { $('mbShareDueRow').hidden = !this.checked; });
    $('mbShareClass').addEventListener('change', function () { $('mbShareVisibleRow').hidden = !this.value; });
    $('mbMemberAdd').addEventListener('click', function () {
      var name = $('mbMemberName').value.trim();
      if (!name) return;
      api('POST', config.urls.members, { username: name, role: $('mbMemberRole').value }).then(function () {
        $('mbMemberName').value = ''; $('mbShareError').textContent = ''; loadMembers();
      }).catch(function (e) { $('mbShareError').textContent = e.message; });
    });

    // Export / import
    document.querySelectorAll('[data-export]').forEach(function (btn) { btn.addEventListener('click', function () { exportAs(btn.dataset.export); }); });
    $('mbImportImage').addEventListener('click', function () { $('mbImageFile').click(); });
    $('mbImageFile').addEventListener('change', function () { importImage(this.files[0]); this.value = ''; });
  }

  MB.Panels = { openMath: openMath, openGeometry: openGeometry, api: api };

  /* Hauteur exacte de l'éditeur : sous la barre du site, au-dessus de la navigation mobile. */
  function fitApp() {
    var app = $('mbApp');
    var top = app.getBoundingClientRect().top + root.scrollY;
    var nav = document.querySelector('.bottom-nav');
    var navHeight = nav && getComputedStyle(nav).display !== 'none' ? nav.offsetHeight : 0;
    app.style.height = Math.max(420, root.innerHeight - top - navHeight) + 'px';
  }

  document.addEventListener('DOMContentLoaded', function () {
    fitApp();
    root.addEventListener('resize', fitApp);
    board = new MB.Board(config);
    board.ui = UI;
    MB.board = board;
    bind();
    board.init().then(function () { board.setTool('select'); UI.history(board); });
  });
})(window);
