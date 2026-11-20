/* Tableau mathématique — écriture manuscrite → texte et formules.
 *
 * Le professeur sélectionne ses traits au stylet, clique sur « Convertir » :
 * une image des seuls traits sélectionnés (fond blanc) part au serveur, qui
 * renvoie des lignes de segments { kind: 'text' | 'math', content }. Le résultat
 * s'affiche dans un champ modifiable, une ligne par ligne du tableau, les
 * formules entre \( et \) ; l'aperçu se met à jour pendant la correction.
 * « Insérer » remplace (ou complète) les traits par du texte et des formules,
 * en une seule action annulable.
 */
(function (root) {
  'use strict';
  var MB = root.MB = root.MB || {};
  var $ = function (id) { return document.getElementById(id); };
  var config = JSON.parse($('mbConfig').textContent);
  var board, api, R;

  var ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿ]/;
  var PAD = 16, MAX_SIDE = 1568;

  function esc(text) { var d = document.createElement('div'); d.textContent = text == null ? '' : String(text); return d.innerHTML; }
  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  /* ---------- Lignes ↔ texte modifiable ---------- */
  function toSource(lines) {
    return lines.map(function (line) {
      return line.segments.map(function (s) { return s.kind === 'math' ? '\\(' + s.content + '\\)' : s.content; }).join(' ');
    }).join('\n');
  }
  function parse(source) {
    return source.split('\n').map(function (row) {
      var segments = [], re = /\\\(([\s\S]*?)\\\)/g, last = 0, m;
      while ((m = re.exec(row))) {
        if (m.index > last) segments.push({ kind: 'text', content: row.slice(last, m.index) });
        if (m[1].trim()) segments.push({ kind: 'math', content: m[1].trim() });
        last = re.lastIndex;
      }
      if (last < row.length) segments.push({ kind: 'text', content: row.slice(last) });
      segments = segments.map(function (s) { return s.kind === 'text' ? { kind: 'text', content: s.content.replace(/\s+/g, ' ') } : s; })
        .filter(function (s) { return s.kind === 'math' || s.content.trim(); });
      return { segments: segments };
    }).filter(function (line) { return line.segments.length; });
  }
  function rtl(line) {
    var first = line.segments.filter(function (s) { return s.kind === 'text'; })[0];
    return !!(first && ARABIC.test(first.content));
  }
  // \text{…} : MathJax l'affiche tel quel ; seuls les accolades et antislashs
  // (qui fermeraient ou ouvriraient une commande) sont retirés.
  function texText(text) {
    return '\\text{' + text.replace(/[\\{}]/g, '') + '}';
  }
  // Une ligne mêlant texte et formules devient une seule formule ; en arabe
  // (droite à gauche), les segments sont placés dans l'ordre inverse.
  function lineLatex(line) {
    var parts = line.segments.map(function (s) { return s.kind === 'math' ? s.content : texText(' ' + s.content.trim() + ' '); });
    if (rtl(line)) parts.reverse();
    return parts.join(' ');
  }

  /* ---------- Image des traits sélectionnés ---------- */
  function strokes() {
    var page = board.page();
    return board.selected().filter(function (o) { var m = o.id && page.objects[o.id]; return m && m.type === 'path'; });
  }
  function capture(objects) {
    var fabric = root.fabric, canvas = board.canvas;
    canvas.discardActiveObject();                       // coordonnées absolues
    var b = board.bounds(objects);
    var scale = Math.min(2, MAX_SIDE / (Math.max(b.width, b.height) + 2 * PAD));
    var w = Math.ceil((b.width + 2 * PAD) * scale), h = Math.ceil((b.height + 2 * PAD) * scale);
    return Promise.all(objects.map(function (o) { return o.clone(); })).then(function (copies) {
      var el = document.createElement('canvas');
      var out = new fabric.StaticCanvas(el, { width: w, height: h, backgroundColor: '#ffffff', enableRetinaScaling: false, renderOnAddRemove: false });
      out.setViewportTransform([scale, 0, 0, scale, (PAD - b.left) * scale, (PAD - b.top) * scale]);
      copies.forEach(function (c) { c.set({ stroke: '#000000', shadow: null, opacity: 1 }); out.add(c); });
      out.renderAll();
      var url = out.toDataURL({ format: 'png' });
      out.dispose();
      return { url: url, bounds: b };
    }).finally(function () {
      if (objects.length > 1) canvas.setActiveObject(new fabric.ActiveSelection(objects, { canvas: canvas }));
      else canvas.setActiveObject(objects[0]);
      canvas.requestRenderAll();
    });
  }

  /* ---------- Dialogue ---------- */
  var Ink = {
    objects: [], bounds: null, busy: false,

    available: function (objects) {
      if (!config.handwriting || !board.canEdit()) return false;
      var page = board.page();
      return objects.some(function (o) { var m = o.id && page.objects[o.id]; return m && m.type === 'path'; });
    },

    open: function () {
      if (this.busy) return;
      var objects = strokes();
      if (!objects.length) { board.ui.toast('Sélectionnez des traits écrits au stylet.', 'error'); return; }
      var self = this;
      this.busy = true;
      this.objects = objects;
      $('mbInkSource').value = '';
      $('mbInkPreview').innerHTML = '';
      $('mbInkError').textContent = '';
      $('mbInkInsert').disabled = true;
      $('mbInkStatus').hidden = false;
      $('mbInkDialog').showModal();
      capture(objects).then(function (shot) {
        self.bounds = shot.bounds;
        return api('POST', config.urls.handwriting, { image: shot.url });
      }).then(function (data) {
        $('mbInkSource').value = toSource(data.lines || []);
        self.preview();
        $('mbInkInsert').disabled = false;
        $('mbInkSource').focus();
      }).catch(function (e) {
        $('mbInkError').textContent = e.message || 'Conversion impossible.';
      }).finally(function () {
        self.busy = false;
        $('mbInkStatus').hidden = true;
      });
    },

    preview: function () {
      var box = $('mbInkPreview'), lines = parse($('mbInkSource').value);
      box.innerHTML = '';
      lines.forEach(function (line) {
        var row = document.createElement('div');
        row.className = 'mb-ink-line';
        row.dir = rtl(line) ? 'rtl' : 'ltr';
        line.segments.forEach(function (s) {
          var el = document.createElement('span');
          if (s.kind === 'text') { el.textContent = s.content; row.appendChild(el); return; }
          el.className = 'mb-ink-math';
          el.textContent = s.content;
          row.appendChild(el);
          R.latexToSvg(s.content, '#1f2937', 18).then(function (out) {
            el.innerHTML = '<img alt="" src="' + R.svgDataUrl(out.svg) + '">';
            el.querySelector('img').alt = s.content;
          }).catch(function () { el.classList.add('is-invalid'); el.title = 'Formule à corriger'; });
        });
        box.appendChild(row);
      });
      $('mbInkInsert').disabled = !lines.length;
    },

    insert: function () {
      var lines = parse($('mbInkSource').value);
      if (!lines.length) return;
      var self = this, page = board.page(), b = this.bounds || board.bounds(this.objects), replace = $('mbInkReplace').checked;
      var size = Math.round(Math.max(18, Math.min(44, b.height / lines.length * 0.5)));
      var top = replace ? b.top : b.top + b.height + 24, right = b.left + b.width, z = board.nextZ(), fabric = root.fabric;
      // Lignes en arabe : alignées à droite des traits (largeur mesurée avant l'ajout,
      // pour que toute la conversion tienne en une seule action annulable).
      var models = lines.map(function (line) {
        var isRtl = rtl(line), id = 'm' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8), model;
        if (line.segments.every(function (s) { return s.kind === 'text'; })) {
          var text = line.segments.map(function (s) { return s.content.trim(); }).join(' ');
          model = { id: id, type: 'i-text', text: text, fontSize: size, fill: '#212529', fontFamily: 'system-ui, sans-serif',
            left: b.left, top: top, z: z++ };
          if (isRtl) {
            var probe = new fabric.IText(text, { fontSize: size, fontFamily: model.fontFamily });
            model.direction = 'rtl'; model.textAlign = 'right'; model.left = Math.max(b.left, right - probe.width);
          }
          top += size * 1.5;
          return Promise.resolve(model);
        }
        model = { id: id, type: 'math', latex: lineLatex(line), color: '#212529', fontSize: size, left: b.left, top: top, z: z++ };
        top += size * 1.9;
        if (!isRtl) return Promise.resolve(model);
        return R.latexToSvg(model.latex, model.color, size).then(function (out) {
          model.left = Math.max(b.left, right - out.width);
          return model;
        }).catch(function () { return model; });
      });
      $('mbInkInsert').disabled = true;
      Promise.all(models).then(function (added) {
        var ops = [], inverse = [];
        added.forEach(function (model) {
          ops.push({ kind: 'object.add', object: model });
          inverse.push({ kind: 'object.delete', id: model.id });
        });
        if (replace) {
          self.objects.forEach(function (o) {
            var m = page.objects[o.id];
            if (!m || !board.owns(m)) return;
            ops.push({ kind: 'object.delete', id: o.id });
            inverse.push({ kind: 'object.add', object: clone(m) });
          });
          board.canvas.discardActiveObject();
        }
        $('mbInkDialog').close();
        return board.perform(ops, inverse);
      }).then(function () {
        board.canvas.requestRenderAll();
        board.ui.toast('Écriture convertie. Pour l’envoyer aux élèves : « Partager » ou « Présenter ».');
      }).catch(function (e) {
        $('mbInkInsert').disabled = false;
        $('mbInkError').textContent = e.message || 'Insertion impossible.';
      });
    },
  };

  document.addEventListener('DOMContentLoaded', function () {
    board = MB.board; api = MB.Panels.api; R = MB.Render;
    MB.Ink = Ink;
    if (!$('mbInkDialog')) return;
    var timer;
    $('mbInkSource').addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { Ink.preview(); }, 300); });
    $('mbInkInsert').addEventListener('click', function () { Ink.insert(); });
    $('mbInkCancel').addEventListener('click', function () { $('mbInkDialog').close(); });
  });
})(window);
