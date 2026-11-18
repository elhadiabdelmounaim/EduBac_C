/**
 * EduBac — tableau de variations / de signes et arbre de probabilités.
 *
 * Tableau (objet « vartable »), une ligne par rangée, cellules séparées par « ; » :
 *   x     : -∞ ; -1 ; 1 ; +∞
 *   f'(x) : + ; 0 ; - ; 0 ; +            (signes : 2n-1 cellules, « || » = valeur interdite)
 *   f     : -∞ ; ↗ ; 3 ; ↘ ; -1 ; ↗ ; +∞  (variations : valeurs et flèches ↗ ↘, ou / \)
 *
 * Arbre (objet « probtree »), indentation de deux espaces par niveau :
 *   A : 0,3
 *     B : 0,6
 *     non B : 0,4
 */
(function (root, factory) {
  var api = factory(root.EduBacMath || (typeof require === 'function' ? require('./whiteboard-math.js') : null));
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.EduBacTables = api;
})(typeof window !== 'undefined' ? window : globalThis, function (M) {
  'use strict';
  var fail = function (m) { throw new M.MathError(m); };
  var UP = /^(↗|\/|croissante|monte|up)$/i, DOWN = /^(↘|\\|décroissante|decroissante|descend|down)$/i;

  /* ================================================== tableau de variations */
  function parseTable(text) {
    var lines = String(text || '').split('\n').map(function (l) { return l.trim(); }).filter(Boolean);
    if (lines.length < 2) fail('Il faut au moins la ligne des x et une autre ligne.');
    if (lines.length > 8) fail('8 lignes au maximum.');
    var rows = lines.map(function (line) {
      var idx = line.indexOf(':');
      if (idx < 0) fail('Chaque ligne commence par son nom suivi de « : » (ex. « x : -∞ ; 2 ; +∞ »).');
      var cells = line.slice(idx + 1).split(';').map(function (c) { return pretty(c.trim()); });
      return { label: pretty(line.slice(0, idx).trim()), cells: cells };
    });
    var xs = rows[0].cells;
    if (xs.length < 2 || xs.length > 9) fail('La ligne des x doit avoir entre 2 et 9 valeurs.');
    var n = xs.length;
    rows.slice(1).forEach(function (row) {
      row.kind = row.cells.some(function (c) { return UP.test(c) || DOWN.test(c); }) ? 'var' : 'sign';
      // Ligne de signes écrite sans les cases vides aux bornes : « + ; 0 ; - ».
      if (row.kind === 'sign' && row.cells.length === 2 * n - 3) row.cells = [''].concat(row.cells, ['']);
      if (row.cells.length !== 2 * n - 1) {
        fail('La ligne « ' + row.label + ' » doit avoir ' + (2 * n - 1) + ' cellules (valeurs et intervalles alternés) : elle en a ' + row.cells.length + '.');
      }
    });
    return { xs: xs, rows: rows.slice(1), label: rows[0].label };
  }
  function pretty(s) {
    return s.replace(/-inf(ini)?/gi, '-∞').replace(/\+inf(ini)?/gi, '+∞').replace(/^inf(ini)?$/i, '+∞')
      .replace(/sqrt\(([^)]*)\)/g, '√$1').replace(/pi/g, 'π').replace(/\./g, ',');
  }

  function layoutTable(o, ctx) {
    var t = parseTable(o.text), n = t.xs.length;
    ctx.font = '15px serif';
    var labelW = Math.max(56, Math.max.apply(null, [t.label].concat(t.rows.map(function (r) { return r.label; })).map(function (s) { return ctx.measureText(s).width + 20; })));
    var colW = Math.max(56, Math.max.apply(null, t.xs.concat.apply(t.xs, t.rows.map(function (r) { return r.cells; })).map(function (s) { return ctx.measureText(s).width + 26; })));
    var heights = [34].concat(t.rows.map(function (r) { return r.kind === 'var' ? 96 : 34; }));
    return { t: t, n: n, labelW: labelW, colW: colW, heights: heights, w: labelW + colW * (n - 1) + colW * 0.6, h: heights.reduce(function (a, b) { return a + b; }, 0) };
  }

  function renderTable(ctx, o) {
    var L;
    try { L = layoutTable(o, ctx); }
    catch (err) {
      ctx.save(); ctx.fillStyle = '#c92a2a'; ctx.font = '14px sans-serif';
      ctx.fillText('Tableau : ' + err.message, o.x, o.y + 16);
      ctx.restore(); o._width = 420; o._height = 24; return;
    }
    o._width = L.w; o._height = L.h;
    var x0 = o.x, y0 = o.y, color = o.color || '#12306b';
    var colX = function (i) { return x0 + L.labelW + L.colW * 0.3 + i * L.colW; };
    ctx.save();
    ctx.fillStyle = '#ffffff'; ctx.fillRect(x0, y0, L.w, L.h);
    ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.strokeRect(x0, y0, L.w, L.h);
    ctx.beginPath(); ctx.moveTo(x0 + L.labelW, y0); ctx.lineTo(x0 + L.labelW, y0 + L.h); ctx.stroke();
    var y = y0;
    ctx.fillStyle = '#263449'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.font = 'italic 15px serif';
    ctx.fillText(L.t.label, x0 + L.labelW / 2, y + L.heights[0] / 2);
    ctx.font = '15px serif';
    L.t.xs.forEach(function (v, i) { ctx.fillText(v, colX(i), y + L.heights[0] / 2); });
    y += L.heights[0];
    L.t.rows.forEach(function (row, r) {
      var h = L.heights[r + 1];
      ctx.strokeStyle = color; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x0 + L.w, y); ctx.stroke();
      ctx.fillStyle = '#263449'; ctx.font = 'italic 15px serif';
      ctx.fillText(row.label, x0 + L.labelW / 2, y + h / 2);
      ctx.font = '15px serif';
      if (row.kind === 'sign') drawSignRow(ctx, row, colX, L, y, h, color);
      else drawVarRow(ctx, row, colX, L, y, h, color);
      y += h;
    });
    ctx.restore();
  }
  function drawSignRow(ctx, row, colX, L, y, h, color) {
    row.cells.forEach(function (c, k) {
      var mid = y + h / 2;
      if (k % 2 === 0) { // valeur en x_i : 0, || ou vide
        var X = colX(k / 2);
        if (c === '||') doubleBar(ctx, X, y, h, color);
        else if (c) {
          ctx.strokeStyle = '#adb5bd'; ctx.setLineDash([3, 3]);
          if (k > 0 && k < row.cells.length - 1) { ctx.beginPath(); ctx.moveTo(X, y); ctx.lineTo(X, y + h); ctx.stroke(); }
          ctx.setLineDash([]); ctx.fillStyle = '#263449';
          ctx.fillStyle = '#ffffff'; ctx.fillRect(X - 8, mid - 9, 16, 18); ctx.fillStyle = '#263449'; ctx.fillText(c, X, mid);
        }
      } else {
        var Xm = (colX((k - 1) / 2) + colX((k + 1) / 2)) / 2;
        ctx.fillStyle = c === '+' ? '#2b8a3e' : c === '-' || c === '−' ? '#c92a2a' : '#263449';
        ctx.font = 'bold 17px serif'; ctx.fillText(c === '-' ? '−' : c, Xm, mid); ctx.font = '15px serif';
      }
    });
  }
  function drawVarRow(ctx, row, colX, L, y, h, color) {
    var cells = row.cells, top = y + 16, bottom = y + h - 16, pos = [];
    // Hauteur de chaque valeur : haut si on y arrive en montant ou si on en repart en descendant.
    for (var i = 0; i < cells.length; i += 2) {
      var before = cells[i - 1] || '', after = cells[i + 1] || '';
      var high = UP.test(before) || DOWN.test(after);
      var low = DOWN.test(before) || UP.test(after);
      pos.push(high && !low ? 'top' : low && !high ? 'bottom' : high ? 'top' : 'middle');
    }
    var at = function (i, part) {
      var c = cells[i];
      var parts = c.split('||');
      var X = colX(i / 2), Y = pos[i / 2] === 'top' ? top : pos[i / 2] === 'bottom' ? bottom : (top + bottom) / 2;
      if (parts.length === 2) {
        // Valeur interdite : limite à gauche | limite à droite (hauteurs déduites des flèches voisines).
        var leftY = DOWN.test(cells[i - 1] || '') ? bottom : top, rightY = UP.test(cells[i + 1] || '') ? bottom : top;
        return part === 'left' ? { x: X - 12, y: leftY, text: parts[0] } : part === 'right' ? { x: X + 12, y: rightY, text: parts[1] } : null;
      }
      return { x: X, y: Y, text: c };
    };
    for (var k = 0; k < cells.length; k += 2) {
      if (cells[k].indexOf('||') >= 0) {
        doubleBar(ctx, colX(k / 2), y, h, color);
        ['left', 'right'].forEach(function (side) { var p = at(k, side); if (p.text) whiteText(ctx, p.text, p.x + (side === 'left' ? -10 : 10), p.y); });
      } else if (cells[k]) {
        var p = at(k); whiteText(ctx, p.text, p.x, p.y);
      }
    }
    for (var j = 1; j < cells.length; j += 2) {
      var up = UP.test(cells[j]), down = DOWN.test(cells[j]);
      if (!up && !down) continue;
      var a = cells[j - 1].indexOf('||') >= 0 ? at(j - 1, 'right') : at(j - 1), b = cells[j + 1].indexOf('||') >= 0 ? at(j + 1, 'left') : at(j + 1);
      var x1 = a.x + 18, x2 = b.x - 18, y1 = up ? bottom - 4 : top + 4, y2 = up ? top + 4 : bottom - 4;
      ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1.6;
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
      var ang = Math.atan2(y2 - y1, x2 - x1);
      ctx.beginPath(); ctx.moveTo(x2, y2); ctx.lineTo(x2 - 9 * Math.cos(ang - 0.4), y2 - 9 * Math.sin(ang - 0.4));
      ctx.lineTo(x2 - 9 * Math.cos(ang + 0.4), y2 - 9 * Math.sin(ang + 0.4)); ctx.closePath(); ctx.fill();
    }
  }
  function whiteText(ctx, text, x, y) {
    var w = ctx.measureText(text).width;
    ctx.fillStyle = '#ffffff'; ctx.fillRect(x - w / 2 - 3, y - 10, w + 6, 20);
    ctx.fillStyle = '#263449'; ctx.fillText(text, x, y);
  }
  function doubleBar(ctx, X, y, h, color) {
    ctx.strokeStyle = color; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(X - 2, y); ctx.lineTo(X - 2, y + h); ctx.moveTo(X + 2, y); ctx.lineTo(X + 2, y + h); ctx.stroke();
  }

  /**
   * Tableau de variations calculé : f sur [a ; b] (bornes affichées), points
   * critiques (extremums) et valeurs interdites (asymptotes verticales).
   */
  function generateTable(fn, name, a, b, options) {
    options = options || {};
    var extrema = M.extrema(fn, a, b).map(function (e) { return e.x; });
    var poles = M.asymptotes(fn, a, b).filter(function (s) { return s.kind === 'v' && s.x > a && s.x < b; }).map(function (s) { return s.x; });
    var xs = [a].concat(extrema, poles, [b]).sort(function (p, q) { return p - q; });
    xs = xs.filter(function (v, i) { return !i || Math.abs(v - xs[i - 1]) > 1e-6; });
    var isPole = function (x) { return poles.some(function (p) { return Math.abs(p - x) < 1e-6; }); };
    var df = M.derivative(fn, 1);
    var leftLabel = options.minusInfinity ? '-∞' : M.fmt(a), rightLabel = options.plusInfinity ? '+∞' : M.fmt(b);
    var xRow = xs.map(function (x, i) { return i === 0 ? leftLabel : i === xs.length - 1 ? rightLabel : M.fmt(x); });
    var sign = [], vari = [];
    var valueAt = function (x, i) {
      if (isPole(x)) {
        var l = fn(x - 1e-7), r = fn(x + 1e-7);
        return limitText(l) + '||' + limitText(r);
      }
      if (i === 0 && options.minusInfinity) return limitText(fn(-1e7));
      if (i === xs.length - 1 && options.plusInfinity) return limitText(fn(1e7));
      var v = fn(x);
      return isFinite(v) ? M.fmt(v) : '';
    };
    xs.forEach(function (x, i) {
      sign.push(isPole(x) ? '||' : (i > 0 && i < xs.length - 1 ? '0' : ''));
      vari.push(valueAt(x, i));
      if (i < xs.length - 1) {
        var mid = (x + xs[i + 1]) / 2, s = df(mid);
        sign.push(s > 0 ? '+' : s < 0 ? '-' : '0');
        vari.push(s > 0 ? '↗' : s < 0 ? '↘' : '→');
      }
    });
    return 'x : ' + xRow.join(' ; ') + '\n' + name + "'(x) : " + sign.slice(1, -1).join(' ; ') + '\n' + name + ' : ' + vari.join(' ; ');
  }
  function limitText(v) {
    if (!isFinite(v) || Math.abs(v) > 1e5) return v > 0 ? '+∞' : '-∞';
    return M.fmt(v);
  }

  /* =================================================== arbre de probabilités */
  function parseTree(text) {
    var lines = String(text || '').split('\n').filter(function (l) { return l.trim(); });
    if (!lines.length) fail('Écrivez au moins une branche, par exemple « A : 0,3 ».');
    if (lines.length > 40) fail('40 branches au maximum.');
    var rootNode = { children: [], depth: -1 }, stack = [rootNode];
    lines.forEach(function (line) {
      var indent = line.replace(/\t/g, '  ').match(/^ */)[0].length, depth = Math.floor(indent / 2);
      var m = /^\s*([^:]+?)\s*:\s*(.+?)\s*$/.exec(line);
      if (!m) fail('Format « événement : probabilité » attendu : « ' + line.trim() + ' ».');
      while (stack.length > 1 && stack[stack.length - 1].depth >= depth) stack.pop();
      var parent = stack[stack.length - 1];
      if (depth > parent.depth + 1) fail('Indentation trop grande à « ' + line.trim() + ' ».');
      var node = { label: eventLabel(m[1]), raw: m[2].replace(',', '.'), depth: depth, children: [] };
      node.p = probability(node.raw);
      parent.children.push(node); stack.push(node);
    });
    return rootNode;
  }
  function eventLabel(s) {
    var t = s.trim();
    var neg = /^(non|not)\s+(.+)$/i.exec(t);
    if (neg) return neg[2].split('').map(function (c) { return c + '̄'; }).join('');
    return t;
  }
  function probability(raw) {
    try { var v = M.evaluate(M.parse(raw), {}); return isFinite(v) ? v : null; } catch (e) { return null; }
  }
  function renderTree(ctx, o) {
    var tree;
    try { tree = parseTree(o.text); }
    catch (err) {
      ctx.save(); ctx.fillStyle = '#c92a2a'; ctx.font = '14px sans-serif'; ctx.fillText('Arbre : ' + err.message, o.x, o.y + 16); ctx.restore();
      o._width = 420; o._height = 24; return;
    }
    var leaves = 0, depthMax = 0;
    (function count(node, d) {
      if (!node.children.length && d >= 0) { leaves++; }
      depthMax = Math.max(depthMax, d);
      node.children.forEach(function (c) { count(c, d + 1); });
    })(tree, -1);
    var rowH = 46, colW = 150, w = (depthMax + 1) * colW + 170, h = Math.max(1, leaves) * rowH + 20;
    o._width = w; o._height = h;
    var color = o.color || '#12306b', leafIndex = 0;
    ctx.save();
    ctx.fillStyle = '#ffffff'; ctx.fillRect(o.x, o.y, w, h);
    ctx.font = '15px serif'; ctx.textBaseline = 'middle';
    function place(node, d) {
      if (!node.children.length) { node.y = o.y + 10 + rowH * (leafIndex++ + 0.5); }
      else {
        node.children.forEach(function (c) { place(c, d + 1); });
        node.y = (node.children[0].y + node.children[node.children.length - 1].y) / 2;
      }
      node.x = o.x + 14 + (d + 1) * colW;
    }
    tree.children.forEach(function (c) { place(c, 0); });
    tree.x = o.x + 14; tree.y = tree.children.length ? (tree.children[0].y + tree.children[tree.children.length - 1].y) / 2 : o.y + h / 2;
    function draw(node, path) {
      var sum = node.children.reduce(function (s, c) { return s + (c.p == null ? NaN : c.p); }, 0);
      var bad = node.children.length && isFinite(sum) && Math.abs(sum - 1) > 1e-9;
      node.children.forEach(function (c) {
        ctx.strokeStyle = color; ctx.lineWidth = 1.4;
        ctx.beginPath(); ctx.moveTo(node.x + (node === tree ? 0 : 22), node.y); ctx.lineTo(c.x - 8, c.y); ctx.stroke();
        var mx = (node.x + c.x) / 2, my = (node.y + c.y) / 2;
        ctx.textAlign = 'center';
        var pText = c.p != null && !/[a-z]/i.test(c.raw) ? M.fmtExact(c.p) : c.raw;
        ctx.fillStyle = '#ffffff'; var tw = ctx.measureText(pText).width; ctx.fillRect(mx - tw / 2 - 3, my - 10, tw + 6, 20);
        ctx.fillStyle = bad ? '#c92a2a' : '#7048e8'; ctx.fillText(pText, mx, my);
        ctx.fillStyle = '#263449'; ctx.textAlign = 'left'; ctx.font = 'bold 15px serif'; ctx.fillText(c.label, c.x - 4, c.y); ctx.font = '15px serif';
        var nextPath = path.concat([c]);
        if (c.children.length) draw(c, nextPath);
        else {
          var prod = nextPath.reduce(function (s, n) { return n.p == null ? NaN : s * n.p; }, 1);
          var name = 'P(' + nextPath.map(function (n) { return n.label; }).join(' ∩ ') + ')';
          ctx.fillStyle = '#495057';
          ctx.fillText(isFinite(prod) ? name + ' = ' + M.fmt(prod, 4) : name, c.x + 30, c.y);
        }
      });
      if (bad) { ctx.fillStyle = '#c92a2a'; ctx.font = '12px sans-serif'; ctx.fillText('somme ≠ 1', node.x - 10, node.y + 18); ctx.font = '15px serif'; }
    }
    draw(tree, []);
    ctx.restore();
  }

  return { parseTable: parseTable, renderTable: renderTable, generateTable: generateTable, parseTree: parseTree, renderTree: renderTree };
});
