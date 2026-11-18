/**
 * EduBac — repère interactif (objet « plot » du tableau blanc).
 *
 * Un repère est un élément ordinaire du tableau :
 *   {type:'plot', x, y, w, h, title, view:{xmin,xmax,ymin,ymax}, home:{…},
 *    opts:{grid, axes, ortho, pi, complex}, items:[{id, line, color, hidden, val}]}
 * Chaque item est une commande texte (« f(x)=x^2-2 », « A=(1;2) »,
 * « a=Curseur(-5;5;0,1) », « T=Tangente(f;A) »…). Déplacer un point ou un
 * curseur réécrit la commande : l'état reste du texte, synchronisé comme le reste.
 */
(function (root, factory) {
  var api = factory(root.EduBacMath || (typeof require === 'function' ? require('./whiteboard-math.js') : null));
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EduBacPlot = api;
})(typeof window !== 'undefined' ? window : globalThis, function (M) {
  'use strict';
  var fail = function (m) { throw new M.MathError(m); };
  var HEADER = 30;
  var PALETTE = ['#1d4fa3', '#d9480f', '#2b8a3e', '#7048e8', '#c2255c', '#0b7285', '#e67700', '#495057'];

  /* ------------------------------------------------------------------ outils */
  function strip(s) { return String(s).normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase(); }
  function splitArgs(src) {
    var out = [], depth = 0, cur = '', quote = false;
    for (var i = 0; i < src.length; i++) {
      var c = src[i];
      if (c === '"') quote = !quote;
      if (!quote && (c === '(' || c === '[')) depth++;
      if (!quote && (c === ')' || c === ']')) depth--;
      if (!quote && depth === 0 && (c === ',' || c === ';')) { out.push(cur.trim()); cur = ''; continue; }
      cur += c;
    }
    if (cur.trim() || out.length) out.push(cur.trim());
    return out;
  }
  function isNumberLiteral(s) { return /^-?\s*(\d+\.?\d*|\.\d+)$/.test(String(s).trim()); }
  function round(v, d) { var k = Math.pow(10, d == null ? 2 : d); return Math.round(v * k) / k; }
  function numText(v) { return String(round(v, 2)); }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }

  /* ------------------------------------------------------------- commandes */
  var COMMANDS = {
    curseur: 'slider', slider: 'slider',
    point: 'point', milieu: 'midpoint', midpoint: 'midpoint',
    droite: 'line', line: 'line', segment: 'segment', demidroite: 'ray', ray: 'ray',
    vecteur: 'vector', vector: 'vector', cercle: 'circle', circle: 'circle',
    polygone: 'polygon', polygon: 'polygon',
    perpendiculaire: 'perp', perpendicular: 'perp', parallele: 'parallel', parallel: 'parallel',
    mediatrice: 'bisector', bissectrice: 'anglebisector',
    intersection: 'intersect', intersect: 'intersect',
    racines: 'roots', racine: 'roots', zeros: 'roots', roots: 'roots',
    extremums: 'extrema', extremum: 'extrema', extrema: 'extrema',
    asymptotes: 'asymptotes', asymptote: 'asymptotes',
    tangente: 'tangent', tangent: 'tangent', derivee: 'derivative', derivative: 'derivative',
    integrale: 'integral', integral: 'integral', aire: 'area', area: 'area',
    distance: 'distance', longueur: 'distance', angle: 'angle',
    translation: 'translate', symetrie: 'reflect', reflect: 'reflect', homothetie: 'dilate', dilate: 'dilate',
    rotation: 'rotate', rotate: 'rotate', barycentre: 'barycenter', barycenter: 'barycenter',
    lieu: 'locus', locus: 'locus', trace: 'trace',
    cercletrigo: 'trig', cercletrigonometrique: 'trig', unitcircle: 'trig',
    suite: 'sequence', sequence: 'sequence', complexe: 'complex', complex: 'complex',
    placer: 'target', exercice: 'target', texte: 'text', text: 'text', fonction: 'function', function: 'function',
  };

  /** Analyse une ligne : {name, kind:'fn'|'cmd'|'pair'|'num', …}. */
  function parseLine(line) {
    var src = String(line || '').trim();
    if (!src) fail('Commande vide.');
    if (src.length > 600) fail('Commande trop longue.');
    var m = /^([A-Za-z_][A-Za-z_0-9]*)\s*\(\s*([a-z])\s*\)\s*=\s*([\s\S]+)$/.exec(src);
    if (m) return fnDef(m[1], m[2], m[3]);
    var y = /^y\s*=\s*([\s\S]+)$/.exec(src);
    if (y) return fnDef(null, 'x', y[1]);
    var name = null, rhs = src;
    var a = /^([A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ_0-9']*)\s*=\s*([\s\S]+)$/.exec(src);
    if (a && a[2].charAt(0) !== '=') { name = a[1]; rhs = a[2].trim(); }
    var c = /^([A-Za-zÀ-ÿ]+)\s*\(([\s\S]*)\)\s*$/.exec(rhs);
    if (c && COMMANDS[strip(c[1])] && !closesEarly(rhs)) {
      return { name: name, kind: 'cmd', cmd: COMMANDS[strip(c[1])], word: c[1], args: splitArgs(c[2]) };
    }
    var p = /^\(([\s\S]*)\)$/.exec(rhs);
    if (p && !closesEarly(rhs)) {
      var parts = splitArgs(p[1]);
      if (parts.length === 2) return { name: name, kind: 'pair', args: parts };
    }
    return { name: name, kind: 'num', expr: rhs };
  }
  // « (1;2)+(3;4) » ne doit pas être pris pour un seul couple.
  function closesEarly(src) {
    var start = src.indexOf('('), depth = 0;
    for (var i = start; i < src.length; i++) {
      if (src[i] === '(') depth++;
      if (src[i] === ')') { depth--; if (depth === 0 && i < src.length - 1) return true; }
    }
    return false;
  }
  function fnDef(name, variable, body) {
    var dom = null, expr = body.trim();
    var d = /\s*(?:sur|,|;)?\s*\[\s*([^\];,]+)\s*[;,]\s*([^\]]+)\s*\]\s*$/.exec(expr);
    if (d && d.index > 0) { dom = [d[1], d[2]]; expr = expr.slice(0, d.index).trim(); }
    return { name: name, kind: 'fn', variable: variable, expr: expr, dom: dom };
  }

  /* --------------------------------------------------------------- géométrie */
  function lineThrough(a, b) { return { k: 'line', a: a, b: b, sub: 'line' }; }
  function intersectLines(l1, l2) {
    var d1x = l1.b.x - l1.a.x, d1y = l1.b.y - l1.a.y, d2x = l2.b.x - l2.a.x, d2y = l2.b.y - l2.a.y;
    var den = d1x * d2y - d1y * d2x;
    if (Math.abs(den) < 1e-12) return [];
    var t = ((l2.a.x - l1.a.x) * d2y - (l2.a.y - l1.a.y) * d2x) / den;
    var u = ((l2.a.x - l1.a.x) * d1y - (l2.a.y - l1.a.y) * d1x) / den;
    if (!onSub(l1, t) || !onSub(l2, u)) return [];
    return [{ x: l1.a.x + t * d1x, y: l1.a.y + t * d1y }];
  }
  function onSub(l, t) {
    if (l.sub === 'segment' || l.sub === 'vector') return t >= -1e-9 && t <= 1 + 1e-9;
    if (l.sub === 'ray') return t >= -1e-9;
    return true;
  }
  function intersectLineCircle(l, c) {
    var dx = l.b.x - l.a.x, dy = l.b.y - l.a.y, fx = l.a.x - c.c.x, fy = l.a.y - c.c.y;
    var A = dx * dx + dy * dy, B = 2 * (fx * dx + fy * dy), C = fx * fx + fy * fy - c.r * c.r;
    var disc = B * B - 4 * A * C;
    if (disc < -1e-12 || A === 0) return [];
    disc = Math.max(0, disc);
    var ts = disc === 0 ? [-B / (2 * A)] : [(-B - Math.sqrt(disc)) / (2 * A), (-B + Math.sqrt(disc)) / (2 * A)];
    return ts.filter(function (t) { return onSub(l, t); }).map(function (t) { return { x: l.a.x + t * dx, y: l.a.y + t * dy }; });
  }
  function intersectCircles(c1, c2) {
    var d = dist(c1.c, c2.c);
    if (d > c1.r + c2.r + 1e-12 || d < Math.abs(c1.r - c2.r) - 1e-12 || d === 0) return [];
    var a = (c1.r * c1.r - c2.r * c2.r + d * d) / (2 * d), h = Math.sqrt(Math.max(0, c1.r * c1.r - a * a));
    var mx = c1.c.x + a * (c2.c.x - c1.c.x) / d, my = c1.c.y + a * (c2.c.y - c1.c.y) / d;
    if (h < 1e-12) return [{ x: mx, y: my }];
    return [
      { x: mx + h * (c2.c.y - c1.c.y) / d, y: my - h * (c2.c.x - c1.c.x) / d },
      { x: mx - h * (c2.c.y - c1.c.y) / d, y: my + h * (c2.c.x - c1.c.x) / d },
    ];
  }
  function polygonArea(pts) {
    var s = 0;
    for (var i = 0; i < pts.length; i++) { var a = pts[i], b = pts[(i + 1) % pts.length]; s += a.x * b.y - b.x * a.y; }
    return Math.abs(s) / 2;
  }
  function angleAt(A, B, C) {
    var a1 = Math.atan2(A.y - B.y, A.x - B.x), a2 = Math.atan2(C.y - B.y, C.x - B.x);
    var d = a2 - a1;
    while (d < 0) d += 2 * Math.PI;
    while (d >= 2 * Math.PI) d -= 2 * Math.PI;
    return { start: a1, sweep: d };
  }

  /** Applique une transformation (fonction point → point, facteur de rayon) à un objet. */
  function transform(obj, map, scale) {
    switch (obj.k) {
      case 'point': { var q = map(obj); return { k: 'point', x: q.x, y: q.y, complex: obj.complex }; }
      case 'line': return { k: 'line', a: map(obj.a), b: map(obj.b), sub: obj.sub };
      case 'circle': return { k: 'circle', c: map(obj.c), r: obj.r * Math.abs(scale == null ? 1 : scale) };
      case 'poly': return { k: 'poly', pts: obj.pts.map(map) };
    }
    fail('Cet objet ne peut pas être transformé.');
  }

  /* --------------------------------------------------------- évaluation */
  /**
   * Évalue la scène. `overrides` : valeurs forcées (curseurs, paramètres de points)
   * pour le calcul d'un lieu. `upto` : n'évalue que les items d'indice < upto.
   */
  function evalScene(plot, overrides, upto) {
    var items = plot.items || [];
    var limit = upto == null ? items.length : upto;
    var view = effectiveView(plot);
    var env = { vars: {}, fns: {}, points: {} };
    var objs = {}, list = [], errors = {}, infos = {}, counters = {};
    function autoName(prefix) {
      counters[prefix] = (counters[prefix] || 0) + 1;
      var name = prefix + counters[prefix];
      while (objs[name]) { counters[prefix]++; name = prefix + counters[prefix]; }
      return name;
    }
    function register(name, obj, item) {
      obj.name = name; obj.item = item; obj.color = obj.color || item.color;
      objs[name] = obj; list.push(obj);
      if (obj.k === 'point') env.points[name] = obj;
      if (obj.k === 'num') env.vars[name] = obj.v;
      if (obj.k === 'fn') env.fns[name] = obj.f;
      if (obj.k === 'slider') env.vars[name] = obj.v;
      return obj;
    }
    function num(raw) {
      var v = M.evaluate(M.parse(raw), env);
      if (typeof v !== 'number' || isNaN(v)) fail('Valeur non numérique : « ' + raw + ' ».');
      return v;
    }
    function ref(raw, kinds, label) {
      var o = objs[String(raw).trim()];
      if (o && (!kinds || kinds.indexOf(o.k) >= 0)) return o;
      if (kinds && kinds.indexOf('point') >= 0) {
        var p = /^\(([\s\S]*)\)$/.exec(String(raw).trim());
        if (p) { var xy = splitArgs(p[1]); if (xy.length === 2) return { k: 'point', x: num(xy[0]), y: num(xy[1]) }; }
      }
      if (kinds && kinds.indexOf('fn') >= 0 && !o) {
        try { return { k: 'fn', f: M.compileFunction(raw, env), expr: raw }; } catch (e) { /* message ci-dessous */ }
      }
      fail((label || 'Objet') + ' introuvable : « ' + raw + ' ».');
    }
    function point(raw) { return ref(raw, ['point'], 'Point'); }
    function linear(raw) { return ref(raw, ['line'], 'Droite'); }
    function curveAt(f, x) { return { x: x, y: f(x) }; }
    function need(args, n, usage) { if (args.length < n) fail('Usage : ' + usage); }

    for (var i = 0; i < limit; i++) {
      var item = items[i];
      if (!item || !item.line) continue;
      var before = list.length;
      try {
        var d = parseLine(item.line);
        if (d.kind === 'fn') {
          var name = d.name || autoName('f');
          var f = M.compileFunction(d.expr, env, d.variable);
          var dom = d.dom ? [num(d.dom[0]), num(d.dom[1])] : null;
          var g = dom ? (function (fn, lo, hi) { return function (x) { return x < lo - 1e-12 || x > hi + 1e-12 ? NaN : fn(x); }; })(f, dom[0], dom[1]) : f;
          register(name, { k: 'fn', f: g, dom: dom, expr: d.expr, label: name + '(x) = ' + d.expr }, item);
        } else if (d.kind === 'pair') {
          var px = num(d.args[0]), py = num(d.args[1]);
          var free = isNumberLiteral(d.args[0]) && isNumberLiteral(d.args[1]);
          register(d.name || autoName('P'), { k: 'point', x: px, y: py, drag: free ? 'free' : null }, item);
        } else if (d.kind === 'num') {
          register(d.name || autoName('n'), { k: 'num', v: num(d.expr), label: (d.name ? d.name + ' = ' : '') }, item);
        } else {
          evalCommand(d, item, i);
        }
      } catch (err) {
        if (err && err.info) infos[item.id] = err.info;
        else errors[item.id] = err instanceof M.MathError || (err && err.name === 'MathError') ? err.message : 'Commande invalide.';
        list.length = before;
      }
    }
    return { objs: objs, list: list, errors: errors, infos: infos, env: env, view: view };

    function evalCommand(d, item, index) {
      var a = d.args, name = d.name;
      switch (d.cmd) {
        case 'slider': {
          need(a, 2, 'a = Curseur(min ; max ; pas)');
          var min = num(a[0]), max = num(a[1]), step = a[2] ? Math.abs(num(a[2])) : (max - min) / 100;
          if (!(max > min)) fail('Le maximum doit dépasser le minimum.');
          var nm = name || autoName('a');
          var initial = a[3] != null && a[3] !== '' ? num(a[3]) : Math.min(max, Math.max(min, 1));
          var v = overrides && overrides[nm] != null ? overrides[nm] : (typeof item.val === 'number' ? item.val : initial);
          v = Math.min(max, Math.max(min, v));
          register(nm, { k: 'slider', v: v, min: min, max: max, step: step || 0.01 }, item);
          return;
        }
        case 'function': {
          need(a, 1, 'Fonction(expression ; a ; b)');
          var fn = M.compileFunction(a[0], env);
          var lo = a[1] != null ? num(a[1]) : null, hi = a[2] != null ? num(a[2]) : null;
          var g = lo == null ? fn : function (x) { return x < lo || x > hi ? NaN : fn(x); };
          register(name || autoName('f'), { k: 'fn', f: g, dom: lo == null ? null : [lo, hi], expr: a[0] }, item);
          return;
        }
        case 'point': {
          need(a, 2, 'B = Point(f ; abscisse)');
          var host = ref(a[0], ['fn', 'line', 'circle'], 'Courbe');
          var nameP = name || autoName('P');
          var t = overrides && overrides[nameP] != null ? overrides[nameP] : num(a[1]);
          var pt;
          if (host.k === 'fn') pt = curveAt(host.f, t);
          else if (host.k === 'line') pt = { x: host.a.x + t * (host.b.x - host.a.x), y: host.a.y + t * (host.b.y - host.a.y) };
          else pt = { x: host.c.x + host.r * Math.cos(t), y: host.c.y + host.r * Math.sin(t) };
          register(nameP, { k: 'point', x: pt.x, y: pt.y, drag: isNumberLiteral(a[1]) ? 'on' : null, host: host, param: t }, item);
          return;
        }
        case 'midpoint': {
          need(a, 2, 'M = Milieu(A ; B)');
          var A = point(a[0]), B = point(a[1]);
          register(name || autoName('M'), { k: 'point', x: (A.x + B.x) / 2, y: (A.y + B.y) / 2 }, item);
          return;
        }
        case 'line': case 'segment': case 'ray': case 'vector': {
          need(a, 2, d.word + '(A ; B)');
          var P = point(a[0]);
          var Q = objs[a[1]] && objs[a[1]].k === 'line' && d.cmd === 'vector'
            ? { x: P.x + objs[a[1]].b.x - objs[a[1]].a.x, y: P.y + objs[a[1]].b.y - objs[a[1]].a.y } : point(a[1]);
          if (dist(P, Q) < 1e-12) fail('Les deux points sont confondus.');
          var obj = { k: 'line', a: { x: P.x, y: P.y }, b: { x: Q.x, y: Q.y }, sub: d.cmd };
          if (d.cmd === 'segment') obj.measure = dist(P, Q);
          register(name || autoName(d.cmd === 'vector' ? 'u' : d.cmd === 'segment' ? 's' : 'd'), obj, item);
          return;
        }
        case 'circle': {
          need(a, 2, 'Cercle(O ; rayon) ou Cercle(O ; A)');
          var O = point(a[0]);
          var r = objs[a[1]] && objs[a[1]].k === 'point' ? dist(O, objs[a[1]]) : num(a[1]);
          if (!(r > 0)) fail('Le rayon doit être positif.');
          register(name || autoName('c'), { k: 'circle', c: { x: O.x, y: O.y }, r: r }, item);
          return;
        }
        case 'polygon': {
          need(a, 3, 'Polygone(A ; B ; C ; …)');
          var pts = a.map(point).map(function (p) { return { x: p.x, y: p.y }; });
          register(name || autoName('poly'), { k: 'poly', pts: pts, area: polygonArea(pts) }, item);
          return;
        }
        case 'perp': case 'parallel': {
          need(a, 2, d.word + '(droite ; point)');
          var L = linear(a[0]), Pt = point(a[1]);
          var dx = L.b.x - L.a.x, dy = L.b.y - L.a.y;
          var dir = d.cmd === 'perp' ? { x: -dy, y: dx } : { x: dx, y: dy };
          register(name || autoName('d'), lineThrough({ x: Pt.x, y: Pt.y }, { x: Pt.x + dir.x, y: Pt.y + dir.y }), item);
          return;
        }
        case 'bisector': {
          need(a, 2, 'Médiatrice(A ; B)');
          var A1 = point(a[0]), B1 = point(a[1]);
          var mid = { x: (A1.x + B1.x) / 2, y: (A1.y + B1.y) / 2 };
          register(name || autoName('d'), lineThrough(mid, { x: mid.x - (B1.y - A1.y), y: mid.y + (B1.x - A1.x) }), item);
          return;
        }
        case 'anglebisector': {
          need(a, 3, 'Bissectrice(A ; B ; C) — bissectrice de l’angle en B');
          var PA = point(a[0]), PB = point(a[1]), PC = point(a[2]);
          var u1 = dist(PA, PB), u2 = dist(PC, PB);
          var w = { x: (PA.x - PB.x) / u1 + (PC.x - PB.x) / u2, y: (PA.y - PB.y) / u1 + (PC.y - PB.y) / u2 };
          if (Math.hypot(w.x, w.y) < 1e-12) w = { x: -(PA.y - PB.y), y: PA.x - PB.x };
          register(name || autoName('d'), lineThrough({ x: PB.x, y: PB.y }, { x: PB.x + w.x, y: PB.y + w.y }), item);
          return;
        }
        case 'intersect': {
          need(a, 2, 'Intersection(objet1 ; objet2)');
          var o1 = ref(a[0], ['line', 'circle', 'fn'], 'Objet'), o2 = ref(a[1], ['line', 'circle', 'fn'], 'Objet');
          var found = intersections(o1, o2);
          if (a[2]) { var k = Math.round(num(a[2])); found = found[k - 1] ? [found[k - 1]] : []; }
          if (!found.length) throw { info: 'Aucun point d’intersection visible.' };
          multiPoints(name || 'I', found, item);
          return;
        }
        case 'roots': {
          need(a, 1, 'Racines(f)');
          var rf = ref(a[0], ['fn'], 'Fonction'), span = domainOf(rf);
          var zs = M.zeros(rf.f, span[0], span[1]);
          if (!zs.length) throw { info: 'Aucune racine sur l’intervalle affiché.' };
          multiPoints(name || 'R', zs.map(function (x) { return { x: x, y: 0, note: 'x = ' + M.fmt(x, 3) }; }), item);
          return;
        }
        case 'extrema': {
          need(a, 1, 'Extremums(f)');
          var ef = ref(a[0], ['fn'], 'Fonction'), espan = domainOf(ef);
          var ex = M.extrema(ef.f, espan[0], espan[1]);
          if (!ex.length) throw { info: 'Aucun extremum local sur l’intervalle affiché.' };
          multiPoints(name || 'E', ex.map(function (e) {
            return { x: e.x, y: e.y, note: (e.kind === 'max' ? 'max ' : 'min ') + M.fmt(e.y, 3) };
          }), item);
          return;
        }
        case 'asymptotes': {
          need(a, 1, 'Asymptotes(f)');
          var af = ref(a[0], ['fn'], 'Fonction');
          var span2 = [Math.min(view.xmin, -50), Math.max(view.xmax, 50)];
          var as = M.asymptotes(af.f, span2[0], span2[1]);
          if (!as.length) throw { info: 'Aucune asymptote détectée.' };
          as.forEach(function (s) {
            var l = s.kind === 'v' ? lineThrough({ x: s.x, y: 0 }, { x: s.x, y: 1 })
              : lineThrough({ x: 0, y: s.b }, { x: 1, y: (s.a || 0) + s.b });
            l.dashed = true;
            l.note = s.kind === 'v' ? 'x = ' + M.fmt(s.x) : M.fmtLine(s.a || 0, s.b);
            register(autoName(name || 'as'), l, item);
          });
          return;
        }
        case 'tangent': {
          need(a, 2, 'Tangente(f ; abscisse) ou Tangente(f ; A)');
          var tf = ref(a[0], ['fn'], 'Fonction');
          var x0 = objs[a[1]] && objs[a[1]].k === 'point' ? objs[a[1]].x : num(a[1]);
          var y0 = tf.f(x0), m = M.derivative(tf.f, 1)(x0);
          if (!isFinite(y0) || !isFinite(m)) fail('La fonction n’est pas dérivable en ' + M.fmt(x0) + '.');
          var tl = lineThrough({ x: x0, y: y0 }, { x: x0 + 1, y: y0 + m });
          tl.note = 'T : ' + M.fmtLine(m, y0 - m * x0);
          tl.slope = m;
          register(name || autoName('T'), tl, item);
          return;
        }
        case 'derivative': {
          need(a, 1, "g = Dérivée(f)");
          var df = ref(a[0], ['fn'], 'Fonction');
          var order = a[1] ? Math.max(1, Math.min(3, Math.round(num(a[1])))) : 1;
          var gname = name || (df.name ? df.name + new Array(order + 1).join("'") : autoName('g'));
          register(gname, { k: 'fn', f: M.derivative(df.f, order), dom: df.dom, expr: gname, label: gname + '(x)', dashed: false }, item);
          if (/^[A-Za-z_]\w*$/.test(gname)) env.fns[gname] = objs[gname].f;
          return;
        }
        case 'integral': case 'area': {
          if (d.cmd === 'area' && a.length === 1) {
            var shape = ref(a[0], ['poly', 'circle'], 'Polygone ou cercle');
            var ar = shape.k === 'poly' ? polygonArea(shape.pts) : Math.PI * shape.r * shape.r;
            register(name || autoName('aire'), { k: 'num', v: ar, label: 'Aire = ', at: shape.k === 'poly' ? centroid(shape.pts) : shape.c }, item);
            return;
          }
          need(a, 3, d.cmd === 'area' ? 'Aire(f ; g ; a ; b)' : 'Intégrale(f ; a ; b)');
          var sf = ref(a[0], ['fn'], 'Fonction');
          var sg = d.cmd === 'area' ? ref(a[1], ['fn'], 'Fonction') : null;
          var lo2 = num(a[sg ? 2 : 1]), hi2 = num(a[sg ? 3 : 2]);
          var diff = sg ? function (x) { return Math.abs(sf.f(x) - sg.f(x)); } : sf.f;
          var val = M.integral(diff, lo2, hi2);
          var shade = register(name || autoName('S'), {
            k: 'shade', f: sf.f, g: sg ? sg.f : null, a: lo2, b: hi2, v: val,
            note: (sg ? 'Aire = ' : '∫ = ') + M.fmt(val, 3),
          }, item);
          env.vars[shade.name] = val; // réutilisable dans un calcul : 2*I1
          return;
        }
        case 'distance': {
          need(a, 2, 'Distance(A ; B)');
          var DA = point(a[0]), DB = objs[a[1]] && objs[a[1]].k === 'line' ? null : point(a[1]);
          var dv, at;
          if (DB) { dv = dist(DA, DB); at = { x: (DA.x + DB.x) / 2, y: (DA.y + DB.y) / 2 }; }
          else {
            var DL = objs[a[1]], ddx = DL.b.x - DL.a.x, ddy = DL.b.y - DL.a.y;
            dv = Math.abs(ddy * (DA.x - DL.a.x) - ddx * (DA.y - DL.a.y)) / Math.hypot(ddx, ddy); at = DA;
          }
          register(name || autoName('dist'), { k: 'num', v: dv, label: (name || (a[0] + a[1])) + ' = ', at: at }, item);
          return;
        }
        case 'angle': {
          need(a, 3, 'Angle(A ; B ; C) — angle en B');
          var GA = point(a[0]), GB = point(a[1]), GC = point(a[2]);
          var ang = angleAt(GA, GB, GC);
          var deg = ang.sweep * 180 / Math.PI;
          var angleObj = register(name || autoName('α'), { k: 'angle', v: deg, at: { x: GB.x, y: GB.y }, start: ang.start, sweep: ang.sweep }, item);
          env.vars[angleObj.name] = deg;
          return;
        }
        case 'translate': case 'reflect': case 'dilate': case 'rotate': {
          var src = ref(a[0], ['point', 'line', 'circle', 'poly'], 'Objet');
          var map, scale = 1, label = d.cmd;
          if (d.cmd === 'translate') {
            need(a, 2, 'Translation(objet ; vecteur)');
            var v = objs[a[1]];
            if (!v || v.k !== 'line') fail('Donnez un vecteur : u = Vecteur(A ; B).');
            var tx = v.b.x - v.a.x, ty = v.b.y - v.a.y;
            map = function (p) { return { x: p.x + tx, y: p.y + ty }; };
          } else if (d.cmd === 'reflect') {
            need(a, 2, 'Symétrie(objet ; point ou droite)');
            var c = objs[a[1]];
            if (c && c.k === 'line') {
              var lx = c.b.x - c.a.x, ly = c.b.y - c.a.y, ll = lx * lx + ly * ly;
              map = function (p) {
                var t = ((p.x - c.a.x) * lx + (p.y - c.a.y) * ly) / ll;
                var fx = c.a.x + t * lx, fy = c.a.y + t * ly;
                return { x: 2 * fx - p.x, y: 2 * fy - p.y };
              };
            } else {
              var C0 = point(a[1]);
              map = function (p) { return { x: 2 * C0.x - p.x, y: 2 * C0.y - p.y }; };
            }
          } else if (d.cmd === 'dilate') {
            need(a, 3, 'Homothétie(objet ; centre ; rapport)');
            var H = point(a[1]), kk = num(a[2]); scale = kk;
            map = function (p) { return { x: H.x + kk * (p.x - H.x), y: H.y + kk * (p.y - H.y) }; };
          } else {
            need(a, 3, 'Rotation(objet ; centre ; angle en degrés)');
            var R = point(a[1]);
            var th = /pi|π/.test(a[2]) ? num(a[2]) : num(a[2]) * Math.PI / 180;
            map = function (p) {
              var x = p.x - R.x, y = p.y - R.y;
              return { x: R.x + x * Math.cos(th) - y * Math.sin(th), y: R.y + x * Math.sin(th) + y * Math.cos(th) };
            };
          }
          var img = transform(src, map, scale);
          img.image = label;
          var imgName = name;
          if (!imgName && src.name) { imgName = src.name + "'"; while (objs[imgName] && imgName.length < src.name.length + 3) imgName += "'"; }
          if (!imgName || objs[imgName]) imgName = autoName('img');
          register(imgName, img, item);
          return;
        }
        case 'barycenter': {
          if (a.length < 4 || a.length % 2) fail('Barycentre(A ; a ; B ; b ; …)');
          var sx = 0, sy = 0, sw = 0;
          for (var j = 0; j < a.length; j += 2) {
            var BP = point(a[j]), bw = num(a[j + 1]);
            sx += bw * BP.x; sy += bw * BP.y; sw += bw;
          }
          if (Math.abs(sw) < 1e-12) fail('La somme des coefficients est nulle : pas de barycentre.');
          register(name || autoName('G'), { k: 'point', x: sx / sw, y: sy / sw }, item);
          return;
        }
        case 'locus': {
          need(a, 2, 'Lieu(M ; curseur ou point mobile)');
          var target = String(a[0]).trim(), driverName = String(a[1]).trim();
          var driver = objs[driverName];
          if (!driver) fail('Curseur ou point mobile introuvable : « ' + driverName + ' ».');
          var range;
          if (driver.k === 'slider') range = [driver.min, driver.max];
          else if (driver.k === 'point' && driver.host) range = driver.host.k === 'fn' ? domainOf(driver.host) : driver.host.k === 'circle' ? [0, 2 * Math.PI] : [-5, 5];
          else fail('Le lieu demande un curseur ou un point sur une courbe.');
          var pts2 = [];
          for (var s = 0; s <= 160; s++) {
            var ov = {}; ov[driverName] = range[0] + (range[1] - range[0]) * s / 160;
            var sub = evalScene(plot, Object.assign({}, overrides, ov), index);
            var tp = sub.objs[target];
            pts2.push(tp && tp.k === 'point' && isFinite(tp.x) && isFinite(tp.y) ? { x: tp.x, y: tp.y } : null);
          }
          register(name || autoName('L'), { k: 'curve', pts: pts2 }, item);
          return;
        }
        case 'trace': {
          need(a, 1, 'Trace(M)');
          point(a[0]);
          register(name || autoName('tr'), { k: 'trace', of: String(a[0]).trim() }, item);
          return;
        }
        case 'trig': {
          var tv = a.length && a[0] !== '' ? num(a[0]) : Math.PI / 3;
          register(name || autoName('C'), { k: 'trig', t: tv }, item);
          return;
        }
        case 'sequence': {
          need(a, 2, 'Suite(f ; u0 ; n)');
          var qf = ref(a[0], ['fn'], 'Fonction'), u = num(a[1]), n = a[2] ? Math.max(1, Math.min(40, Math.round(num(a[2])))) : 6;
          var vals = [u];
          for (var q = 0; q < n; q++) { u = qf.f(u); if (!isFinite(u)) break; vals.push(u); }
          register(name || autoName('u'), { k: 'cobweb', f: qf.f, vals: vals }, item);
          vals.forEach(function (vv, idx) { env.vars['u' + idx] = vv; });
          return;
        }
        case 'complex': {
          need(a, 2, 'z = Complexe(a ; b)');
          var re = num(a[0]), im = num(a[1]);
          var free2 = isNumberLiteral(a[0]) && isNumberLiteral(a[1]);
          register(name || autoName('z'), { k: 'point', x: re, y: im, drag: free2 ? 'free' : null, complex: true }, item);
          return;
        }
        case 'target': {
          need(a, 3, 'Placer(A ; x ; y) — exercice : l’élève place le point');
          var tname = String(a[0]).replace(/"/g, '').trim();
          register(name || ('?' + tname), { k: 'target', label: tname, x: num(a[1]), y: num(a[2]), tol: a[3] ? Math.abs(num(a[3])) : 0.3 }, item);
          return;
        }
        case 'text': {
          need(a, 1, 'Texte("…" ; A)');
          var txt = String(a[0]).replace(/^"|"$/g, '');
          var anchor = a[1] ? point(a[1]) : { x: view.xmin + (view.xmax - view.xmin) * 0.05, y: view.ymax - (view.ymax - view.ymin) * 0.1 };
          register(name || autoName('t'), { k: 'text', text: txt.slice(0, 200), at: { x: anchor.x, y: anchor.y } }, item);
          return;
        }
      }
      fail('Commande inconnue.');
    }
    function multiPoints(base, pts, item) {
      pts.forEach(function (p, idx) {
        var nm = pts.length === 1 ? base : base + (idx + 1);
        if (objs[nm]) nm = autoName(base);
        register(nm, { k: 'point', x: p.x, y: p.y, note: p.note }, item);
      });
    }
    function domainOf(fnObj) {
      var lo = view.xmin, hi = view.xmax;
      if (fnObj.dom) { lo = Math.max(lo, fnObj.dom[0]); hi = Math.min(hi, fnObj.dom[1]); }
      return [lo, hi];
    }
    function intersections(o1, o2) {
      if (o1.k === 'fn' || o2.k === 'fn') {
        var f1 = toFn(o1), f2 = toFn(o2);
        if (!f1 || !f2) fail('Intersection entre une courbe et un cercle : non disponible.');
        var span = [view.xmin, view.xmax];
        return M.zeros(function (x) { return f1(x) - f2(x); }, span[0], span[1]).map(function (x) { return { x: x, y: f1(x) }; });
      }
      if (o1.k === 'line' && o2.k === 'line') return intersectLines(o1, o2);
      if (o1.k === 'line' && o2.k === 'circle') return intersectLineCircle(o1, o2);
      if (o1.k === 'circle' && o2.k === 'line') return intersectLineCircle(o2, o1);
      return intersectCircles(o1, o2);
    }
    function toFn(o) {
      if (o.k === 'fn') return o.f;
      if (o.k === 'line') {
        var dx = o.b.x - o.a.x;
        if (Math.abs(dx) < 1e-12) return null;
        var m = (o.b.y - o.a.y) / dx;
        return function (x) { return o.a.y + m * (x - o.a.x); };
      }
      return null;
    }
  }
  function centroid(pts) {
    return { x: pts.reduce(function (s, p) { return s + p.x; }, 0) / pts.length, y: pts.reduce(function (s, p) { return s + p.y; }, 0) / pts.length };
  }

  /* ------------------------------------------------------------- repère */
  function effectiveView(plot) {
    var v = plot.view || { xmin: -6, xmax: 6, ymin: -4, ymax: 4 };
    var opts = plot.opts || {};
    if (opts.ortho === false) return { xmin: v.xmin, xmax: v.xmax, ymin: v.ymin, ymax: v.ymax };
    var gw = Math.max(40, (plot.w || 480)), gh = Math.max(40, (plot.h || 360) - HEADER);
    var scale = gw / (v.xmax - v.xmin), yc = (v.ymin + v.ymax) / 2, half = gh / scale / 2;
    return { xmin: v.xmin, xmax: v.xmax, ymin: yc - half, ymax: yc + half };
  }
  function area(plot) { return { x: plot.x, y: plot.y + HEADER, w: plot.w, h: plot.h - HEADER }; }
  function mapper(plot) {
    var v = effectiveView(plot), r = area(plot);
    var sx = r.w / (v.xmax - v.xmin), sy = r.h / (v.ymax - v.ymin);
    return {
      v: v, r: r, sx: sx, sy: sy,
      px: function (x) { return r.x + (x - v.xmin) * sx; },
      py: function (y) { return r.y + r.h - (y - v.ymin) * sy; },
      mx: function (X) { return v.xmin + (X - r.x) / sx; },
      my: function (Y) { return v.ymin + (r.y + r.h - Y) / sy; },
    };
  }
  function niceStep(range, pixels) {
    var raw = range / Math.max(1, pixels / 60), pow = Math.pow(10, Math.floor(Math.log10(raw)));
    var n = raw / pow;
    return (n < 1.5 ? 1 : n < 3.5 ? 2 : n < 7.5 ? 5 : 10) * pow;
  }

  function defaultPlot(x, y, preset) {
    var plot = {
      type: 'plot', x: x, y: y, w: 560, h: 420, title: 'Repère',
      view: { xmin: -6, xmax: 6, ymin: -4, ymax: 4 }, home: null,
      opts: { grid: true, axes: true, ortho: true, pi: false, complex: false }, items: [],
    };
    if (preset && PRESETS[preset]) {
      var p = PRESETS[preset];
      plot.title = p.title;
      plot.view = Object.assign({}, p.view || plot.view);
      plot.opts = Object.assign({}, plot.opts, p.opts || {});
      plot.items = p.items.map(function (line, i) {
        var item = { id: 'i' + i + '-' + Math.random().toString(36).slice(2, 7), line: line, color: PALETTE[i % PALETTE.length] };
        return item;
      });
    }
    plot.home = Object.assign({}, plot.view);
    return plot;
  }

  var PRESETS = {
    fonction: { title: 'Étude de fonction', items: ['f(x)=x^3-3x+1', "Dérivée(f)", 'Racines(f)', 'Extremums(f)', 'A=Point(f;1.5)', 'T=Tangente(f;A)'] },
    second: { title: 'Second degré', items: ['a=Curseur(-3;3;0.1;1)', 'b=Curseur(-5;5;0.1;-2)', 'c=Curseur(-5;5;0.1;-3)', 'f(x)=a x^2+b x+c', 'Racines(f)', 'Extremums(f)'] },
    asymptotes: { title: 'Asymptotes', view: { xmin: -8, xmax: 8, ymin: -6, ymax: 6 }, items: ['f(x)=(x^2+1)/(x-1)', 'Asymptotes(f)'] },
    integrale: { title: 'Intégrale', view: { xmin: -1, xmax: 5, ymin: -1, ymax: 5 }, items: ['f(x)=0.5x^2-x+2', 'a=Curseur(0;4;0.1;0.5)', 'b=Curseur(0;4;0.1;3)', 'Intégrale(f;a;b)'] },
    trigo: { title: 'Cercle trigonométrique', view: { xmin: -2, xmax: 2, ymin: -1.5, ymax: 1.5 }, items: ['t=Curseur(0;2pi;pi/12;pi/3)', 'CercleTrigo(t)'] },
    suite: { title: 'Suite récurrente', view: { xmin: -0.5, xmax: 4, ymin: -0.5, ymax: 4 }, items: ['f(x)=sqrt(x+2)', 'u=Suite(f;0;6)'] },
    complexe: { title: 'Plan complexe', view: { xmin: -4, xmax: 4, ymin: -3, ymax: 3 }, opts: { complex: true }, items: ['O=(0;0)', 'z=Complexe(2;1)', "z'=Rotation(z;O;90)"] },
    triangle: { title: 'Triangle et droites remarquables', view: { xmin: -1, xmax: 9, ymin: -1, ymax: 7 }, items: ['A=(1;1)', 'B=(7;1.5)', 'C=(3;5.5)', 'Polygone(A;B;C)', 'd1=Médiatrice(A;B)', 'd2=Médiatrice(B;C)', 'O=Intersection(d1;d2)', 'Cercle(O;A)'] },
    transformations: { title: 'Transformations', view: { xmin: -6, xmax: 6, ymin: -4, ymax: 4 }, items: ['A=(1;1)', 'B=(3;1)', 'C=(2;3)', 'p=Polygone(A;B;C)', 'O=(0;0)', 'Symétrie(p;O)', 'k=Curseur(-2;2;0.1)', 'Homothétie(p;O;k)'] },
    barycentre: { title: 'Barycentre', view: { xmin: -1, xmax: 7, ymin: -1, ymax: 5 }, items: ['A=(1;1)', 'B=(6;2)', 'a=Curseur(-3;3;1;1)', 'b=Curseur(-3;3;1;2)', 'G=Barycentre(A;a;B;b)', 'Segment(A;B)'] },
    lieu: { title: 'Lieu géométrique', view: { xmin: -5, xmax: 5, ymin: -4, ymax: 4 }, items: ['O=(0;0)', 'c=Cercle(O;3)', 'A=(4;0)', 'M=Point(c;1)', 'I=Milieu(A;M)', 'Segment(A;M)', 'Lieu(I;M)'] },
    exercice: { title: 'Exercice : placer des points', items: ['Placer(A;2;3)', 'Placer(B;-1;2)', 'Placer(C;-3;-1)'] },
  };

  /* ---------------------------------------------------------------- rendu */
  /**
   * Dessine le repère. `state` (facultatif) :
   *   answers : réponses des élèves [{target, mx, my, by}], me : id utilisateur,
   *   reviewer : true pour l'enseignant (voit toutes les réponses),
   *   traces : {nomDuPoint: [{x,y}]}, editable : boutons d'édition visibles.
   * Renvoie la mise en page des zones cliquables (stockée par l'appelant).
   */
  function render(ctx, plot, state) {
    state = state || {};
    var scene = evalScene(plot);
    var T = mapper(plot), r = T.r, v = T.v, opts = plot.opts || {};
    var layout = { buttons: [], sliders: [], handles: [], scene: scene };
    ctx.save();
    // Cadre et en-tête
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(plot.x, plot.y, plot.w, plot.h);
    ctx.fillStyle = '#eef3fb';
    ctx.fillRect(plot.x, plot.y, plot.w, HEADER);
    ctx.strokeStyle = '#9fb3d1'; ctx.lineWidth = 1;
    ctx.strokeRect(plot.x + 0.5, plot.y + 0.5, plot.w - 1, plot.h - 1);
    ctx.fillStyle = '#12306b'; ctx.font = 'bold 14px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    var targets = scene.list.filter(function (o) { return o.k === 'target'; });
    var title = String(plot.title || 'Repère').slice(0, 60);
    if (targets.length) title += ' — placez : ' + targets.map(function (t) { return t.label + '(' + M.fmt(t.x) + ' ; ' + M.fmt(t.y) + ')'; }).join(', ');
    ctx.fillText(ellipsis(ctx, title, plot.w - 150), plot.x + 10, plot.y + HEADER / 2);
    var buttons = [['zoomOut', '−'], ['zoomIn', '+'], ['reset', '⟲']];
    if (state.editable) buttons.push(['edit', '✎']);
    buttons.forEach(function (b, idx) {
      var bx = plot.x + plot.w - (buttons.length - idx) * 28 - 4, by = plot.y + 4;
      ctx.fillStyle = '#ffffff'; ctx.fillRect(bx, by, 24, 22);
      ctx.strokeStyle = '#9fb3d1'; ctx.strokeRect(bx + 0.5, by + 0.5, 23, 21);
      ctx.fillStyle = '#12306b'; ctx.font = '15px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(b[1], bx + 12, by + 11);
      layout.buttons.push({ name: b[0], x: bx, y: by, w: 24, h: 22 });
    });

    ctx.beginPath(); ctx.rect(r.x, r.y, r.w, r.h); ctx.clip();
    drawGridAndAxes(ctx, T, opts);

    // Ordre : surfaces, courbes, droites, cercles, polygones, puis points et textes.
    var order = { shade: 0, poly: 1, cobweb: 2, curve: 2, fn: 3, line: 4, circle: 4, trig: 5, angle: 6, trace: 7, point: 8, target: 9, num: 9, text: 9, slider: 10 };
    var visible = scene.list.filter(function (o) { return !o.item.hidden; });
    visible.slice().sort(function (a, b) { return (order[a.k] || 0) - (order[b.k] || 0); }).forEach(function (o) {
      drawObject(ctx, T, o, scene, state, layout);
    });
    drawAnswers(ctx, T, scene, state);
    ctx.restore();

    // Curseurs (au-dessus, hors découpe)
    var sliders = scene.list.filter(function (o) { return o.k === 'slider' && !o.item.hidden; });
    sliders.forEach(function (s, idx) {
      var sx = r.x + 10, sy = r.y + 10 + idx * 30, tw = 130;
      ctx.save();
      ctx.fillStyle = 'rgba(255,255,255,0.92)'; ctx.fillRect(sx - 6, sy - 6, tw + 120, 26);
      ctx.strokeStyle = '#c5d2e8'; ctx.strokeRect(sx - 6.5, sy - 6.5, tw + 120, 26);
      ctx.fillStyle = '#263449'; ctx.font = '13px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.fillText(s.name + ' = ' + (/pi/.test(s.item.line) ? M.fmtPi(s.v) : M.fmt(s.v)), sx, sy + 7);
      var tx = sx + 100, ty = sy + 7;
      ctx.strokeStyle = '#9fb3d1'; ctx.lineWidth = 4; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(tx + tw, ty); ctx.stroke();
      var kx = tx + (s.v - s.min) / (s.max - s.min) * tw;
      ctx.fillStyle = s.color || '#1d4fa3';
      ctx.beginPath(); ctx.arc(kx, ty, 7, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
      layout.sliders.push({ name: s.name, item: s.item, x: tx, y: ty - 10, w: tw, h: 20, min: s.min, max: s.max, step: s.step });
    });
    return layout;
  }

  function ellipsis(ctx, text, max) {
    if (ctx.measureText(text).width <= max) return text;
    while (text.length > 3 && ctx.measureText(text + '…').width > max) text = text.slice(0, -1);
    return text + '…';
  }

  function drawGridAndAxes(ctx, T, opts) {
    var v = T.v, r = T.r;
    var stepX = opts.pi ? piStep(v.xmax - v.xmin, r.w) : niceStep(v.xmax - v.xmin, r.w);
    var stepY = niceStep(v.ymax - v.ymin, r.h);
    if (opts.ortho !== false && !opts.pi) stepY = stepX = Math.max(stepX, stepY);
    ctx.lineWidth = 1;
    if (opts.grid !== false) {
      ctx.strokeStyle = '#e3e9f3';
      for (var gx = Math.ceil(v.xmin / stepX) * stepX; gx <= v.xmax; gx += stepX) { ctx.beginPath(); ctx.moveTo(T.px(gx), r.y); ctx.lineTo(T.px(gx), r.y + r.h); ctx.stroke(); }
      for (var gy = Math.ceil(v.ymin / stepY) * stepY; gy <= v.ymax; gy += stepY) { ctx.beginPath(); ctx.moveTo(r.x, T.py(gy)); ctx.lineTo(r.x + r.w, T.py(gy)); ctx.stroke(); }
    }
    if (opts.axes === false) return;
    var ox = Math.min(r.x + r.w - 1, Math.max(r.x, T.px(0))), oy = Math.min(r.y + r.h - 1, Math.max(r.y, T.py(0)));
    ctx.strokeStyle = '#3d4b63'; ctx.fillStyle = '#3d4b63'; ctx.lineWidth = 1.3;
    ctx.beginPath(); ctx.moveTo(r.x, oy); ctx.lineTo(r.x + r.w, oy); ctx.moveTo(ox, r.y + r.h); ctx.lineTo(ox, r.y); ctx.stroke();
    arrowHead(ctx, r.x + r.w - 2, oy, 0); arrowHead(ctx, ox, r.y + 2, -Math.PI / 2);
    ctx.font = '11px sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    for (var x = Math.ceil(v.xmin / stepX) * stepX; x <= v.xmax; x += stepX) {
      if (Math.abs(x) < stepX / 1000) continue;
      var X = T.px(x);
      ctx.beginPath(); ctx.moveTo(X, oy - 3); ctx.lineTo(X, oy + 3); ctx.stroke();
      ctx.fillText(opts.pi ? M.fmtPi(x) : M.fmt(x, 3), X, Math.min(oy + 5, r.y + r.h - 14));
    }
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    for (var y = Math.ceil(v.ymin / stepY) * stepY; y <= v.ymax; y += stepY) {
      if (Math.abs(y) < stepY / 1000) continue;
      var Y = T.py(y);
      ctx.beginPath(); ctx.moveTo(ox - 3, Y); ctx.lineTo(ox + 3, Y); ctx.stroke();
      ctx.fillText(M.fmt(y, 3) + (opts.complex ? 'i' : ''), Math.max(ox - 5, r.x + 24), Y);
    }
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'; ctx.font = 'italic 12px serif';
    ctx.fillText(opts.complex ? 'Re' : 'x', r.x + r.w - 18, oy - 6);
    ctx.fillText(opts.complex ? 'Im' : 'y', ox + 6, r.y + 14);
    ctx.fillText('O', ox - 12, oy + 12);
  }
  function piStep(range, pixels) {
    var candidates = [Math.PI / 6, Math.PI / 4, Math.PI / 2, Math.PI, 2 * Math.PI, 4 * Math.PI];
    for (var i = 0; i < candidates.length; i++) if (range / candidates[i] <= pixels / 55) return candidates[i];
    return 8 * Math.PI;
  }
  function arrowHead(ctx, x, y, angle) {
    ctx.save(); ctx.translate(x, y); ctx.rotate(angle);
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(-8, -4); ctx.lineTo(-8, 4); ctx.closePath(); ctx.fill();
    ctx.restore();
  }
  function label(ctx, text, X, Y, color) {
    ctx.font = '13px sans-serif'; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    var w = ctx.measureText(text).width;
    ctx.fillStyle = 'rgba(255,255,255,0.85)'; ctx.fillRect(X - 2, Y - 13, w + 4, 17);
    ctx.fillStyle = color || '#263449'; ctx.fillText(text, X, Y);
  }

  function drawObject(ctx, T, o, scene, state, layout) {
    var color = o.color || '#1d4fa3', r = T.r;
    ctx.save();
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
    switch (o.k) {
      case 'fn': drawFunction(ctx, T, o.f, color, o.dashed); {
        var lx = T.v.xmin + (T.v.xmax - T.v.xmin) * 0.82, ly = o.f(lx);
        if (isFinite(ly) && T.py(ly) > r.y + 12 && T.py(ly) < r.y + r.h - 4) label(ctx, '𝒞' + o.name, T.px(lx) + 4, T.py(ly) - 6, color);
      } break;
      case 'line': drawLine(ctx, T, o, color); break;
      case 'circle':
        ctx.beginPath(); ctx.ellipse(T.px(o.c.x), T.py(o.c.y), o.r * T.sx, o.r * T.sy, 0, 0, Math.PI * 2); ctx.stroke(); break;
      case 'poly':
        ctx.beginPath(); o.pts.forEach(function (p, i) { (i ? ctx.lineTo : ctx.moveTo).call(ctx, T.px(p.x), T.py(p.y)); }); ctx.closePath();
        ctx.globalAlpha = 0.12; ctx.fill(); ctx.globalAlpha = 1; ctx.stroke(); break;
      case 'shade': drawShade(ctx, T, o, color); break;
      case 'point': drawPoint(ctx, T, o, color, layout); break;
      case 'num':
        if (o.at) label(ctx, o.label + M.fmt(o.v, 3), T.px(o.at.x) + 6, T.py(o.at.y) - 8, color);
        break;
      case 'angle': {
        var R = 26, X = T.px(o.at.x), Y = T.py(o.at.y);
        ctx.beginPath(); ctx.moveTo(X, Y); ctx.arc(X, Y, R, -o.start, -(o.start + o.sweep), true); ctx.closePath();
        ctx.globalAlpha = 0.18; ctx.fill(); ctx.globalAlpha = 1;
        var mid = o.start + o.sweep / 2;
        label(ctx, o.name + ' = ' + M.fmt(o.v, 1) + '°', X + (R + 6) * Math.cos(mid), Y - (R + 6) * Math.sin(mid), color);
      } break;
      case 'text': label(ctx, o.text, T.px(o.at.x), T.py(o.at.y), color); break;
      case 'curve': {
        ctx.lineWidth = 2; ctx.setLineDash([6, 4]); ctx.beginPath(); var started = false;
        o.pts.forEach(function (p) { if (!p) { started = false; return; } if (started) ctx.lineTo(T.px(p.x), T.py(p.y)); else { ctx.moveTo(T.px(p.x), T.py(p.y)); started = true; } });
        ctx.stroke();
      } break;
      case 'trace': {
        var pts = (state.traces || {})[o.of] || [];
        ctx.lineWidth = 1.5; ctx.globalAlpha = 0.7; ctx.beginPath();
        pts.forEach(function (p, i) { (i ? ctx.lineTo : ctx.moveTo).call(ctx, T.px(p.x), T.py(p.y)); }); ctx.stroke();
      } break;
      case 'trig': drawTrig(ctx, T, o, color); break;
      case 'cobweb': drawCobweb(ctx, T, o, color); break;
      case 'target':
        if (state.reviewer) {
          ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.arc(T.px(o.x), T.py(o.y), Math.max(6, o.tol * T.sx), 0, Math.PI * 2); ctx.stroke();
          label(ctx, o.label + ' attendu', T.px(o.x) + 8, T.py(o.y) + 18, color);
        }
        break;
    }
    ctx.restore();
  }

  function drawFunction(ctx, T, f, color, dashed) {
    var r = T.r, steps = Math.max(200, Math.round(r.w * 1.5)), started = false, prev = null;
    ctx.strokeStyle = color; ctx.lineWidth = 2.2; if (dashed) ctx.setLineDash([6, 4]);
    ctx.beginPath();
    for (var i = 0; i <= steps; i++) {
      var X = r.x + i * r.w / steps, x = T.mx(X), y = f(x);
      if (!isFinite(y)) { started = false; prev = null; continue; }
      var Y = T.py(y);
      // Discontinuité (asymptote verticale) : ne pas relier.
      if (prev != null && Math.abs(Y - prev) > r.h * 1.5) started = false;
      if (Y < r.y - r.h || Y > r.y + 2 * r.h) { started = false; prev = Y; continue; }
      if (started) ctx.lineTo(X, Y); else { ctx.moveTo(X, Y); started = true; }
      prev = Y;
    }
    ctx.stroke();
    ctx.setLineDash([]);
  }
  function drawLine(ctx, T, o, color) {
    var a = { x: T.px(o.a.x), y: T.py(o.a.y) }, b = { x: T.px(o.b.x), y: T.py(o.b.y) };
    var dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
    var far = (T.r.w + T.r.h) * 3;
    var p1 = a, p2 = b;
    if (o.sub === 'line') { p1 = { x: a.x - dx / len * far, y: a.y - dy / len * far }; p2 = { x: a.x + dx / len * far, y: a.y + dy / len * far }; }
    if (o.sub === 'ray') p2 = { x: a.x + dx / len * far, y: a.y + dy / len * far };
    ctx.lineWidth = o.dashed ? 1.5 : 2; if (o.dashed) ctx.setLineDash([7, 5]);
    ctx.beginPath(); ctx.moveTo(p1.x, p1.y); ctx.lineTo(p2.x, p2.y); ctx.stroke(); ctx.setLineDash([]);
    if (o.sub === 'vector') { ctx.fillStyle = color; arrowHead(ctx, b.x, b.y, Math.atan2(dy, dx)); }
    var text = o.note || (o.sub === 'segment' && o.measure != null ? o.name + ' = ' + M.fmt(o.measure) : o.sub === 'vector' ? '→' + o.name : '');
    if (o.sub === 'line' && !o.note && /^d\d*$|^[a-z]/.test(o.name || '')) text = '(' + o.name + ')';
    if (text) {
      var anchor = o.sub === 'line' || o.sub === 'ray' ? clampToArea(T, a, dx / len, dy / len) : { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      label(ctx, text, anchor.x + 6, anchor.y - 6, color);
    }
  }
  function clampToArea(T, a, ux, uy) {
    var r = T.r, best = a;
    for (var t = -2000; t <= 2000; t += 20) {
      var p = { x: a.x + ux * t, y: a.y + uy * t };
      if (p.x > r.x + 20 && p.x < r.x + r.w - 140 && p.y > r.y + 20 && p.y < r.y + r.h - 20) best = p;
    }
    return best;
  }
  function drawShade(ctx, T, o, color) {
    var n = 200, top = [], bottom = [];
    for (var i = 0; i <= n; i++) {
      var x = o.a + (o.b - o.a) * i / n, y1 = o.f(x), y2 = o.g ? o.g(x) : 0;
      if (!isFinite(y1) || !isFinite(y2)) continue;
      top.push({ x: T.px(x), y: T.py(y1) }); bottom.push({ x: T.px(x), y: T.py(y2) });
    }
    if (!top.length) return;
    ctx.beginPath();
    top.forEach(function (p, i) { (i ? ctx.lineTo : ctx.moveTo).call(ctx, p.x, p.y); });
    bottom.reverse().forEach(function (p) { ctx.lineTo(p.x, p.y); });
    ctx.closePath(); ctx.globalAlpha = 0.25; ctx.fill(); ctx.globalAlpha = 1;
    var mx = (o.a + o.b) / 2;
    label(ctx, o.note, T.px(mx) - 30, T.py((o.f(mx) + (o.g ? o.g(mx) : 0)) / 2), color);
  }
  function drawPoint(ctx, T, o, color, layout) {
    if (!isFinite(o.x) || !isFinite(o.y)) return;
    var X = T.px(o.x), Y = T.py(o.y), big = !!o.drag;
    if (o.complex) {
      ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(T.px(0), T.py(0)); ctx.lineTo(X, Y); ctx.stroke(); ctx.setLineDash([]);
      var arg = Math.atan2(o.y, o.x);
      ctx.beginPath(); ctx.arc(T.px(0), T.py(0), 22, 0, -arg, arg > 0); ctx.stroke();
    }
    ctx.fillStyle = color; ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(X, Y, big ? 6 : 4.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    var text = o.name;
    if (o.complex) {
      var mod = Math.hypot(o.x, o.y), deg = Math.atan2(o.y, o.x) * 180 / Math.PI;
      text = o.name + ' = ' + complexText(o.x, o.y) + '  |' + o.name + '| = ' + M.fmt(mod) + '  arg ≈ ' + M.fmt(deg, 1) + '°';
    } else if (o.note) text += ' (' + o.note + ')';
    else if (big || o.host) text += '(' + M.fmt(o.x) + ' ; ' + M.fmt(o.y) + ')';
    label(ctx, text, X + 8, Y - 8, color);
    if (o.drag) layout.handles.push({ name: o.name, item: o.item, x: X, y: Y, kind: o.drag, host: o.host });
  }
  function complexText(a, b) {
    if (Math.abs(b) < 1e-9) return M.fmt(a);
    var im = Math.abs(Math.abs(b) - 1) < 1e-9 ? 'i' : M.fmt(Math.abs(b)) + 'i';
    if (Math.abs(a) < 1e-9) return (b < 0 ? '-' : '') + im;
    return M.fmt(a) + (b < 0 ? ' - ' : ' + ') + im;
  }
  function drawTrig(ctx, T, o, color) {
    var cx = T.px(0), cy = T.py(0), rx = T.sx, ry = T.sy;
    var c = Math.cos(o.t), s = Math.sin(o.t), X = T.px(c), Y = T.py(s);
    ctx.lineWidth = 2; ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); ctx.stroke();
    ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(X, Y); ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, 18, 0, -o.t, o.t > 0); ctx.stroke();
    ctx.setLineDash([4, 4]); ctx.strokeStyle = '#2b8a3e';
    ctx.beginPath(); ctx.moveTo(X, Y); ctx.lineTo(X, cy); ctx.stroke();
    ctx.strokeStyle = '#c2255c'; ctx.beginPath(); ctx.moveTo(X, Y); ctx.lineTo(cx, Y); ctx.stroke(); ctx.setLineDash([]);
    ctx.lineWidth = 4;
    ctx.strokeStyle = '#2b8a3e'; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(X, cy); ctx.stroke();
    ctx.strokeStyle = '#c2255c'; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx, Y); ctx.stroke();
    if (Math.abs(c) > 1e-6) {
      var t = s / c, TX = T.px(1), TY = T.py(t);
      ctx.lineWidth = 1; ctx.strokeStyle = '#7048e8';
      ctx.beginPath(); ctx.moveTo(TX, T.r.y); ctx.lineTo(TX, T.r.y + T.r.h); ctx.stroke();
      ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(TX, TY); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = '#7048e8'; ctx.beginPath(); ctx.arc(TX, TY, 4, 0, Math.PI * 2); ctx.fill();
    }
    ctx.fillStyle = color; ctx.beginPath(); ctx.arc(X, Y, 5, 0, Math.PI * 2); ctx.fill();
    var lines = [
      ['t = ' + M.fmtPi(o.t) + ' rad = ' + M.fmt(o.t * 180 / Math.PI, 1) + '°', color],
      ['cos t = ' + M.fmt(c, 3), '#2b8a3e'], ['sin t = ' + M.fmt(s, 3), '#c2255c'],
      ['tan t = ' + (Math.abs(c) > 1e-6 ? M.fmt(s / c, 3) : 'non définie'), '#7048e8'],
    ];
    var bx = T.r.x + T.r.w - 190, by = T.r.y + T.r.h - 92;
    ctx.fillStyle = 'rgba(255,255,255,0.92)'; ctx.fillRect(bx - 8, by - 16, 190, 86);
    lines.forEach(function (l, i) { label(ctx, l[0], bx, by + i * 20, l[1]); });
    label(ctx, 'M', X + 8, Y - 8, color);
  }
  function drawCobweb(ctx, T, o, color) {
    drawFunction(ctx, T, function (x) { return x; }, '#868e96', true);
    var vals = o.vals;
    ctx.strokeStyle = color; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(T.px(vals[0]), T.py(0));
    for (var i = 0; i < vals.length - 1; i++) {
      ctx.lineTo(T.px(vals[i]), T.py(vals[i + 1]));
      ctx.lineTo(T.px(vals[i + 1]), T.py(vals[i + 1]));
    }
    ctx.stroke();
    ctx.font = '11px sans-serif'; ctx.fillStyle = color;
    vals.forEach(function (v, i) {
      if (i > 6) return;
      ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(T.px(v), T.py(0)); ctx.lineTo(T.px(v), T.py(i ? v : 0)); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillText('u' + i, T.px(v) - 6, T.py(0) + 16 + (i % 2) * 11);
    });
    var text = vals.slice(0, 7).map(function (v, i) { return 'u' + i + ' = ' + M.fmt(v, 3); }).join('   ');
    label(ctx, text, T.r.x + 10, T.r.y + T.r.h - 10, color);
  }
  function drawAnswers(ctx, T, scene, state) {
    var answers = state.answers || [];
    if (!answers.length) return;
    var targets = {};
    scene.list.forEach(function (o) { if (o.k === 'target') targets[o.label] = o; });
    var ok = 0, total = 0;
    answers.forEach(function (ans) {
      var t = targets[ans.target];
      if (!t) return;
      if (!state.reviewer && ans.by !== state.me) return;
      var good = Math.hypot(ans.mx - t.x, ans.my - t.y) <= t.tol;
      total++; if (good) ok++;
      var X = T.px(ans.mx), Y = T.py(ans.my);
      ctx.fillStyle = good ? '#2b8a3e' : '#c92a2a'; ctx.strokeStyle = '#fff'; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(X, Y, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      label(ctx, (state.reviewer && ans.byName ? ans.byName + ' : ' : '') + ans.target + (good ? ' ✓' : ' ✗'), X + 8, Y - 8, good ? '#2b8a3e' : '#c92a2a');
    });
    if (state.reviewer && total) label(ctx, 'Réponses : ' + total + ' · justes : ' + ok, T.r.x + 10, T.r.y + T.r.h - 10, '#12306b');
  }

  /* ---------------------------------------------------------- interactions */
  /** Que se passe-t-il si on appuie en p (coordonnées du tableau) ? */
  function hitTest(plot, layout, p) {
    if (!layout) return null;
    var inside = function (b) { return p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h; };
    for (var i = 0; i < layout.buttons.length; i++) if (inside(layout.buttons[i])) return { type: 'button', name: layout.buttons[i].name };
    for (var j = 0; j < layout.sliders.length; j++) {
      var s = layout.sliders[j];
      if (p.x >= s.x - 10 && p.x <= s.x + s.w + 10 && p.y >= s.y && p.y <= s.y + s.h) return { type: 'slider', slider: s };
    }
    var best = null, bestD = 14;
    layout.handles.forEach(function (h) { var d = Math.hypot(p.x - h.x, p.y - h.y); if (d < bestD) { bestD = d; best = h; } });
    if (best) return { type: 'point', handle: best };
    if (p.y >= plot.y && p.y < plot.y + HEADER) return { type: 'header' };
    if (p.x >= plot.x && p.x <= plot.x + plot.w && p.y >= plot.y + HEADER && p.y <= plot.y + plot.h) return { type: 'pan' };
    return null;
  }

  function setLine(item, line) { item.line = line; }
  function rewriteArgs(line, values) {
    var m = /^([\s\S]*?\()([\s\S]*)\)\s*$/.exec(line);
    if (!m) return line;
    var args = splitArgs(m[2]);
    Object.keys(values).forEach(function (k) { args[k] = values[k]; });
    return m[1] + args.join(';') + ')';
  }
  function snap(v, step) {
    var s = step || 0.1, r = Math.round(v / s) * s;
    return round(Math.abs(r - Math.round(r)) < s * 0.6 && Math.abs(v - Math.round(v)) < s * 0.6 ? Math.round(v) : r, 4);
  }

  /** Applique un déplacement. `start` = position du premier appui, `p` = position actuelle. */
  function drag(plot, hit, p, last) {
    var T = mapper(plot);
    if (hit.type === 'slider') {
      var s = hit.slider, ratio = Math.min(1, Math.max(0, (p.x - s.x) / s.w));
      var v = s.min + ratio * (s.max - s.min);
      v = Math.round((v - s.min) / s.step) * s.step + s.min;
      hit.slider.item.val = round(Math.min(s.max, Math.max(s.min, v)), 6);
      return true;
    }
    if (hit.type === 'point') {
      var h = hit.handle, item = h.item, mx = T.mx(p.x), my = T.my(p.y);
      var step = niceStep(T.v.xmax - T.v.xmin, T.r.w) / 10;
      var d = parseLine(item.line);
      if (h.kind === 'free' && d.kind === 'pair') {
        setLine(item, (d.name ? d.name + '=' : '') + '(' + numText(snap(mx, step)) + ';' + numText(snap(my, step)) + ')');
        return true;
      }
      if (h.kind === 'free' && d.kind === 'cmd' && d.cmd === 'complex') {
        setLine(item, rewriteArgs(item.line, { 0: numText(snap(mx, step)), 1: numText(snap(my, step)) }));
        return true;
      }
      if (h.kind === 'on' && d.kind === 'cmd' && d.cmd === 'point') {
        var host = h.host, t;
        if (host.k === 'fn') t = snap(mx, step);
        else if (host.k === 'circle') t = round(Math.atan2(my - host.c.y, mx - host.c.x), 4);
        else {
          var dx = host.b.x - host.a.x, dy = host.b.y - host.a.y;
          t = round(((mx - host.a.x) * dx + (my - host.a.y) * dy) / (dx * dx + dy * dy), 4);
        }
        setLine(item, rewriteArgs(item.line, { 1: numText(t) }));
        return true;
      }
      return false;
    }
    if (hit.type === 'pan' && last) {
      var dxm = (p.x - last.x) / T.sx, dym = (p.y - last.y) / T.sy;
      plot.view.xmin -= dxm; plot.view.xmax -= dxm; plot.view.ymin += dym; plot.view.ymax += dym;
      return true;
    }
    return false;
  }
  function zoom(plot, factor, center) {
    var T = mapper(plot), v = plot.view;
    var cx = center ? T.mx(center.x) : (v.xmin + v.xmax) / 2, cy = center ? T.my(center.y) : (v.ymin + v.ymax) / 2;
    var nx0 = cx + (v.xmin - cx) * factor, nx1 = cx + (v.xmax - cx) * factor;
    if (nx1 - nx0 < 1e-3 || nx1 - nx0 > 1e5) return false;
    v.xmin = nx0; v.xmax = nx1;
    v.ymin = cy + (v.ymin - cy) * factor; v.ymax = cy + (v.ymax - cy) * factor;
    return true;
  }
  function resetView(plot) { if (plot.home) plot.view = Object.assign({}, plot.home); }
  /** Coordonnées mathématiques d'un point du tableau (pour la réponse d'un élève). */
  function toMath(plot, p) { var T = mapper(plot); return { x: round(T.mx(p.x), 3), y: round(T.my(p.y), 3) }; }
  function fromMath(plot, m) { var T = mapper(plot); return { x: T.px(m.x), y: T.py(m.y) }; }
  /** Positions des points mobiles (pour enregistrer une trace pendant le déplacement). */
  function pointPositions(plot) {
    var scene = evalScene(plot), out = {};
    scene.list.forEach(function (o) { if (o.k === 'point') out[o.name] = { x: o.x, y: o.y }; });
    return { points: out, traced: scene.list.filter(function (o) { return o.k === 'trace'; }).map(function (o) { return o.of; }) };
  }

  /** Commande d'insertion pour les boutons de l'éditeur (modèles). */
  var SNIPPETS = [
    ['Fonction', 'f(x)=x^2-2x-3'], ['Fonction par morceaux', 'g(x)=si(x<0; -x; x^2)'], ['Fonction sur [a ; b]', 'h(x)=sqrt(x) [0;9]'],
    ['Curseur', 'a=Curseur(-5;5;0.1;1)'], ['Point', 'A=(1;2)'], ['Point sur f', 'M=Point(f;1)'],
    ['Dérivée', "Dérivée(f)"], ['Tangente', 'T=Tangente(f;M)'], ['Racines', 'Racines(f)'], ['Extremums', 'Extremums(f)'],
    ['Asymptotes', 'Asymptotes(f)'], ['Intersection', 'Intersection(f;g)'], ['Intégrale', 'Intégrale(f;0;2)'], ['Aire entre courbes', 'Aire(f;g;0;2)'],
    ['Droite', 'd=Droite(A;B)'], ['Segment', 'Segment(A;B)'], ['Demi-droite', 'DemiDroite(A;B)'], ['Vecteur', 'u=Vecteur(A;B)'],
    ['Cercle', 'Cercle(A;2)'], ['Polygone', 'p=Polygone(A;B;C)'], ['Milieu', 'I=Milieu(A;B)'],
    ['Perpendiculaire', 'Perpendiculaire(d;C)'], ['Parallèle', 'Parallèle(d;C)'], ['Médiatrice', 'Médiatrice(A;B)'], ['Bissectrice', 'Bissectrice(A;B;C)'],
    ['Distance', 'Distance(A;B)'], ['Angle', 'Angle(A;B;C)'], ['Aire polygone', 'Aire(p)'],
    ['Translation', 'Translation(p;u)'], ['Symétrie centrale', 'Symétrie(p;A)'], ['Symétrie axiale', 'Symétrie(p;d)'],
    ['Homothétie', 'Homothétie(p;A;2)'], ['Rotation', 'Rotation(p;A;90)'], ['Barycentre', 'G=Barycentre(A;1;B;2)'],
    ['Lieu', 'Lieu(I;M)'], ['Trace', 'Trace(M)'], ['Cercle trigonométrique', 'CercleTrigo(pi/3)'], ['Suite', 'Suite(f;0;6)'],
    ['Complexe', 'z=Complexe(2;1)'], ['Texte', 'Texte("Remarque" ; A)'], ['Exercice : placer', 'Placer(A;2;3)'],
  ];

  return {
    HEADER: HEADER, PALETTE: PALETTE, PRESETS: PRESETS, SNIPPETS: SNIPPETS,
    parseLine: parseLine, evalScene: evalScene, effectiveView: effectiveView, mapper: mapper,
    defaultPlot: defaultPlot, render: render, hitTest: hitTest, drag: drag, zoom: zoom, resetView: resetView,
    toMath: toMath, fromMath: fromMath, pointPositions: pointPositions, splitArgs: splitArgs, rewriteArgs: rewriteArgs,
  };
});
