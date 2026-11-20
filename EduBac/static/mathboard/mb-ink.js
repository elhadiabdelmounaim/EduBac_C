/* Tableau mathématique — écriture manuscrite (sans IA générative).
 *
 *  - Lasso : sélection à main levée des seuls éléments entourés.
 *  - Formes : un trait libre devient une forme propre (segment, cercle, ellipse,
 *    triangle, rectangle, carré, polygone, flèche, angle) par analyse géométrique
 *    locale ; « Écriture originale » rend le tracé d'origine.
 *  - Gomme partielle : coupe les traits sous la gomme au lieu de les supprimer.
 *  - Conversion en texte / en formule : les tracés bruts (x, y, t) partent au
 *    serveur, qui interroge un moteur spécialisé de reconnaissance de
 *    l'écriture (MyScript) ; le résultat est relu, corrigé (MathLive pour les
 *    formules), puis accepté ou refusé. L'écriture d'origine est conservée.
 *
 * Les tracés bruts sont enregistrés par mb-board.js dans chaque trait (`ink`).
 */
(function (root) {
  'use strict';
  var MB = root.MB = root.MB || {};
  var $ = function (id) { return document.getElementById(id); };
  var config = JSON.parse($('mbConfig').textContent);
  var board, api, fabric;

  var ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿ]/;
  var TEXT_TYPES = ['i-text', 'textbox', 'text'];

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function uid() { return 'm' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
  // Modèle enregistré sans les champs gérés par le serveur (_by, _rev…).
  function cleanModel(model) {
    var out = {};
    Object.keys(model).forEach(function (k) { if (k.charAt(0) !== '_') out[k] = clone(model[k]); });
    return out;
  }

  /* =================== Géométrie des traits =================== */
  function modelOf(obj) { return obj && obj.id && board.page().objects[obj.id]; }
  function isStroke(model) { return !!model && model.type === 'path' && !model.ink_shape; }

  // Points du trait en coordonnées de la scène (suivent déplacements et agrandissements).
  function strokePoints(obj, model) {
    var m = obj.calcTransformMatrix(), off = obj.pathOffset || { x: 0, y: 0 };
    function scene(x, y) { return fabric.util.transformPoint(new fabric.Point(x - off.x, y - off.y), m); }
    if (model.ink && model.ink.x) {
      return model.ink.x.map(function (x, i) {
        var p = scene(x, model.ink.y[i]);
        return { x: p.x, y: p.y, t: model.ink.t ? model.ink.t[i] : i * 10 };
      });
    }
    var pts = [];
    (obj.path || []).forEach(function (cmd) {
      for (var i = 1; i + 1 < cmd.length; i += 2) {
        var p = scene(cmd[i], cmd[i + 1]);
        pts.push({ x: p.x, y: p.y, t: pts.length * 10 });
      }
    });
    return pts;
  }
  function objectPoints(obj, model) {
    if (model && model.type === 'path') return strokePoints(obj, model);
    return obj.getCoords().map(function (p) { return { x: p.x, y: p.y }; });
  }
  function length(pts) {
    var total = 0;
    for (var i = 1; i < pts.length; i++) total += dist(pts[i - 1], pts[i]);
    return total;
  }
  function bbox(pts) {
    var xs = pts.map(function (p) { return p.x; }), ys = pts.map(function (p) { return p.y; });
    var left = Math.min.apply(null, xs), top = Math.min.apply(null, ys);
    return { left: left, top: top, width: Math.max.apply(null, xs) - left, height: Math.max.apply(null, ys) - top };
  }
  function resample(pts, n) {
    var total = length(pts);
    if (pts.length < 2 || !total) return pts.slice();
    var step = total / (n - 1), out = [pts[0]], acc = 0, prev = pts[0];
    for (var i = 1; i < pts.length; i++) {
      var cur = pts[i], d = dist(prev, cur);
      while (acc + d >= step && out.length < n) {
        var r = (step - acc) / d;
        prev = { x: prev.x + r * (cur.x - prev.x), y: prev.y + r * (cur.y - prev.y) };
        out.push(prev);
        d = dist(prev, cur);
        acc = 0;
      }
      acc += d;
      prev = cur;
    }
    while (out.length < n) out.push(pts[pts.length - 1]);
    return out;
  }
  // Douglas-Peucker : sommets d'une ligne brisée.
  function simplify(pts, eps) {
    if (pts.length < 3) return pts.slice();
    var a = pts[0], b = pts[pts.length - 1], best = 0, index = 0;
    for (var i = 1; i < pts.length - 1; i++) {
      var d = segmentDistance(pts[i], a, b);
      if (d > best) { best = d; index = i; }
    }
    if (best <= eps) return [a, b];
    return simplify(pts.slice(0, index + 1), eps).slice(0, -1).concat(simplify(pts.slice(index), eps));
  }
  function segmentDistance(p, a, b) {
    var dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy;
    if (!len2) return dist(p, a);
    var t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
    return dist(p, { x: a.x + t * dx, y: a.y + t * dy });
  }
  function angleAt(a, b, c) {     // angle en b, en degrés
    var v1 = { x: a.x - b.x, y: a.y - b.y }, v2 = { x: c.x - b.x, y: c.y - b.y };
    var cos = (v1.x * v2.x + v1.y * v2.y) / ((Math.hypot(v1.x, v1.y) * Math.hypot(v2.x, v2.y)) || 1);
    return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
  }
  function inside(p, poly) {      // point dans un polygone (lancer de rayon)
    var hit = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var a = poly[i], b = poly[j];
      if ((a.y > p.y) !== (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) hit = !hit;
    }
    return hit;
  }
  // Sommets d'un contour fermé : les angles plats et les sommets trop proches sont fusionnés.
  function corners(loop, size) {
    var v = simplify(loop.concat([loop[0]]), 0.035 * length(loop.concat([loop[0]]))).slice(0, -1);
    var changed = true;
    while (changed && v.length > 3) {
      changed = false;
      for (var i = 0; i < v.length; i++) {
        var a = v[(i - 1 + v.length) % v.length], b = v[i], c = v[(i + 1) % v.length];
        if (dist(a, b) < 0.12 * size || angleAt(a, b, c) > 155) { v.splice(i, 1); changed = true; break; }
      }
    }
    return v;
  }

  /* =================== Reconnaissance des formes =================== */
  /* Renvoie { kind, … } ou null. Analyse géométrique, sans apprentissage. */
  function recognizeShape(raw) {
    if (!raw || raw.length < 4) return null;
    var L = length(raw), box = bbox(raw), size = Math.max(box.width, box.height);
    if (size < 12 || L < 20) return null;
    var pts = resample(raw, 72), first = pts[0], last = pts[pts.length - 1], chord = dist(first, last);

    if (chord / L > 0.94) {                                 // segment
      var a = first, b = last, ang = Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
      if (Math.abs(Math.abs(ang) - 90) < 6) b = { x: a.x, y: b.y };                       // vertical
      else if (Math.abs(ang) < 6 || Math.abs(Math.abs(ang) - 180) < 6) b = { x: b.x, y: a.y };  // horizontal
      return { kind: 'line', points: [a, b] };
    }

    if (chord < 0.22 * size) {                              // contour fermé
      var loop = pts.slice(0, -1);
      var cx = box.left + box.width / 2, cy = box.top + box.height / 2;
      var rx = Math.max(1, box.width / 2), ry = Math.max(1, box.height / 2);
      var err = loop.reduce(function (s, p) {
        return s + Math.abs(Math.sqrt(Math.pow((p.x - cx) / rx, 2) + Math.pow((p.y - cy) / ry, 2)) - 1);
      }, 0) / loop.length;
      var v = corners(loop, size);
      // Écart moyen au polygone des sommets comparé à l'écart moyen à l'ellipse :
      // des côtés droits (polygone) s'ajustent nettement mieux qu'une courbe.
      var polyErr = v.length >= 3 ? loop.reduce(function (s, p) {
        var best = Infinity;
        for (var i = 0; i < v.length; i++) best = Math.min(best, segmentDistance(p, v[i], v[(i + 1) % v.length]));
        return s + best;
      }, 0) / loop.length : Infinity;
      var ellErr = err * (rx + ry) / 2;
      var polygonLike = v.length >= 3 && v.length <= 8 && polyErr < 0.6 * ellErr;
      if (err < 0.09 && !polygonLike) {
        if (Math.abs(box.width - box.height) / size < 0.15) {
          var r = (box.width + box.height) / 4;
          return { kind: 'circle', cx: cx, cy: cy, r: r };
        }
        return { kind: 'ellipse', cx: cx, cy: cy, rx: rx, ry: ry };
      }
      if (v.length === 3) return { kind: 'triangle', points: v };
      if (v.length === 4) {
        var right = [0, 1, 2, 3].every(function (i) { return Math.abs(angleAt(v[(i + 3) % 4], v[i], v[(i + 1) % 4]) - 90) < 16; });
        var edge = Math.atan2(v[1].y - v[0].y, v[1].x - v[0].x) * 180 / Math.PI;
        var axis = Math.min(Math.abs(edge % 90), 90 - Math.abs(edge % 90)) < 12;
        if (right && axis) {
          var q = bbox(v);
          if (Math.abs(q.width - q.height) / Math.max(q.width, q.height) < 0.12) {
            var side = (q.width + q.height) / 2;
            return { kind: 'square', left: q.left, top: q.top, width: side, height: side };
          }
          return { kind: 'rectangle', left: q.left, top: q.top, width: q.width, height: q.height };
        }
        return { kind: 'polygon', points: v };
      }
      if (polygonLike) return { kind: 'polygon', points: v };
      return null;
    }

    // Trait ouvert : flèche (corps puis pointe) ou angle (deux côtés).
    var open = simplify(pts, 0.04 * L);
    if (open.length >= 4) {
      var shaft = dist(open[0], open[1]);
      var head = open.slice(2), tip = open[1];
      var dir = { x: (tip.x - open[0].x) / shaft, y: (tip.y - open[0].y) / shaft };
      var behind = head.every(function (p) {
        return dist(p, tip) < 0.45 * shaft && ((p.x - tip.x) * dir.x + (p.y - tip.y) * dir.y) < 0.15 * shaft;
      });
      if (shaft > 0.45 * L && behind) return { kind: 'arrow', points: [open[0], tip] };
    }
    if (open.length === 3) {
      var s1 = dist(open[0], open[1]), s2 = dist(open[1], open[2]), deg = angleAt(open[0], open[1], open[2]);
      if (s1 > 0.2 * L && s2 > 0.2 * L && deg > 12 && deg < 165) return { kind: 'angle', points: open };
    }
    return null;
  }
  // Flèche dessinée en deux traits : un segment et une pointe en « V » à une extrémité.
  function recognizeArrowPair(a, b) {
    function tryPair(line, vee) {
      var s = recognizeShape(line);
      if (!s || s.kind !== 'line') return null;
      var v = simplify(resample(vee, 40), 0.06 * length(vee));
      if (v.length !== 3) return null;
      var apex = v[1], ends = s.points, shaft = dist(ends[0], ends[1]);
      var far = dist(apex, ends[1]) < dist(apex, ends[0]) ? ends : [ends[1], ends[0]];
      if (dist(apex, far[1]) > 0.25 * shaft || dist(v[0], apex) > 0.6 * shaft) return null;
      return { kind: 'arrow', points: [far[0], far[1]] };
    }
    return tryPair(a, b) || tryPair(b, a);
  }

  function arrowPath(a, b, head) {
    var ang = Math.atan2(b.y - a.y, b.x - a.x), a1 = ang + Math.PI - 0.45, a2 = ang + Math.PI + 0.45;
    return 'M ' + a.x + ' ' + a.y + ' L ' + b.x + ' ' + b.y + ' M ' + (b.x + head * Math.cos(a1)) + ' ' + (b.y + head * Math.sin(a1)) +
      ' L ' + b.x + ' ' + b.y + ' L ' + (b.x + head * Math.cos(a2)) + ' ' + (b.y + head * Math.sin(a2));
  }
  function polyPath(points, closed) {
    return points.map(function (p, i) { return (i ? 'L ' : 'M ') + p.x + ' ' + p.y; }).join(' ') + (closed ? ' Z' : '');
  }
  function anglePath(p) {     // deux côtés + petit arc au sommet
    var o = p[1], r = Math.min(dist(o, p[0]), dist(o, p[2])) * 0.25;
    var a1 = Math.atan2(p[0].y - o.y, p[0].x - o.x), a2 = Math.atan2(p[2].y - o.y, p[2].x - o.x);
    var delta = a2 - a1;
    while (delta > Math.PI) delta -= 2 * Math.PI;
    while (delta < -Math.PI) delta += 2 * Math.PI;
    var s = { x: o.x + r * Math.cos(a1), y: o.y + r * Math.sin(a1) }, e = { x: o.x + r * Math.cos(a2), y: o.y + r * Math.sin(a2) };
    return polyPath(p, false) + ' M ' + s.x + ' ' + s.y + ' A ' + r + ' ' + r + ' 0 0 ' + (delta > 0 ? 1 : 0) + ' ' + e.x + ' ' + e.y;
  }
  // Objet Fabric de la forme, au style du trait d'origine.
  function shapeObject(shape, style) {
    var common = { stroke: style.color, strokeWidth: style.width, fill: 'transparent', strokeUniform: true,
      strokeLineCap: 'round', strokeLineJoin: 'round' };
    switch (shape.kind) {
      case 'line': return new fabric.Line([shape.points[0].x, shape.points[0].y, shape.points[1].x, shape.points[1].y], common);
      case 'circle': return new fabric.Circle(Object.assign({ left: shape.cx - shape.r, top: shape.cy - shape.r, radius: shape.r }, common));
      case 'ellipse': return new fabric.Ellipse(Object.assign({ left: shape.cx - shape.rx, top: shape.cy - shape.ry, rx: shape.rx, ry: shape.ry }, common));
      case 'rectangle':
      case 'square': return new fabric.Rect(Object.assign({ left: shape.left, top: shape.top, width: shape.width, height: shape.height }, common));
      case 'triangle':
      case 'polygon': return new fabric.Path(polyPath(shape.points, true), common);
      case 'arrow': return new fabric.Path(arrowPath(shape.points[0], shape.points[1], Math.max(10, style.width * 4)), Object.assign({}, common, { fill: '' }));
      case 'angle': return new fabric.Path(anglePath(shape.points), Object.assign({}, common, { fill: '' }));
    }
    return null;
  }
  function styleOf(model) {
    return { color: model.stroke || model.fill || '#212529', width: (model.ink && model.ink.width) || model.strokeWidth || 3 };
  }
  var SHAPE_NAMES = { line: 'segment', circle: 'cercle', ellipse: 'ellipse', triangle: 'triangle', rectangle: 'rectangle',
    square: 'carré', polygon: 'polygone', arrow: 'flèche', angle: 'angle' };

  /* =================== Actions =================== */
  var Ink = {
    selection: [],

    /* ---------- Formes ---------- */
    toShapes: function (objects, quiet) {
      var page = board.page(), strokes = (objects || board.selected()).filter(function (o) {
        var m = modelOf(o); return isStroke(m) && board.owns(m);
      });
      if (!strokes.length) return 0;
      var found = [];
      if (strokes.length === 2) {
        var pair = recognizeArrowPair(strokePoints(strokes[0], modelOf(strokes[0])), strokePoints(strokes[1], modelOf(strokes[1])));
        if (pair) found.push({ shape: pair, sources: strokes });
      }
      if (!found.length) {
        strokes.forEach(function (o) {
          var shape = recognizeShape(strokePoints(o, modelOf(o)));
          if (shape) found.push({ shape: shape, sources: [o] });
        });
      }
      if (!found.length) { if (!quiet) board.ui.toast('Aucune forme reconnue : redessinez plus nettement.'); return 0; }
      var ops = [], inverse = [];
      board.canvas.discardActiveObject();
      found.forEach(function (f) {
        var origin = modelOf(f.sources[0]), obj = shapeObject(f.shape, styleOf(origin));
        var model = R().fromFabric(obj);
        model.id = uid(); model.z = origin.z || board.nextZ();
        model.ink_shape = f.shape.kind;
        model.ink_source = f.sources.map(function (o) { return cleanModel(page.objects[o.id]); });
        ops.push({ kind: 'object.add', object: model });
        inverse.unshift({ kind: 'object.delete', id: model.id });
        f.sources.forEach(function (o) {
          ops.push({ kind: 'object.delete', id: o.id });
          inverse.push({ kind: 'object.add', object: clone(page.objects[o.id]) });
        });
      });
      board.perform(ops, inverse);
      if (!quiet) {
        board.ui.toast(found.length === 1 ? 'Forme reconnue : ' + SHAPE_NAMES[found[0].shape.kind] + '. « Écriture originale » rend le tracé.'
          : found.length + ' formes reconnues.');
      }
      return found.length;
    },

    // Rend les traits d'origine d'une forme ou d'un texte / d'une formule convertis.
    restore: function () {
      var page = board.page(), objects = board.selected().filter(function (o) {
        var m = modelOf(o); return m && m.ink_source && board.owns(m);
      });
      if (!objects.length) return;
      var ops = [], inverse = [];
      board.canvas.discardActiveObject();
      objects.forEach(function (o) {
        var model = page.objects[o.id];
        ops.push({ kind: 'object.delete', id: o.id });
        model.ink_source.forEach(function (source) {
          var copy = clone(source);
          if (page.objects[copy.id]) copy.id = uid();
          ops.push({ kind: 'object.add', object: copy });
          inverse.unshift({ kind: 'object.delete', id: copy.id });
        });
        inverse.push({ kind: 'object.add', object: clone(model) });
      });
      board.perform(ops, inverse);
      board.ui.toast('Écriture originale rétablie.');
    },

    resize: function (factor) {
      var active = board.canvas.getActiveObject();
      if (!active) return;
      active.set({ scaleX: active.scaleX * factor, scaleY: active.scaleY * factor });
      active.setCoords();
      if (active.type === 'activeselection' || active.type === 'ActiveSelection') board._withSelection(function (objs) { board._modified(objs); });
      else board._modified([active]);
      board.canvas.requestRenderAll();
    },

    /* ---------- Gomme partielle ---------- */
    erasePartial: function (point, state) {
      var canvas = board.canvas, page = board.page(), r = 9 / canvas.getZoom();
      canvas.getObjects().slice().forEach(function (obj) {
        var model = modelOf(obj);
        if (!isStroke(model) || !board.owns(model)) return;
        var rect = obj.getBoundingRect();
        if (point.x < rect.left - r || point.x > rect.left + rect.width + r || point.y < rect.top - r || point.y > rect.top + rect.height + r) return;
        // Trait à pression sans tracé brut : seul son contour est connu, il est effacé en entier.
        if (!model.ink && !model.stroke) { removeWhole(obj, model, state); return; }
        var pts = densify(strokePoints(obj, model), r / 2);
        if (!pts.some(function (p) { return dist(p, point) < r; })) return;
        var pieces = [], run = [];
        pts.forEach(function (p) {
          if (dist(p, point) < r) { if (run.length) pieces.push(run); run = []; } else run.push(p);
        });
        if (run.length) pieces.push(run);
        removeWhole(obj, model, state);
        var style = styleOf(model);
        pieces.filter(function (piece) { return piece.length >= 2 && length(piece) > 2 / canvas.getZoom(); }).forEach(function (piece) {
          var path = new fabric.Path(fabric.util.getSmoothPathFromPoints(piece.map(function (p) { return new fabric.Point(p.x, p.y); })), {
            stroke: style.color, strokeWidth: style.width, fill: null, strokeLineCap: 'round', strokeLineJoin: 'round', opacity: model.opacity == null ? 1 : model.opacity });
          path.set({ id: uid(), z: model.z || 0 });
          var piece_model = R().fromFabric(path);
          var ink = MB.inkData(piece);
          if (ink) { ink.width = style.width; piece_model.ink = ink; }
          var op = { kind: 'object.add', object: piece_model, page: board.pageUid };
          state.ops.push(op);
          state.inverse.unshift({ kind: 'object.delete', id: piece_model.id });
          board._applyToMirror({ kind: 'object.add', page: board.pageUid, object: Object.assign(clone(piece_model), { _by: board.me }) });
          board._permissions(path);
          board.byId[path.id] = path;
          canvas.add(path);
        });
        board._sortZ();
      });
      canvas.requestRenderAll();
    },

    /* ---------- Conversion en texte / formule ---------- */
    convert: function (kind) {
      var objects = board.selected().filter(function (o) { return isStroke(modelOf(o)); });
      if (!objects.length) { board.ui.toast('Sélectionnez des traits écrits à la main.', 'error'); return; }
      this.objects = objects;
      this.kind = kind;
      var all = [];
      this.strokes = objects.map(function (o) {
        var pts = strokePoints(o, modelOf(o));
        all = all.concat(pts);
        return pts;
      });
      this.bounds = bbox(all);
      this.color = styleOf(modelOf(objects[0])).color;
      $('mbConvTitle').textContent = kind === 'math' ? 'Convertir en formule' : 'Convertir en texte';
      $('mbConvTextRow').hidden = kind !== 'text';
      $('mbConvMathRow').hidden = kind !== 'math';
      $('mbConvLangRow').hidden = kind !== 'text';
      $('mbConvReplace').checked = false;
      $('mbConvDialog').showModal();
      this.recognize();
    },
    recognize: function () {
      var self = this, b = this.bounds;
      $('mbConvError').textContent = '';
      $('mbConvStatus').hidden = false;
      $('mbConvAccept').disabled = true;
      $('mbConvText').value = '';
      $('mbConvMath').value = '';
      var strokes = this.strokes.map(function (pts) {
        return { x: pts.map(function (p) { return Math.round((p.x - b.left) * 10) / 10; }),
          y: pts.map(function (p) { return Math.round((p.y - b.top) * 10) / 10; }),
          t: pts.map(function (p, i) { return Math.round(p.t == null ? i * 10 : p.t); }) };
      });
      api('POST', config.urls.recognition, { kind: this.kind, lang: $('mbConvLang').value, strokes: strokes,
        width: Math.ceil(b.width), height: Math.ceil(b.height) }).then(function (data) {
        if (self.kind === 'math') $('mbConvMath').value = data.latex || '';
        else { $('mbConvText').value = data.text || ''; $('mbConvText').dir = ARABIC.test(data.text || '') ? 'rtl' : 'ltr'; }
        $('mbConvAccept').disabled = false;
      }).catch(function (e) {
        $('mbConvError').textContent = e.message || 'Reconnaissance impossible.';
      }).finally(function () { $('mbConvStatus').hidden = true; });
    },
    accept: function () {
      var page = board.page(), b = this.bounds, replace = $('mbConvReplace').checked, model;
      var top = replace ? b.top : b.top + b.height + 16;
      if (this.kind === 'math') {
        var latex = $('mbConvMath').value.trim();
        if (!latex) { $('mbConvError').textContent = 'La formule est vide.'; return; }
        model = { type: 'math', latex: latex, color: this.color, fontSize: Math.round(Math.max(18, Math.min(48, b.height * 0.45))),
          left: b.left, top: top };
      } else {
        var text = $('mbConvText').value.replace(/\s+$/, '');
        if (!text.trim()) { $('mbConvError').textContent = 'Le texte est vide.'; return; }
        var rtl = ARABIC.test(text.replace(/[^A-Za-zÀ-ɏ؀-ۿ]/g, '').charAt(0));
        var lines = Math.max(1, text.split('\n').length);
        model = { type: 'i-text', text: text, fill: this.color, fontFamily: $('mbConvFont').value,
          fontSize: Number($('mbConvSize').value) || Math.round(Math.max(16, Math.min(48, b.height / lines * 0.7))),
          left: b.left, top: top };
        if (rtl) {
          var probe = new fabric.IText(text, { fontSize: model.fontSize, fontFamily: model.fontFamily });
          Object.assign(model, { direction: 'rtl', textAlign: 'right', left: Math.max(b.left, b.left + b.width - probe.width) });
        }
      }
      model.id = uid();
      model.z = board.nextZ();
      var ops = [{ kind: 'object.add', object: model }], inverse = [{ kind: 'object.delete', id: model.id }];
      if (replace) {
        // Remplacement confirmé par la case à cocher ; l'écriture reste récupérable.
        model.ink_source = this.objects.filter(function (o) { return board.owns(modelOf(o)); })
          .map(function (o) { return cleanModel(page.objects[o.id]); });
        board.canvas.discardActiveObject();
        this.objects.forEach(function (o) {
          if (!board.owns(modelOf(o))) return;
          ops.push({ kind: 'object.delete', id: o.id });
          inverse.push({ kind: 'object.add', object: clone(page.objects[o.id]) });
        });
      }
      $('mbConvDialog').close();
      board.perform(ops, inverse).then(function () {
        board.ui.toast(replace ? 'Converti. « Écriture originale » rend le tracé.' : 'Converti : l’écriture originale est conservée.');
      });
    },

    /* ---------- Barre de sélection ---------- */
    selectionState: function (objects) {
      var models = objects.map(modelOf);
      return {
        strokes: board.canEdit() && models.some(isStroke),
        restore: board.canEdit() && models.some(function (m) { return m && m.ink_source; }),
        recognition: !!config.recognition,
      };
    },
    action: function (act) {
      if (act === 'shape') return this.toShapes(), true;
      if (act === 'restore') return this.restore(), true;
      if (act === 'to-text') return this.convert('text'), true;
      if (act === 'to-math') return this.convert('math'), true;
      if (act === 'bigger') return this.resize(1.2), true;
      if (act === 'smaller') return this.resize(1 / 1.2), true;
      return false;
    },
  };

  function removeWhole(obj, model, state) {
    state.ops.push({ kind: 'object.delete', id: obj.id, page: board.pageUid });
    state.inverse.unshift({ kind: 'object.add', object: clone(model) });
    board._applyToMirror({ kind: 'object.delete', id: obj.id, page: board.pageUid });
    board.canvas.remove(obj);
    delete board.byId[obj.id];
  }
  function densify(pts, step) {
    var out = [];
    pts.forEach(function (p, i) {
      if (i) {
        var prev = pts[i - 1], d = dist(prev, p), n = Math.floor(d / step);
        for (var k = 1; k < n; k++) out.push({ x: prev.x + (p.x - prev.x) * k / n, y: prev.y + (p.y - prev.y) * k / n, t: prev.t + (p.t - prev.t) * k / n });
      }
      out.push(p);
    });
    return out;
  }
  function R() { return MB.Render; }

  /* =================== Lasso =================== */
  var lasso = {
    points: null,
    down: function (point) { this.points = [point]; this.draw(); },
    move: function (point) {
      if (!this.points) return;
      var last = this.points[this.points.length - 1];
      if (dist(last, point) * board.canvas.getZoom() < 3) return;
      this.points.push(point);
      this.draw();
    },
    draw: function () {
      var canvas = board.canvas, ctx = canvas.contextTop, v = canvas.viewportTransform, pts = this.points;
      canvas.clearContext(ctx);
      if (!pts || pts.length < 2) return;
      ctx.save();
      ctx.transform(v[0], v[1], v[2], v[3], v[4], v[5]);
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      pts.forEach(function (p) { ctx.lineTo(p.x, p.y); });
      ctx.closePath();
      ctx.fillStyle = 'rgba(25, 113, 194, 0.08)';
      ctx.fill();
      ctx.setLineDash([6 / v[0], 4 / v[0]]);
      ctx.lineWidth = 1.5 / v[0];
      ctx.strokeStyle = '#1971c2';
      ctx.stroke();
      ctx.restore();
    },
    up: function () {
      var poly = this.points, canvas = board.canvas;
      this.points = null;
      canvas.clearContext(canvas.contextTop);
      if (!poly || poly.length < 3 || length(poly) * canvas.getZoom() < 20) return;
      var chosen = canvas.getObjects().filter(function (obj) {
        var model = modelOf(obj);
        if (!model || !board.owns(model)) return false;
        var pts = objectPoints(obj, model);
        if (!pts.length) return false;
        if (model.type === 'path') {
          var sample = pts.length > 80 ? pts.filter(function (p, i) { return i % Math.ceil(pts.length / 80) === 0; }) : pts;
          return sample.filter(function (p) { return inside(p, poly); }).length >= 0.6 * sample.length;
        }
        var center = obj.getCenterPoint();
        return inside(center, poly) && pts.filter(function (p) { return inside(p, poly); }).length >= 3;
      });
      board.setTool('select');
      if (!chosen.length) { board.ui.toast('Aucun élément entouré.'); return; }
      if (chosen.length === 1) canvas.setActiveObject(chosen[0]);
      else canvas.setActiveObject(new fabric.ActiveSelection(chosen, { canvas: canvas }));
      canvas.requestRenderAll();
      board.ui.selection(board.selected(), board);
    },
    cancel: function () { this.points = null; board.canvas.clearContext(board.canvas.contextTop); },
  };

  /* =================== Options des outils =================== */
  function toolOptions(tool) {
    var bar = $('mbToolOptions');
    if (!bar) return;
    bar.querySelectorAll('[data-for]').forEach(function (el) { el.hidden = el.dataset.for !== tool; });
    bar.hidden = !board.canEdit() || !bar.querySelector('[data-for="' + tool + '"]');
  }

  document.addEventListener('DOMContentLoaded', function () {
    board = MB.board; api = MB.Panels.api; fabric = root.fabric;
    MB.Ink = Ink;
    Ink.recognizeShape = recognizeShape;   // tests
    board.toolHandlers = board.toolHandlers || {};
    board.toolHandlers.lasso = lasso;

    // Formes automatiques : chaque trait reconnu devient une forme (Ctrl+Z rend le trait).
    try { board.autoShapes = localStorage.getItem('mathboard:autoShapes') === '1'; } catch (e) { board.autoShapes = false; }
    board.onStroke = function (path) {
      if (!board.autoShapes || board.tool !== 'pen') return;
      var model = modelOf(path);
      if (model && model.ink && Math.max(path.width, path.height) >= 40) Ink.toShapes([path], true);
    };

    var ui = board.ui, originalTool = ui.tool;
    ui.tool = function (tool) { originalTool.call(ui, tool); toolOptions(tool); };
    toolOptions(board.tool);
    var auto = $('mbAutoShapes');
    if (auto) {
      auto.checked = board.autoShapes;
      auto.addEventListener('change', function () {
        board.autoShapes = this.checked;
        try { localStorage.setItem('mathboard:autoShapes', this.checked ? '1' : '0'); } catch (e) { /* stockage indisponible */ }
      });
    }
    document.querySelectorAll('input[name="mbEraserMode"]').forEach(function (input) {
      input.addEventListener('change', function () { if (this.checked) board.eraserMode = this.value; });
    });

    if ($('mbConvDialog')) {
      $('mbConvAccept').addEventListener('click', function () { Ink.accept(); });
      $('mbConvReject').addEventListener('click', function () { $('mbConvDialog').close(); });
      $('mbConvRetry').addEventListener('click', function () { Ink.recognize(); });
      $('mbConvLang').addEventListener('change', function () {
        try { localStorage.setItem('mathboard:inkLang', this.value); } catch (e) { /* stockage indisponible */ }
        Ink.recognize();
      });
      try { var lang = localStorage.getItem('mathboard:inkLang'); if (lang) $('mbConvLang').value = lang; } catch (e) { /* idem */ }
      $('mbConvText').addEventListener('input', function () { this.dir = ARABIC.test(this.value.trim().charAt(0)) ? 'rtl' : 'ltr'; });
    }
  });
})(window);
