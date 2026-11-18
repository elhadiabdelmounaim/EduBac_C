/**
 * EduBac — moteur mathématique du tableau blanc (sans dépendance, sans eval).
 *
 * 1. Expressions : analyse sûre (aucun code exécuté), notation des élèves :
 *    2x, x², √(x), ln, e^x, f'(x), si(x<0 ; -x ; x²), π…
 * 2. Scène d'un repère : liste de commandes en français (à la GeoGebra),
 *    évaluées dans l'ordre : fonctions, curseurs, points, constructions,
 *    mesures, transformations, analyse (racines, extremums, asymptotes,
 *    tangente, intégrale), cercle trigonométrique, suites, complexes, exercices.
 * 3. Rendu canvas + interactions (déplacer un point, un curseur, le repère).
 * 4. Tableau de variations / de signes et arbre de probabilités.
 *
 * L'état d'un repère est sérialisable tel quel (liste de commandes texte) :
 * il se synchronise comme n'importe quel élément du tableau.
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EduBacMath = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function MathError(message) { this.message = message; this.name = 'MathError'; }
  MathError.prototype = Object.create(Error.prototype);
  MathError.prototype.constructor = MathError;
  function fail(message) { throw new MathError(message); }

  /* ====================================================================
   * 1. Expressions
   * ==================================================================== */
  var SUPERSCRIPTS = { '²': '^2', '³': '^3', '⁴': '^4', '¹': '^1', '⁰': '^0' };

  function normalizeSource(src) {
    var s = String(src == null ? '' : src);
    if (s.length > 2000) fail('Expression trop longue.');
    s = s.replace(/Math\./g, '')
      .replace(/\*\*/g, '^')
      .replace(/[−–]/g, '-').replace(/[×·]/g, '*').replace(/÷/g, '/')
      .replace(/π/g, '(pi)').replace(/√(\d+(?:\.\d+)?|[A-Za-z])/g, 'sqrt($1)').replace(/√/g, 'sqrt').replace(/∞/g, 'inf')
      .replace(/≤/g, '<=').replace(/≥/g, '>=').replace(/≠/g, '!=')
      .replace(/[²³⁴¹⁰]/g, function (c) { return SUPERSCRIPTS[c]; });
    return s;
  }

  function tokenize(src) {
    var s = normalizeSource(src), tokens = [], i = 0;
    while (i < s.length) {
      var c = s[i];
      if (/\s/.test(c)) { i++; continue; }
      if (/[0-9.]/.test(c)) {
        var m = /^(\d+\.?\d*|\.\d+)(e[+-]?\d+)?/i.exec(s.slice(i));
        if (!m) fail('Nombre mal écrit près de « ' + s.slice(i, i + 6) + ' ».');
        tokens.push({ t: 'num', v: parseFloat(m[0]) }); i += m[0].length; continue;
      }
      if (/[A-Za-zÀ-ÿ_]/.test(c)) {
        var id = /^[A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ_0-9]*/.exec(s.slice(i))[0];
        i += id.length;
        var primes = 0;
        while (s[i] === "'") { primes++; i++; }
        tokens.push({ t: 'id', v: id, primes: primes }); continue;
      }
      if (c === '"') {
        var end = s.indexOf('"', i + 1);
        if (end < 0) fail('Guillemet non fermé.');
        tokens.push({ t: 'str', v: s.slice(i + 1, end) }); i = end + 1; continue;
      }
      var two = s.slice(i, i + 2);
      if (['<=', '>=', '==', '!=', '&&', '||'].indexOf(two) >= 0) { tokens.push({ t: 'op', v: two }); i += 2; continue; }
      if ('+-*/^(),;<>=[]!'.indexOf(c) >= 0) { tokens.push({ t: 'op', v: c === ';' ? ',' : c }); i++; continue; }
      fail('Caractère non reconnu : « ' + c + ' ».');
    }
    return tokens;
  }

  // Grammaire : comparaison > addition > multiplication (implicite comprise) > unaire > puissance > appel/atome.
  function parse(src) {
    var tokens = tokenize(src), pos = 0;
    if (!tokens.length) fail('Expression vide.');
    function peek() { return tokens[pos]; }
    function isOp(v) { var t = tokens[pos]; return t && t.t === 'op' && t.v === v; }
    function expect(v) { if (!isOp(v)) fail('« ' + v + ' » attendu.'); pos++; }

    function parseOr() {
      var left = parseAnd();
      while (isOp('||')) { pos++; left = { k: 'bin', op: '||', a: left, b: parseAnd() }; }
      return left;
    }
    function parseAnd() {
      var left = parseCompare();
      while (isOp('&&')) { pos++; left = { k: 'bin', op: '&&', a: left, b: parseCompare() }; }
      return left;
    }
    function parseCompare() {
      var left = parseAdd();
      while (peek() && peek().t === 'op' && ['<', '>', '<=', '>=', '==', '!=', '='].indexOf(peek().v) >= 0) {
        var op = tokens[pos++].v;
        left = { k: 'bin', op: op === '=' ? '==' : op, a: left, b: parseAdd() };
      }
      return left;
    }
    function parseAdd() {
      var left = parseMul();
      while (isOp('+') || isOp('-')) { var op = tokens[pos++].v; left = { k: 'bin', op: op, a: left, b: parseMul() }; }
      return left;
    }
    function startsAtom(t) { return t && (t.t === 'num' || t.t === 'id' || (t.t === 'op' && t.v === '(')); }
    function parseMul() {
      var left = parseUnary();
      for (;;) {
        if (isOp('*') || isOp('/')) { var op = tokens[pos++].v; left = { k: 'bin', op: op, a: left, b: parseUnary() }; continue; }
        if (startsAtom(peek())) { left = { k: 'bin', op: '*', a: left, b: parsePow() }; continue; } // 2x, 3(x+1), x(x-1)
        return left;
      }
    }
    function parseUnary() {
      if (isOp('-')) { pos++; return { k: 'neg', a: parseUnary() }; }
      if (isOp('+')) { pos++; return parseUnary(); }
      if (isOp('!')) { pos++; return { k: 'not', a: parseUnary() }; }
      return parsePow();
    }
    function parsePow() {
      var base = parseAtom();
      if (isOp('^')) { pos++; return { k: 'bin', op: '^', a: base, b: parseUnary() }; }
      return base;
    }
    function parseArgs() {
      var args = [];
      if (isOp(')')) { pos++; return args; }
      for (;;) {
        args.push(parseOr());
        if (isOp(',')) { pos++; continue; }
        expect(')'); return args;
      }
    }
    function parseAtom() {
      var t = tokens[pos];
      if (!t) fail('Expression incomplète.');
      if (t.t === 'num') { pos++; return { k: 'num', v: t.v }; }
      if (t.t === 'str') { pos++; return { k: 'str', v: t.v }; }
      if (t.t === 'id') {
        pos++;
        if (isOp('(')) { pos++; return { k: 'call', name: t.v, primes: t.primes, args: parseArgs() }; }
        return { k: 'id', name: t.v, primes: t.primes };
      }
      if (isOp('(')) {
        pos++;
        var first = parseOr();
        if (isOp(',')) { // (x ; y) : couple
          pos++; var second = parseOr(); expect(')');
          return { k: 'pair', a: first, b: second };
        }
        expect(')'); return first;
      }
      if (isOp('|')) fail('Utilisez abs(...) pour la valeur absolue.');
      fail('Symbole inattendu : « ' + t.v + ' ».');
    }
    var ast = parseOr();
    if (pos < tokens.length) fail('Symbole inattendu : « ' + tokens[pos].v + ' ».');
    return ast;
  }

  var CONSTANTS = { pi: Math.PI, e: Math.E, inf: Infinity };
  var FUNCS = {
    sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos, atan: Math.atan,
    arcsin: Math.asin, arccos: Math.acos, arctan: Math.atan,
    sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh,
    sqrt: Math.sqrt, racine: Math.sqrt, abs: Math.abs, exp: Math.exp,
    ln: Math.log, log: function (v) { return Math.log(v) / Math.LN10; }, log10: function (v) { return Math.log(v) / Math.LN10; },
    floor: Math.floor, E: Math.floor, ent: Math.floor, ceil: Math.ceil, round: Math.round,
    sign: Math.sign, signe: Math.sign, cbrt: Math.cbrt,
    min: Math.min, max: Math.max, pow: Math.pow,
    mod: function (a, b) { return ((a % b) + b) % b; },
    // Combinatoire (probabilités) : factorielle, arrangements, combinaisons.
    fact: factorial, factorielle: factorial,
    C: function (n, k) { return combination(n, k); }, comb: function (n, k) { return combination(n, k); },
    A: function (n, k) { return factorial(n) / factorial(n - k); },
  };
  function factorial(n) {
    if (n < 0 || n !== Math.floor(n) || n > 170) return NaN;
    var r = 1; for (var i = 2; i <= n; i++) r *= i; return r;
  }
  function combination(n, k) {
    if (k < 0 || k > n || n !== Math.floor(n) || k !== Math.floor(k)) return 0;
    k = Math.min(k, n - k); var r = 1;
    for (var i = 1; i <= k; i++) r = r * (n - k + i) / i;
    return Math.round(r);
  }

  /** Dérivée numérique d'ordre n (différences centrées). */
  function derivative(fn, order) {
    if (!order) return fn;
    var prev = derivative(fn, order - 1);
    return function (x) {
      var h = 1e-4 * Math.max(1, Math.abs(x));
      var v = (prev(x + h) - prev(x - h)) / (2 * h);
      return isFinite(v) ? v : NaN;
    };
  }

  /**
   * Évalue un arbre. `scope` :
   *   vars : { nom: nombre }      (x, curseurs, nombres nommés)
   *   fns  : { nom: function(x) } (fonctions de la scène)
   *   points : { A: {x, y} }      (pour x(A), y(A))
   */
  function evaluate(node, scope) {
    scope = scope || {};
    switch (node.k) {
      case 'num': return node.v;
      case 'str': fail('Texte inattendu dans un calcul.');
      // falls through
      case 'neg': return -evaluate(node.a, scope);
      case 'not': return evaluate(node.a, scope) ? 0 : 1;
      case 'pair': fail('Un couple (x ; y) n’est pas un nombre.');
      // falls through
      case 'id': {
        var name = node.name;
        if (node.primes) fail('Écrire ' + name + "'(x) pour la dérivée.");
        if (scope.vars && Object.prototype.hasOwnProperty.call(scope.vars, name)) return scope.vars[name];
        if (Object.prototype.hasOwnProperty.call(CONSTANTS, name)) return CONSTANTS[name];
        if (name === 'i') fail('Pour un nombre complexe, utilisez Complexe(a ; b).');
        fail('Nom inconnu : « ' + name + ' »' + (/^[a-z]{2,}$/.test(name) ? ' (écrire par exemple a*x au lieu de ax)' : '') + '.');
      }
      // falls through
      case 'call': {
        var args = node.args;
        var fname = node.name;
        if (fname === 'si' || fname === 'if') {
          if (args.length < 2) fail('si(condition ; valeur_si_vrai ; valeur_si_faux)');
          return evaluate(args[0], scope) ? evaluate(args[1], scope) : (args.length > 2 ? evaluate(args[2], scope) : NaN);
        }
        if ((fname === 'x' || fname === 'y') && args.length === 1 && args[0].k === 'id' && scope.points && scope.points[args[0].name]) {
          return scope.points[args[0].name][fname];
        }
        if (scope.fns && Object.prototype.hasOwnProperty.call(scope.fns, fname)) {
          if (args.length !== 1) fail(fname + ' attend une seule valeur.');
          return derivative(scope.fns[fname], node.primes || 0)(evaluate(args[0], scope));
        }
        if (Object.prototype.hasOwnProperty.call(FUNCS, fname) && !node.primes) {
          var values = args.map(function (a) { return evaluate(a, scope); });
          return FUNCS[fname].apply(null, values);
        }
        // a(x+1) avec a nombre : multiplication implicite.
        if (args.length === 1 && !node.primes) return evaluate({ k: 'id', name: fname }, scope) * evaluate(args[0], scope);
        fail('Fonction inconnue : « ' + fname + ' ».');
      }
      // falls through
      case 'bin': {
        var op = node.op;
        if (op === '&&') return evaluate(node.a, scope) && evaluate(node.b, scope) ? 1 : 0;
        if (op === '||') return evaluate(node.a, scope) || evaluate(node.b, scope) ? 1 : 0;
        var a = evaluate(node.a, scope), b = evaluate(node.b, scope);
        switch (op) {
          case '+': return a + b;
          case '-': return a - b;
          case '*': return a * b;
          case '/': return a / b;
          case '^':
            if (a < 0 && b !== Math.floor(b)) {
              // Racine impaire d'un négatif : x^(1/3)
              var inv = 1 / b;
              if (Math.abs(inv - Math.round(inv)) < 1e-9 && Math.round(inv) % 2) return -Math.pow(-a, b);
            }
            return Math.pow(a, b);
          case '<': return a < b ? 1 : 0;
          case '>': return a > b ? 1 : 0;
          case '<=': return a <= b ? 1 : 0;
          case '>=': return a >= b ? 1 : 0;
          case '==': return Math.abs(a - b) < 1e-12 ? 1 : 0;
          case '!=': return Math.abs(a - b) >= 1e-12 ? 1 : 0;
        }
      }
    }
    fail('Expression invalide.');
  }

  /** Liste des noms libres utilisés (pour signaler une variable inconnue). */
  function compileFunction(src, scope, variable) {
    var ast = typeof src === 'string' ? parse(src) : src;
    var v = variable || 'x';
    var vars = Object.assign({}, scope && scope.vars);
    var local = { vars: vars, fns: scope && scope.fns, points: scope && scope.points };
    var fn = function (x) {
      vars[v] = x;
      try { var r = evaluate(ast, local); return typeof r === 'number' ? r : NaN; }
      catch (e) { return NaN; }
    };
    // Vérifie les noms une fois (x = 1) pour signaler les erreurs de saisie.
    vars[v] = 1.2345;
    evaluate(ast, local);
    return fn;
  }

  /* ====================================================================
   * Outils numériques
   * ==================================================================== */
  function bisect(f, a, b) {
    var fa = f(a);
    for (var i = 0; i < 60; i++) {
      var m = (a + b) / 2, fm = f(m);
      if (!isFinite(fm)) return NaN;
      if ((fa < 0) === (fm < 0)) { a = m; fa = fm; } else b = m;
    }
    return (a + b) / 2;
  }
  /** Zéros de f sur [a ; b] : changements de signe + zéros « tangents » (minimum de |f| proche de 0). */
  function zeros(f, a, b, samples) {
    var n = samples || 600, result = [], prevX = a, prevY = f(a);
    var step = (b - a) / n;
    for (var i = 1; i <= n; i++) {
      var x = a + i * step, y = f(x);
      if (isFinite(prevY) && isFinite(y)) {
        if (prevY === 0) result.push(prevX);
        else if ((prevY < 0) !== (y < 0) && y !== 0) {
          var r = bisect(f, prevX, x);
          // Écarter les discontinuités (1/x en 0) : |f| doit être petit au point trouvé.
          if (isFinite(r) && Math.abs(f(r)) < 1e-6 * Math.max(1, Math.abs(prevY), Math.abs(y))) result.push(r);
        }
      }
      prevX = x; prevY = y;
    }
    if (isFinite(prevY) && prevY === 0) result.push(prevX);
    // Zéros doubles (x² en 0) : minimum local de |f| très proche de 0.
    var g = function (x) { return Math.abs(f(x)); };
    for (var j = 1; j < n; j++) {
      var x0 = a + (j - 1) * step, x1 = a + j * step, x2 = a + (j + 1) * step;
      var g0 = g(x0), g1 = g(x1), g2 = g(x2);
      if (g1 <= g0 && g1 <= g2 && g1 < 1e-3 * Math.max(1, (b - a))) {
        var m = golden(g, x0, x2);
        if (g(m) < 1e-7 && !result.some(function (r) { return Math.abs(r - m) < step; })) result.push(m);
      }
    }
    return dedupe(result.sort(function (p, q) { return p - q; }), step / 2);
  }
  function golden(f, a, b) {
    var gr = (Math.sqrt(5) - 1) / 2, c = b - gr * (b - a), d = a + gr * (b - a);
    for (var i = 0; i < 80; i++) {
      if (f(c) < f(d)) b = d; else a = c;
      c = b - gr * (b - a); d = a + gr * (b - a);
    }
    return (a + b) / 2;
  }
  function dedupe(list, eps) {
    var out = [];
    list.forEach(function (v) { if (!out.length || Math.abs(v - out[out.length - 1]) > eps) out.push(v); });
    return out;
  }
  function integral(f, a, b) {
    if (a === b) return 0;
    var n = 1000, h = (b - a) / n, s = f(a) + f(b);
    for (var i = 1; i < n; i++) s += (i % 2 ? 4 : 2) * f(a + i * h);
    return s * h / 3;
  }
  /** Extremums locaux : changements de signe de f'. */
  function extrema(f, a, b) {
    var df = derivative(f, 1), result = [];
    zeros(df, a, b, 600).forEach(function (x) {
      var h = (b - a) / 400, left = df(x - h), right = df(x + h);
      if (!isFinite(f(x))) return;
      if (left > 0 && right < 0) result.push({ x: x, y: f(x), kind: 'max' });
      else if (left < 0 && right > 0) result.push({ x: x, y: f(x), kind: 'min' });
    });
    return result;
  }
  /** Asymptotes : verticales (explosion entre deux échantillons), horizontales, obliques. */
  function asymptotes(f, a, b) {
    var out = [], n = 800, step = (b - a) / n, big = 1e6;
    var xs = [], ys = [];
    for (var i = 0; i <= n; i++) { xs.push(a + i * step); ys.push(f(a + i * step)); }
    // Candidats : changement de signe, valeur non définie, ou maximum local de |f|
    // (pôle d'ordre pair comme 1/x², sans changement de signe).
    var candidates = [];
    for (var k = 0; k < n; k++) {
      var y0 = ys[k], y1 = ys[k + 1];
      if (isNaN(y0) && isNaN(y1)) continue; // hors du domaine des deux côtés
      if (!isFinite(y0) || !isFinite(y1) || (y0 < 0) !== (y1 < 0)) candidates.push([xs[k], xs[k + 1]]);
      if (k > 0 && isFinite(y0) && Math.abs(y0) >= Math.abs(ys[k - 1]) && Math.abs(y0) >= Math.abs(y1) && Math.abs(y0) > 10) {
        candidates.push([xs[k - 1], xs[k + 1]]);
      }
    }
    candidates.forEach(function (span) {
      var c = golden(function (x) { var v = Math.abs(f(x)); return isFinite(v) ? -v : -1e300; }, span[0], span[1]);
      // Confirmation : f explose des deux côtés (une racine ou un maximum lisse est écarté).
      // NaN = hors du domaine (ln, √) : ce n'est pas une explosion.
      var blows = function (v) { return v === Infinity || v === -Infinity || (isFinite(v) && Math.abs(v) > big); };
      var right = f(c + 1e-7), left = f(c - 1e-7);
      var okRight = blows(right), okLeft = blows(left);
      // Bord du domaine (ln en 0) : divergence lente mais régulière en s'approchant du bord.
      var slowEdge = function (side) {
        var v1 = Math.abs(f(c + side * 1e-9)), v2 = Math.abs(f(c + side * 1e-5)), v3 = Math.abs(f(c + side * 1e-3));
        return isFinite(v1) && isFinite(v2) && isFinite(v3) && v1 > v2 && v2 > v3 && v1 - v3 > 8;
      };
      var edge = (isNaN(left) && (okRight || slowEdge(1))) || (isNaN(right) && (okLeft || slowEdge(-1)));
      if (!((okRight && okLeft) || edge)) return;
      var rounded = roundNice(c);
      if (!out.some(function (o) { return o.kind === 'v' && Math.abs(o.x - rounded) < step * 2; })) out.push({ kind: 'v', x: rounded });
    });
    [1, -1].forEach(function (side) {
      var X1 = side * 1e6, X2 = side * 1e8, y1 = f(X1), y2 = f(X2);
      if (!isFinite(y1) || !isFinite(y2)) return;
      var a1 = y1 / X1, a2 = y2 / X2;
      if (Math.abs(a2) < 1e-4 && Math.abs(y2 - y1) < 1e-2 * Math.max(1, Math.abs(y2))) {
        var hb = roundNice(y2);
        if (!out.some(function (o) { return o.kind === 'h' && Math.abs(o.b - hb) < 1e-6; })) out.push({ kind: 'h', b: hb, side: side });
        return;
      }
      if (Math.abs(a2 - a1) < 1e-3 * Math.max(1, Math.abs(a2))) {
        var slope = roundNice(a2), b1 = y1 - slope * X1, b2 = y2 - slope * X2;
        if (Math.abs(b2 - b1) < 1e-2 * Math.max(1, Math.abs(b2)) && Math.abs(slope) > 1e-6) {
          var ob = roundNice(b2);
          if (!out.some(function (o) { return o.kind === 'o' && Math.abs(o.a - slope) < 1e-6 && Math.abs(o.b - ob) < 1e-6; })) out.push({ kind: 'o', a: slope, b: ob, side: side });
        }
      }
    });
    return out;
  }
  function roundNice(v) {
    var r = Math.round(v * 1e4) / 1e4;
    return Math.abs(r - Math.round(r)) < 1e-4 ? Math.round(r) : r;
  }

  /* ====================================================================
   * Affichage des nombres (virgule française, π, fractions simples)
   * ==================================================================== */
  function fmt(v, digits) {
    if (v === Infinity) return '+∞';
    if (v === -Infinity) return '-∞';
    if (!isFinite(v)) return '?';
    var d = digits == null ? 2 : digits;
    var r = Math.round(v * Math.pow(10, d)) / Math.pow(10, d);
    if (Object.is(r, -0)) r = 0;
    return String(r).replace('.', ',');
  }
  function fmtPi(v) {
    var k = v / Math.PI, frac = toFraction(k, 12);
    if (frac && Math.abs(k) > 1e-9) {
      var n = frac[0], d = frac[1], sign = n < 0 ? '-' : '';
      n = Math.abs(n);
      return sign + (n === 1 ? '' : n) + 'π' + (d === 1 ? '' : '/' + d);
    }
    return fmt(v);
  }
  function toFraction(v, maxDen) {
    for (var d = 1; d <= (maxDen || 12); d++) {
      var n = Math.round(v * d);
      if (Math.abs(n / d - v) < 1e-9) return [n, d];
    }
    return null;
  }
  function fmtExact(v) {
    var f = toFraction(v, 12);
    if (f) return f[1] === 1 ? String(f[0]) : f[0] + '/' + f[1];
    return fmt(v);
  }
  function fmtLine(m, p) {
    var mText = Math.abs(m) < 1e-9 ? '' : (Math.abs(m - 1) < 1e-9 ? 'x' : Math.abs(m + 1) < 1e-9 ? '-x' : fmt(m) + 'x');
    if (!mText) return 'y = ' + fmt(p);
    if (Math.abs(p) < 1e-9) return 'y = ' + mText;
    return 'y = ' + mText + (p < 0 ? ' - ' + fmt(-p) : ' + ' + fmt(p));
  }

  return {
    MathError: MathError, parse: parse, evaluate: evaluate, compileFunction: compileFunction,
    derivative: derivative, zeros: zeros, integral: integral, extrema: extrema, asymptotes: asymptotes,
    fmt: fmt, fmtPi: fmtPi, fmtExact: fmtExact, fmtLine: fmtLine, FUNCS: FUNCS,
    _internal: { tokenize: tokenize, bisect: bisect, golden: golden, combination: combination, factorial: factorial, roundNice: roundNice },
  };
});
