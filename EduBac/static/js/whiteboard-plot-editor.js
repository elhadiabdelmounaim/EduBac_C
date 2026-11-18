/**
 * Fenêtres d'édition : repère interactif, tableau de variations, arbre de probabilités.
 * Interface seulement : le tableau blanc fournit onSave (placer ou mettre à jour l'objet).
 */
(function () {
  'use strict';
  var P = window.EduBacPlot, T = window.EduBacTables, M = window.EduBacMath;
  if (!P || !T || !M) return;
  function $(id) { return document.getElementById(id); }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function newId() { return 'i' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }

  /* ============================================================ repère */
  var dialog = $('wbPlotEditor');
  var draft = null, options = null, previewLayout = null, previewDrag = null;

  function previewPlot() {
    var canvas = $('wbPlotPreview');
    return Object.assign({}, draft, { x: 0, y: 0, w: canvas.width, h: canvas.height });
  }
  function refresh() {
    var canvas = $('wbPlotPreview'), ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    var shown = previewPlot();
    previewLayout = P.render(ctx, shown, { reviewer: true, traces: draft._traces || {} });
    var scene = previewLayout.scene;
    // Erreurs et informations au bon endroit dans la liste.
    document.querySelectorAll('#wbPlotItems li').forEach(function (li) {
      var msg = li.querySelector('.wb-plot-item-msg'), id = li.dataset.id;
      var error = scene.errors[id], info = scene.infos[id];
      msg.textContent = error || info || '';
      msg.className = 'wb-plot-item-msg' + (error ? ' is-error' : info ? ' is-info' : '');
      var input = li.querySelector('.wb-plot-line');
      var item = draft.items.find(function (it) { return it.id === id; });
      if (item && document.activeElement !== input && input.value !== item.line) input.value = item.line;
    });
    var fnSelect = $('wbPlotTableFn'), current = fnSelect.value;
    var fns = scene.list.filter(function (o) { return o.k === 'fn' && /^[A-Za-z_]\w*$/.test(o.name); });
    fnSelect.replaceChildren.apply(fnSelect, fns.map(function (o) { var opt = document.createElement('option'); opt.value = opt.textContent = o.name; return opt; }));
    if (current) fnSelect.value = current;
    $('wbPlotTableGen').disabled = !fns.length;
  }
  function renderItems() {
    var list = $('wbPlotItems');
    list.replaceChildren();
    draft.items.forEach(function (item, index) {
      var li = document.createElement('li');
      li.dataset.id = item.id;
      li.innerHTML = '<div class="wb-plot-item-row">'
        + '<input type="color" class="wb-plot-color" aria-label="Couleur">'
        + '<input type="text" class="wb-plot-line form-control form-control-sm font-monospace" spellcheck="false" aria-label="Commande">'
        + '<button type="button" class="wb-plot-icon" data-act="hide"></button>'
        + '<button type="button" class="wb-plot-icon" data-act="up" aria-label="Monter" title="Monter"><i class="bi bi-arrow-up" aria-hidden="true"></i></button>'
        + '<button type="button" class="wb-plot-icon is-danger" data-act="del" aria-label="Supprimer" title="Supprimer"><i class="bi bi-trash" aria-hidden="true"></i></button>'
        + '</div><p class="wb-plot-item-msg"></p>';
      var color = li.querySelector('.wb-plot-color'), line = li.querySelector('.wb-plot-line'), hide = li.querySelector('[data-act="hide"]');
      color.value = item.color || P.PALETTE[index % P.PALETTE.length];
      line.value = item.line;
      hide.innerHTML = '<i class="bi ' + (item.hidden ? 'bi-eye-slash' : 'bi-eye') + '" aria-hidden="true"></i>';
      hide.setAttribute('aria-label', item.hidden ? 'Afficher' : 'Masquer'); hide.title = hide.getAttribute('aria-label');
      color.addEventListener('input', function () { item.color = color.value; refresh(); });
      line.addEventListener('input', function () { item.line = line.value; delete item.val; refresh(); });
      hide.addEventListener('click', function () { item.hidden = !item.hidden; renderItems(); refresh(); });
      li.querySelector('[data-act="del"]').addEventListener('click', function () {
        draft.items = draft.items.filter(function (it) { return it !== item; }); renderItems(); refresh();
      });
      li.querySelector('[data-act="up"]').addEventListener('click', function () {
        var i = draft.items.indexOf(item); if (i < 1) return;
        draft.items.splice(i, 1); draft.items.splice(i - 1, 0, item); renderItems(); refresh();
      });
      list.appendChild(li);
    });
  }
  function readView() {
    var v = { xmin: Number($('wbPlotXmin').value), xmax: Number($('wbPlotXmax').value), ymin: Number($('wbPlotYmin').value), ymax: Number($('wbPlotYmax').value) };
    if ([v.xmin, v.xmax, v.ymin, v.ymax].every(isFinite) && v.xmax > v.xmin && v.ymax > v.ymin) { draft.view = v; return true; }
    return false;
  }
  function writeView() {
    var v = draft.view;
    $('wbPlotXmin').value = +v.xmin.toFixed(3); $('wbPlotXmax').value = +v.xmax.toFixed(3);
    $('wbPlotYmin').value = +v.ymin.toFixed(3); $('wbPlotYmax').value = +v.ymax.toFixed(3);
    var o = draft.opts;
    $('wbPlotGrid').checked = o.grid !== false; $('wbPlotAxes').checked = o.axes !== false; $('wbPlotOrtho').checked = o.ortho !== false;
    $('wbPlotPi').checked = !!o.pi; $('wbPlotComplex').checked = !!o.complex;
  }
  function addCommand() {
    var input = $('wbPlotCmd'), line = input.value.trim(), err = $('wbPlotCmdError');
    if (!line) return;
    if (draft.items.length >= 60) { err.textContent = '60 éléments au maximum par repère.'; return; }
    var item = { id: newId(), line: line, color: P.PALETTE[draft.items.length % P.PALETTE.length] };
    var test = clone(draft); test.items.push(item);
    var scene = P.evalScene(test);
    if (scene.errors[item.id]) { err.textContent = scene.errors[item.id]; input.focus(); return; }
    err.textContent = '';
    draft.items.push(item); input.value = '';
    renderItems(); refresh(); input.focus();
  }

  if (dialog) {
    $('wbPlotSnippets').replaceChildren.apply($('wbPlotSnippets'), P.SNIPPETS.map(function (s) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'wb-plot-snippet'; b.textContent = s[0]; b.title = s[1];
      b.addEventListener('click', function () { var input = $('wbPlotCmd'); input.value = s[1]; input.focus(); input.select(); });
      return b;
    }));
    $('wbPlotAdd').addEventListener('click', addCommand);
    $('wbPlotCmd').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); addCommand(); } });
    ['wbPlotXmin', 'wbPlotXmax', 'wbPlotYmin', 'wbPlotYmax'].forEach(function (id) { $(id).addEventListener('change', function () { if (readView()) refresh(); }); });
    [['wbPlotGrid', 'grid'], ['wbPlotAxes', 'axes'], ['wbPlotOrtho', 'ortho'], ['wbPlotPi', 'pi'], ['wbPlotComplex', 'complex']].forEach(function (pair) {
      $(pair[0]).addEventListener('change', function (e) { draft.opts[pair[1]] = e.target.checked; refresh(); });
    });
    $('wbPlotTitle').addEventListener('input', function (e) { draft.title = e.target.value; refresh(); });
    $('wbPlotPreset').addEventListener('change', function (e) {
      var key = e.target.value; e.target.value = '';
      if (!key) return;
      if (draft.items.length && !window.confirm('Remplacer le contenu du repère par ce modèle ?')) return;
      var fresh = P.defaultPlot(draft.x, draft.y, key);
      draft.title = fresh.title; draft.view = fresh.view; draft.home = fresh.home; draft.opts = fresh.opts; draft.items = fresh.items;
      $('wbPlotTitle').value = draft.title; writeView(); renderItems(); refresh();
    });
    $('wbPlotTableGen').addEventListener('click', function () {
      var name = $('wbPlotTableFn').value, scene = P.evalScene(draft), fn = scene.objs[name];
      if (!fn || !options.onTable) return;
      var v = P.effectiveView(draft), lo = fn.dom ? Math.max(v.xmin, fn.dom[0]) : v.xmin, hi = fn.dom ? Math.min(v.xmax, fn.dom[1]) : v.xmax;
      options.onTable(T.generateTable(fn.f, name, Math.round(lo * 100) / 100, Math.round(hi * 100) / 100), draft);
    });
    $('wbPlotCancel').addEventListener('click', function () { dialog.close(); });
    $('wbPlotSave').addEventListener('click', function () {
      if (!readView()) { $('wbPlotCmdError').textContent = 'Fenêtre invalide : x max doit dépasser x min, y max dépasser y min.'; return; }
      var pending = $('wbPlotCmd').value.trim();
      if (pending) { addCommand(); if ($('wbPlotCmdError').textContent) return; }
      var result = clone(draft);
      delete result._traces;
      if (!result.home) result.home = Object.assign({}, result.view);
      dialog.close();
      options.onSave(result);
    });

    // Aperçu manipulable : mêmes gestes que sur le tableau.
    var canvas = $('wbPlotPreview');
    function pos(e) { var r = canvas.getBoundingClientRect(); return { x: (e.clientX - r.left) * canvas.width / r.width, y: (e.clientY - r.top) * canvas.height / r.height }; }
    canvas.addEventListener('pointerdown', function (e) {
      var p = pos(e), shown = previewPlot(), hit = P.hitTest(shown, previewLayout, p);
      if (!hit) return;
      if (hit.type === 'button') {
        if (hit.name === 'zoomIn') P.zoom(draft, 0.8); else if (hit.name === 'zoomOut') P.zoom(draft, 1.25); else if (hit.name === 'reset') P.resetView(draft);
        writeView(); refresh(); return;
      }
      if (hit.type === 'header') return;
      previewDrag = { hit: hit, last: p }; canvas.setPointerCapture(e.pointerId);
    });
    canvas.addEventListener('pointermove', function (e) {
      if (!previewDrag) return;
      var p = pos(e), shown = previewPlot();
      if (P.drag(shown, previewDrag.hit, p, previewDrag.last)) { draft.view = shown.view; writeView(); refresh(); }
      previewDrag.last = p;
    });
    canvas.addEventListener('pointerup', function () { previewDrag = null; });
    canvas.addEventListener('wheel', function (e) {
      e.preventDefault();
      var shown = previewPlot();
      if (P.zoom(shown, e.deltaY > 0 ? 1.15 : 0.87, pos(e))) { draft.view = shown.view; writeView(); refresh(); }
    }, { passive: false });
  }

  function openPlot(plot, opts) {
    if (!dialog) return;
    options = opts || {};
    draft = clone(plot);
    draft.opts = draft.opts || {};
    draft.items = (draft.items || []).map(function (it) { return Object.assign({ id: newId() }, it); });
    $('wbPlotEditorTitle').textContent = options.creating ? 'Nouveau repère' : 'Modifier le repère';
    $('wbPlotSave').textContent = options.creating ? 'Placer sur le tableau' : 'Enregistrer';
    $('wbPlotTitle').value = draft.title || '';
    $('wbPlotCmd').value = ''; $('wbPlotCmdError').textContent = '';
    writeView(); renderItems();
    dialog.showModal();
    refresh();
    $('wbPlotCmd').focus();
  }

  /* ============================================== tableau / arbre (texte) */
  var textDialog = $('wbTextObjEditor'), textOptions = null, textKind = null;
  var EXAMPLES = {
    vartable: [
      ['Variations', "x : -∞ ; -1 ; 1 ; +∞\nf'(x) : + ; 0 ; - ; 0 ; +\nf : -∞ ; ↗ ; 2 ; ↘ ; -2 ; ↗ ; +∞"],
      ['Valeur interdite', "x : -∞ ; 1 ; +∞\nf'(x) : - ; || ; -\nf : 0 ; ↘ ; -∞||+∞ ; ↘ ; 0"],
      ['Signe d’un produit', 'x : -∞ ; -2 ; 3 ; +∞\nx+2 : - ; 0 ; + ; ; +\nx-3 : - ; ; - ; 0 ; +\n(x+2)(x-3) : + ; 0 ; - ; 0 ; +'],
    ],
    probtree: [
      ['Deux épreuves', 'A : 0,3\n  B : 0,6\n  non B : 0,4\nnon A : 0,7\n  B : 0,2\n  non B : 0,8'],
      ['Tirages sans remise', 'R : 3/5\n  R : 2/4\n  V : 2/4\nV : 2/5\n  R : 3/4\n  V : 1/4'],
    ],
  };
  var HELP = {
    vartable: 'Une ligne par rangée, « nom : cellules » séparées par « ; ». Ligne des x d’abord. Signes : + 0 - entre les valeurs, « || » valeur interdite. Variations : valeurs et flèches ↗ ↘ (ou / \\).',
    probtree: 'Une branche par ligne « événement : probabilité ». Deux espaces d’indentation par niveau. « non A » s’écrit Ā. Fractions acceptées (1/3).',
  };
  function textPreview() {
    var canvas = $('wbTextObjPreview'), ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    var obj = { x: 10, y: 10, text: $('wbTextObjInput').value, color: '#12306b' };
    var err = '';
    try { textKind === 'vartable' ? T.parseTable(obj.text) : T.parseTree(obj.text); } catch (e) { err = e.message; }
    $('wbTextObjError').textContent = err;
    if (!err) {
      ctx.save();
      // Mise à l'échelle si l'objet dépasse l'aperçu.
      var probe = document.createElement('canvas').getContext('2d');
      (textKind === 'vartable' ? T.renderTable : T.renderTree)(probe, obj);
      var scale = Math.min(1, (canvas.width - 20) / (obj._width || 1), (canvas.height - 20) / (obj._height || 1));
      ctx.scale(scale, scale);
      (textKind === 'vartable' ? T.renderTable : T.renderTree)(ctx, obj);
      ctx.restore();
    }
    $('wbTextObjSave').disabled = !!err;
  }
  if (textDialog) {
    $('wbTextObjInput').addEventListener('input', textPreview);
    $('wbTextObjCancel').addEventListener('click', function () { textDialog.close(); });
    $('wbTextObjSave').addEventListener('click', function () {
      textPreview();
      if ($('wbTextObjError').textContent) return;
      textDialog.close();
      textOptions.onSave($('wbTextObjInput').value.trim());
    });
  }
  function openText(kind, text, opts) {
    if (!textDialog) return;
    textKind = kind; textOptions = opts || {};
    $('wbTextObjTitle').textContent = (textOptions.creating ? 'Nouveau ' : 'Modifier le ') + (kind === 'vartable' ? 'tableau de variations / signes' : 'arbre de probabilités');
    $('wbTextObjHelp').textContent = HELP[kind];
    $('wbTextObjInput').value = text || EXAMPLES[kind][0][1];
    $('wbTextObjSave').textContent = textOptions.creating ? 'Placer sur le tableau' : 'Enregistrer';
    var box = $('wbTextObjExamples');
    box.replaceChildren.apply(box, EXAMPLES[kind].map(function (ex) {
      var b = document.createElement('button'); b.type = 'button'; b.className = 'wb-plot-snippet'; b.textContent = 'Exemple : ' + ex[0];
      b.addEventListener('click', function () { $('wbTextObjInput').value = ex[1]; textPreview(); });
      return b;
    }));
    textDialog.showModal();
    textPreview();
    $('wbTextObjInput').focus();
  }

  window.EduBacPlotEditor = { openPlot: openPlot, openText: openText };
})();
