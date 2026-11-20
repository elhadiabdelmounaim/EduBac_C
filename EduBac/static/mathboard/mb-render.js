/* Tableau mathématique — couche d'intégration entre les moteurs.
 *
 * Répartition des rôles (aucune fonction n'est implémentée deux fois) :
 *   Fabric.js : dessin libre, formes, texte, images, sélection, calques, zoom.
 *   MathJax   : rendu des formules LaTeX (objets « math », tableaux de variations).
 *   JSXGraph  : toute construction géométrique et toute courbe (objets « geometry »).
 *   SymPy     : calcul exact côté serveur (asymptotes, variations, résolutions).
 *
 * Un objet mathématique est stocké sous sa forme source (LaTeX ou script de
 * construction) ; Fabric n'en reçoit qu'un rendu SVG. L'objet reste donc
 * modifiable (double-clic) et identique chez tous les participants.
 */
(function (root) {
  'use strict';
  var MB = root.MB = root.MB || {};

  var TYPE_MAP = { IText: 'i-text', Textbox: 'textbox', FabricImage: 'image', Image: 'image', Rect: 'rect',
    Circle: 'circle', Ellipse: 'ellipse', Triangle: 'triangle', Line: 'line', Polyline: 'polyline',
    Polygon: 'polygon', Path: 'path', Group: 'group', Text: 'text' };
  var SPECIAL = { math: true, geometry: true };
  var GEOMETRY_PROPS = ['left', 'top', 'scaleX', 'scaleY', 'angle', 'flipX', 'flipY', 'opacity'];

  function svgDataUrl(svg) {
    return 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svg)));
  }

  /* ---------------- MathJax ---------------- */
  var mathReady = null;
  function mathjax() {
    if (!mathReady) {
      mathReady = new Promise(function (resolve, reject) {
        var start = Date.now();
        (function wait() {
          if (root.MathJax && root.MathJax.tex2svgPromise && root.MathJax.startup && root.MathJax.startup.promise) {
            root.MathJax.startup.promise.then(resolve, reject);
          } else if (Date.now() - start > 20000) {
            reject(new Error('MathJax indisponible'));
          } else {
            setTimeout(wait, 50);
          }
        })();
      });
    }
    return mathReady;
  }

  function latexToSvg(latex, color, fontSize) {
    fontSize = fontSize || 28;
    return mathjax().then(function () {
      return root.MathJax.tex2svgPromise(latex, { display: true });
    }).then(function (node) {
      var svg = node.querySelector('svg');
      if (!svg) throw new Error('Formule illisible.');
      var error = node.querySelector('[data-mjx-error]');
      if (error) throw new Error(error.getAttribute('data-mjx-error') || 'Formule LaTeX invalide.');
      var exToPx = fontSize * 0.5;
      var width = parseFloat(svg.getAttribute('width')) * exToPx;
      var height = parseFloat(svg.getAttribute('height')) * exToPx;
      svg.setAttribute('width', width.toFixed(2));
      svg.setAttribute('height', height.toFixed(2));
      svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      svg.removeAttribute('style');
      // Traits des tableaux (\\hline, |) : stylés par la feuille CSS de MathJax, absente
      // d'une image SVG autonome. On les écrit en attributs.
      Array.prototype.forEach.call(svg.querySelectorAll('line'), function (line) {
        line.setAttribute('stroke', 'currentColor');
        line.setAttribute('stroke-width', line.getAttribute('stroke-width') || '60');
        if (line.hasAttribute('stroke-dasharray') === false && line.getAttribute('data-line') === 'dashed') line.setAttribute('stroke-dasharray', '140');
      });
      var text = new XMLSerializer().serializeToString(svg).replace(/currentColor/g, color || '#1f2937');
      return { svg: text, width: width, height: height };
    });
  }

  /* ---------------- Tableau de variations (données SymPy → LaTeX) ---------------- */
  function vartableLatex(table) {
    var points = table.points, n = points.length;
    var fx = table['function'] + '(x)', fpx = table['function'] + "'(x)";
    var cols = [];   // 2n-1 colonnes : points et intervalles alternés
    for (var i = 0; i < n; i++) {
      cols.push({ point: i });
      if (i < n - 1) cols.push({ interval: i });
    }
    function level(i) {   // position d'une valeur : haut / bas
      var before = i > 0 ? table.arrows[i - 1] : null, after = i < n - 1 ? table.arrows[i] : null;
      if (before === 'up' && after !== 'up') return 'top';
      if (before === 'down' && after !== 'down') return 'bottom';
      if (!before) return after === 'down' ? 'top' : 'bottom';
      return before === 'up' ? 'top' : 'bottom';
    }
    var forbidden = table.forbidden || [];
    var rowX = [table.variable], rowS = [fpx], rowTop = [fx], rowMid = [''], rowBottom = [''];
    cols.forEach(function (col) {
      if (col.point !== undefined) {
        var i = col.point, p = points[i], v = table.values[i];
        var isForbidden = forbidden.indexOf(p) >= 0 || (v && v.forbidden);
        rowX.push(p === '\\infty' ? '+\\infty' : p);
        rowS.push(isForbidden ? '\\Vert' : (i === 0 || i === n - 1 ? '' : (table.signs[i - 1] !== table.signs[i] ? '0' : '')));
        if (isForbidden) {
          var leftTop = table.arrows[i - 1] === 'up', rightTop = table.arrows[i] === 'down';
          var cellTop = (leftTop ? fix(v.left) : '') + '\\,\\Vert\\,' + (rightTop ? fix(v.right) : '');
          var cellBottom = (!leftTop ? fix(v.left) : '') + '\\,\\Vert\\,' + (!rightTop ? fix(v.right) : '');
          rowTop.push(cellTop); rowMid.push('\\Vert'); rowBottom.push(cellBottom);
        } else {
          var where = level(i), value = fix(v.value);
          rowTop.push(where === 'top' ? value : ''); rowMid.push(''); rowBottom.push(where === 'bottom' ? value : '');
        }
      } else {
        var k = col.interval, sign = table.signs[k], arrow = table.arrows[k];
        rowX.push(''); rowS.push(sign === '||' ? '' : sign);
        rowTop.push(''); rowBottom.push('');
        rowMid.push(arrow === 'up' ? '\\nearrow' : arrow === 'down' ? '\\searrow' : arrow === 'flat' ? '\\rightarrow' : '');
      }
    });
    function fix(v) { return v === '\\infty' ? '+\\infty' : (v || ''); }
    var spec = 'c|' + cols.map(function () { return 'c'; }).join('');
    return '\\begin{array}{' + spec + '}' + rowX.join(' & ') + ' \\\\ \\hline ' + rowS.join(' & ') +
      ' \\\\ \\hline ' + rowTop.join(' & ') + ' \\\\ ' + rowMid.join(' & ') + ' \\\\ ' + rowBottom.join(' & ') +
      ' \\end{array}';
  }

  /* ---------------- JSXGraph : langage de construction ---------------- */
  var COLORS = { rouge: '#e03131', bleu: '#1971c2', vert: '#2f9e44', orange: '#f08c00', noir: '#212529',
    violet: '#9c36b5', gris: '#868e96', red: '#e03131', blue: '#1971c2', green: '#2f9e44', black: '#212529' };
  var COMMANDS = {
    point: 'point', segment: 'segment', droite: 'line', line: 'line', demidroite: 'ray', ray: 'ray',
    cercle: 'circle', circle: 'circle', polygone: 'polygon', polygon: 'polygon', triangle: 'polygon',
    angle: 'angle', vecteur: 'vector', vector: 'vector', milieu: 'midpoint', midpoint: 'midpoint',
    perpendiculaire: 'perpendicular', perpendicular: 'perpendicular', parallele: 'parallel', 'parallèle': 'parallel',
    parallel: 'parallel', intersection: 'intersection', intersect: 'intersection', tangente: 'tangent',
    tangent: 'tangent', verticale: 'vertical', vertical: 'vertical', texte: 'text', text: 'text',
  };

  function splitArgs(text) {
    var out = [], depth = 0, cur = '';
    for (var i = 0; i < text.length; i++) {
      var ch = text[i];
      if (ch === '(' || ch === '[') depth++;
      if (ch === ')' || ch === ']') depth--;
      if ((ch === ',' || ch === ';') && depth === 0) { out.push(cur.trim()); cur = ''; } else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }

  function number(src) {
    var value = root.EduBacMath.evaluate(root.EduBacMath.parse(String(src)), { vars: {} });
    if (typeof value !== 'number' || !isFinite(value)) throw new Error('Nombre attendu : « ' + src + ' ».');
    return value;
  }

  /* Construit le script sur un tableau JSXGraph. Renvoie {errors, objects}. */
  function buildGeometry(board, script, options) {
    options = options || {};
    var env = {}, errors = [], lines = String(script || '').split('\n');
    function get(name, kind) {
      var obj = env[name.trim()];
      if (!obj) throw new Error('« ' + name.trim() + ' » n’est pas défini.');
      if (kind && obj.mbKind !== kind && !(kind === 'line' && obj.mbKind === 'segment')) {
        throw new Error('« ' + name.trim() + ' » n’est pas ' + (kind === 'point' ? 'un point' : kind === 'curve' ? 'une fonction' : 'une droite') + '.');
      }
      return obj;
    }
    function pointArg(text) {
      text = text.trim();
      var m = /^\((.*)\)$/.exec(text);
      if (m) { var xy = splitArgs(m[1]); return board.create('point', [number(xy[0]), number(xy[1])], { visible: false, name: '' }); }
      return get(text, 'point');
    }
    lines.forEach(function (raw, index) {
      var line = raw.replace(/#.*$/, '').trim();
      if (!line) return;
      try {
        var style = {}, sm = /\[([^\]]*)\]\s*$/.exec(line);
        if (sm) {
          line = line.slice(0, sm.index).trim();
          sm[1].split(/[,\s]+/).forEach(function (word) {
            word = word.toLowerCase();
            if (COLORS[word]) style.strokeColor = style.fillColor = COLORS[word];
            if (word === 'pointillé' || word === 'pointille' || word === 'dashed') style.dash = 2;
            if (word === 'épais' || word === 'epais' || word === 'thick') style.strokeWidth = 3;
          });
        }
        var fn = /^([A-Za-z][\w']*)\s*\(\s*x\s*\)\s*=\s*(.+)$/.exec(line);
        if (fn) {
          var compiled = root.EduBacMath.compileFunction(fn[2], {}, 'x');
          var curve = board.create('functiongraph', [function (x) { var y = compiled(x); return isFinite(y) ? y : NaN; }],
            Object.assign({ name: fn[1], withLabel: false, strokeWidth: 2, strokeColor: '#1971c2' }, style));
          curve.mbKind = 'curve'; curve.mbFn = compiled; env[fn[1]] = curve;
          return;
        }
        var assign = /^([A-Za-z][\w']*)\s*=\s*(.+)$/.exec(line);
        var name = assign ? assign[1] : '', expr = assign ? assign[2].trim() : line;
        var coords = /^\(([^()]*)\)$/.exec(expr);
        if (coords) {
          var xy = splitArgs(coords[1]);
          if (xy.length !== 2) throw new Error('Un point s’écrit A = (x, y).');
          var p = board.create('point', [number(xy[0]), number(xy[1])],
            Object.assign({ name: name, size: 3, strokeColor: '#d9480f', fillColor: '#d9480f', fixed: !options.interactive,
              label: { offset: [6, 6] } }, style));
          p.mbKind = 'point'; p.mbLine = index;
          if (name) env[name] = p;
          return;
        }
        var call = /^([A-Za-zéè]+)\s*\((.*)\)$/.exec(expr);
        if (!call) throw new Error('Commande non reconnue.');
        var kind = COMMANDS[call[1].toLowerCase()];
        if (!kind) throw new Error('Commande inconnue : ' + call[1] + '.');
        var args = splitArgs(call[2]);
        var attrs = Object.assign({ name: name, withLabel: !!name && kind !== 'segment', strokeWidth: 2,
          strokeColor: '#343a40', label: { offset: [6, 6] } }, style);
        var obj;
        if (kind === 'segment' || kind === 'line' || kind === 'ray' || kind === 'vector') {
          var A = pointArg(args[0]), B = pointArg(args[1]);
          if (kind === 'ray') attrs.straightFirst = false;
          if (kind === 'vector') attrs.lastArrow = true;
          obj = board.create(kind === 'line' || kind === 'ray' ? 'line' : kind === 'vector' ? 'arrow' : 'segment', [A, B], attrs);
          obj.mbKind = kind === 'line' || kind === 'ray' ? 'line' : 'segment';
        } else if (kind === 'circle') {
          var center = pointArg(args[0]);
          var second = /^[A-Za-z][\w']*$/.test(args[1]) && env[args[1]] ? pointArg(args[1]) : number(args[1]);
          obj = board.create('circle', [center, second], Object.assign(attrs, { withLabel: false }));
          obj.mbKind = 'circle';
        } else if (kind === 'polygon') {
          var pts = args.map(pointArg);
          if (pts.length < 3) throw new Error('Il faut au moins trois points.');
          obj = board.create('polygon', pts, Object.assign(attrs, { withLabel: false, fillOpacity: 0.12,
            fillColor: style.fillColor || '#4dabf7', borders: { strokeColor: style.strokeColor || '#343a40', strokeWidth: 2 } }));
          obj.mbKind = 'polygon';
        } else if (kind === 'angle') {
          obj = board.create('angle', [pointArg(args[0]), pointArg(args[1]), pointArg(args[2])],
            Object.assign(attrs, { radius: 0.8, fillColor: '#ffd43b', fillOpacity: 0.4, withLabel: true,
              name: function () { return (obj ? (obj.Value() * 180 / Math.PI).toFixed(1).replace('.', ',') : '') + '°'; } }));
          obj.mbKind = 'angle';
        } else if (kind === 'midpoint') {
          obj = board.create('midpoint', [pointArg(args[0]), pointArg(args[1])],
            Object.assign(attrs, { size: 3, strokeColor: '#2f9e44', fillColor: '#2f9e44' }));
          obj.mbKind = 'point';
        } else if (kind === 'perpendicular' || kind === 'parallel') {
          obj = board.create(kind, [get(args[1], 'line'), pointArg(args[0])], Object.assign(attrs, { dash: style.dash || 0 }));
          obj.mbKind = 'line';
        } else if (kind === 'intersection') {
          obj = board.create('intersection', [get(args[0]), get(args[1]), args[2] ? number(args[2]) : 0],
            Object.assign(attrs, { size: 3, strokeColor: '#9c36b5', fillColor: '#9c36b5' }));
          obj.mbKind = 'point';
        } else if (kind === 'tangent') {
          var f = get(args[0], 'curve'), a = number(args[1]);
          var y0 = f.mbFn(a), slope = root.EduBacMath.derivative(f.mbFn, 1)(a);
          if (!isFinite(y0) || !isFinite(slope)) throw new Error('Pas de tangente en ce point.');
          obj = board.create('line', [[a, y0], [a + 1, y0 + slope]], Object.assign(attrs, { strokeColor: style.strokeColor || '#e03131' }));
          obj.mbKind = 'line';
        } else if (kind === 'vertical') {
          var x0 = number(args[0]);
          obj = board.create('line', [[x0, 0], [x0, 1]], Object.assign(attrs, { dash: style.dash === undefined ? 2 : style.dash,
            strokeColor: style.strokeColor || '#e03131', withLabel: false }));
          obj.mbKind = 'line';
        } else if (kind === 'text') {
          var at = pointArg(args[0]);
          var label = args.slice(1).join(', ').replace(/^["«\s]+|["»\s]+$/g, '');
          obj = board.create('text', [at.X() + 0.1, at.Y() + 0.1, label], { fontSize: 16, strokeColor: style.strokeColor || '#212529' });
          obj.mbKind = 'text';
        } else {
          obj = board.create('point', args.map(number), attrs);
          obj.mbKind = 'point';
        }
        if (name) env[name] = obj;
      } catch (error) {
        errors.push({ line: index + 1, message: error.message || String(error) });
      }
    });
    return { errors: errors, objects: env };
  }

  function boardAttributes(view, interactive) {
    return { boundingbox: [view.xmin, view.ymax, view.xmax, view.ymin], axis: view.axes !== false,
      grid: view.grid !== false, showNavigation: false, showCopyright: false, keepAspectRatio: false,
      pan: { enabled: !!interactive }, zoom: { enabled: !!interactive, wheel: !!interactive, needShift: false },
      defaultAxes: { x: { ticks: { label: { fontSize: 12 } } }, y: { ticks: { label: { fontSize: 12 } } } } };
  }

  function geometryToSvg(model) {
    var JXG = root.JXG;
    if (!JXG) return Promise.reject(new Error('JSXGraph indisponible.'));
    JXG.Options.text.display = 'internal';
    var width = model.width || 480, height = model.height || 360;
    var host = document.createElement('div');
    host.style.cssText = 'position:fixed;left:-10000px;top:0;width:' + width + 'px;height:' + height + 'px;';
    host.id = 'mbOffscreen' + Math.random().toString(36).slice(2);
    document.body.appendChild(host);
    try {
      var board = JXG.JSXGraph.initBoard(host.id, boardAttributes(model.view || { xmin: -5, xmax: 5, ymin: -4, ymax: 4 }, false));
      var result = buildGeometry(board, model.script || '', { interactive: false });
      board.update();
      var svg = board.renderer.svgRoot.cloneNode(true);
      svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
      svg.setAttribute('width', width);
      svg.setAttribute('height', height);
      svg.style.background = '#ffffff';
      var bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      bg.setAttribute('width', '100%'); bg.setAttribute('height', '100%'); bg.setAttribute('fill', '#ffffff');
      bg.setAttribute('stroke', '#ced4da');
      svg.insertBefore(bg, svg.firstChild);
      var text = new XMLSerializer().serializeToString(svg);
      JXG.JSXGraph.freeBoard(board);
      return Promise.resolve({ svg: text, width: width, height: height, errors: result.errors });
    } catch (error) {
      return Promise.reject(error);
    } finally {
      host.remove();
    }
  }

  /* ---------------- Modèle ↔ Fabric ---------------- */
  function renderSpecial(model) {
    if (model.type === 'math') return latexToSvg(model.latex || '', model.color, model.fontSize);
    return geometryToSvg(model);
  }

  function toFabric(model) {
    var fabric = root.fabric;
    var base = { id: model.id, z: model.z || 0 };
    if (SPECIAL[model.type]) {
      return renderSpecial(model).catch(function (error) {
        var fallback = '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="40"><rect width="220" height="40" fill="#fff5f5" stroke="#e03131"/>' +
          '<text x="8" y="25" font-family="sans-serif" font-size="13" fill="#c92a2a">Formule à corriger</text></svg>';
        return { svg: fallback, width: 220, height: 40, error: error.message };
      }).then(function (rendered) {
        return fabric.FabricImage.fromURL(svgDataUrl(rendered.svg)).then(function (img) {
          var mb = {};
          Object.keys(model).forEach(function (k) { if (GEOMETRY_PROPS.indexOf(k) < 0 && k !== 'id' && k !== 'z' && k.charAt(0) !== '_') mb[k] = model[k]; });
          img.set(Object.assign({ left: model.left || 0, top: model.top || 0, scaleX: model.scaleX || 1, scaleY: model.scaleY || 1,
            angle: model.angle || 0, flipX: !!model.flipX, flipY: !!model.flipY, opacity: model.opacity === undefined ? 1 : model.opacity }, base));
          img.mb = mb;
          img.mbError = rendered.error || '';
          return img;
        });
      });
    }
    var data = Object.assign({}, model);
    Object.keys(data).forEach(function (k) { if (k.charAt(0) === '_') delete data[k]; });
    return fabric.util.enlivenObjects([data]).then(function (objects) {
      var obj = objects[0];
      obj.set(base);
      return obj;
    });
  }

  function fromFabric(obj) {
    if (obj.mb && SPECIAL[obj.mb.type]) {
      var model = Object.assign({ id: obj.id, z: obj.z || 0 }, obj.mb);
      GEOMETRY_PROPS.forEach(function (k) { model[k] = obj[k]; });
      return round(model);
    }
    var data = obj.toObject(['id', 'z']);
    data.type = TYPE_MAP[data.type] || String(data.type).toLowerCase();
    delete data.version;
    return round(data);
  }

  function round(model) {
    Object.keys(model).forEach(function (k) {
      if (typeof model[k] === 'number') model[k] = Math.round(model[k] * 1000) / 1000;
    });
    return model;
  }

  MB.Render = {
    mathjax: mathjax, latexToSvg: latexToSvg, vartableLatex: vartableLatex, buildGeometry: buildGeometry,
    boardAttributes: boardAttributes, geometryToSvg: geometryToSvg, toFabric: toFabric, fromFabric: fromFabric,
    svgDataUrl: svgDataUrl, SPECIAL: SPECIAL, TYPE_MAP: TYPE_MAP,
  };
})(window);
