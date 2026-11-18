// Tests du moteur mathématique du tableau blanc (node --test).
const test = require('node:test');
const assert = require('node:assert/strict');
const M = require('../../static/js/whiteboard-math.js');
const P = require('../../static/js/whiteboard-plot.js');
const T = require('../../static/js/whiteboard-tables.js');

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≠ ${b}`);
const ev = (s, vars) => M.evaluate(M.parse(s), { vars: Object.assign({ x: 2 }, vars), fns: { f: (x) => x * x } });
function scene(lines, extra) {
  const plot = P.defaultPlot(0, 0);
  plot.items = lines.map((line, i) => Object.assign({ id: 'i' + i, line, color: '#000' }, (extra || {})[i]));
  return { plot, s: P.evalScene(plot) };
}

test('écritures des élèves', () => {
  near(ev('2x+1'), 5); near(ev('x²-1'), 3); near(ev('3(x+1)'), 9); near(ev('(x+1)(x-1)'), 3);
  near(ev('-x^2'), -4); near(ev('√(x+2)'), 2); near(ev('√2*√2'), 2); near(ev('2πx/2'), 2 * Math.PI);
  near(ev('ln(e)'), 1); near(ev('log(100)'), 2); near(ev('si(x<0;-x;x²)'), 4); near(ev("f'(3)"), 6, 1e-4);
  near(ev('Math.pow(x,3)'), 8); near(ev('a(x+1)', { a: 2 }), 6); near(ev('C(5;2)'), 10); near(ev('(-8)^(1/3)'), -2);
});

test('aucun code exécuté, messages clairs', () => {
  for (const bad of ['constructor', 'this.alert(1)', 'x=>x', '1 # 2', 'ax+1']) {
    assert.throws(() => ev(bad), M.MathError, bad);
  }
  assert.throws(() => ev('ax+1'), /a\*x/);
});

test('analyse : racines, extremums, asymptotes, intégrale', () => {
  assert.deepEqual(M.zeros(M.compileFunction('x^2-2'), -5, 5).map((v) => +v.toFixed(6)), [-1.414214, 1.414214]);
  assert.equal(M.zeros(M.compileFunction('(x-1)^2'), -5, 5).length, 1);
  assert.equal(M.zeros(M.compileFunction('1/x'), -5, 5).length, 0);
  assert.deepEqual(M.extrema(M.compileFunction('x^3-3x'), -5, 5).map((e) => [e.kind, +e.x.toFixed(4)]), [['max', -1], ['min', 1]]);
  assert.deepEqual(M.asymptotes(M.compileFunction('(x^2+1)/x'), -5, 5).map((a) => a.kind), ['v', 'o']);
  near(M.integral(M.compileFunction('x^2'), 0, 3), 9);
});

test('géométrie et transformations', () => {
  const { s } = scene(['A=(0;0)', 'B=(4;0)', 'C=(0;3)', 'Distance(B;C)', 'Angle(B;A;C)', 'p=Polygone(A;B;C)', 'Aire(p)',
    'G=Barycentre(A;1;B;1;C;1)', 'd=Droite(A;B)', 'c=Cercle(A;2)', 'Intersection(c;d)', 'Symétrie(C;d)', 'Rotation(B;A;90)', 'Homothétie(B;A;0.5)']);
  assert.deepEqual(s.errors, {});
  near(s.objs.dist1.v, 5); near(s.objs['α1'].v, 90); near(s.objs.aire1.v, 6);
  near(s.objs.G.x, 4 / 3); near(s.objs.I1.x, -2); near(s.objs.I2.x, 2);
  near(s.objs["C'"].y, -3); near(s.objs["B'"].y, 4); near(s.objs["B''"].x, 2);
});

test('fonctions : tangente, intégrale réutilisable, curseurs, domaine', () => {
  const { s } = scene(['a=Curseur(-3;3;0.1;2)', 'f(x)=a x^2-1', 'T=Tangente(f;1)', 'Intégrale(f;0;1)', 'k=3*S1', 'g(x)=ln(x) [1;5]', 'Racines(x^2+1)']);
  assert.deepEqual(s.errors, {});
  assert.equal(s.objs.T.note, 'T : y = 4x - 3');
  near(s.objs.k.v, 3 * (2 / 3 - 1));
  assert.ok(Number.isNaN(s.objs.g.f(0.5)));
  assert.match(s.infos.i6, /Aucune racine/);
});

test('glisser un point ou un curseur réécrit la commande', () => {
  const { plot } = scene(['A=(1;2)', 'f(x)=x^2', 'M=Point(f;1)', 'a=Curseur(0;10;1;3)']);
  const ctx = fakeCtx();
  const layout = P.render(ctx, plot, {});
  const handleA = layout.handles.find((h) => h.name === 'A');
  const target = P.fromMath(plot, { x: 3, y: -1 });
  assert.ok(P.drag(plot, { type: 'point', handle: handleA }, target));
  assert.equal(plot.items[0].line, 'A=(3;-1)');
  const handleM = layout.handles.find((h) => h.name === 'M');
  P.drag(plot, { type: 'point', handle: handleM }, P.fromMath(plot, { x: 2, y: 0 }));
  assert.equal(plot.items[2].line, 'M=Point(f;2)');
  const slider = layout.sliders[0];
  P.drag(plot, { type: 'slider', slider }, { x: slider.x + slider.w, y: slider.y });
  assert.equal(plot.items[3].val, 10);
});

test('lieu, suite, cercle trigonométrique, complexes, exercice', () => {
  for (const key of Object.keys(P.PRESETS)) {
    const s = P.evalScene(P.defaultPlot(0, 0, key));
    assert.deepEqual(s.errors, {}, key);
  }
  const lieu = P.evalScene(P.defaultPlot(0, 0, 'lieu')).objs.L1;
  assert.ok(lieu.pts.filter(Boolean).length > 100);
  const suite = P.evalScene(P.defaultPlot(0, 0, 'suite')).objs.u;
  near(suite.vals[1], Math.sqrt(2));
  const z = P.evalScene(P.defaultPlot(0, 0, 'complexe')).objs["z'"];
  near(z.x, -1); near(z.y, 2); assert.equal(z.complex, true);
});

test('tableau de variations et arbre', () => {
  const text = T.generateTable(M.compileFunction('x^3-3x'), 'f', -3, 3);
  assert.equal(text, "x : -3 ; -1 ; 1 ; 3\nf'(x) : + ; 0 ; - ; 0 ; +\nf : -18 ; ↗ ; 2 ; ↘ ; -2 ; ↗ ; 18");
  assert.deepEqual(T.parseTable(text).rows.map((r) => r.kind), ['sign', 'var']);
  assert.match(T.generateTable(M.compileFunction('1/(x-1)'), 'g', -3, 3), /\|\|/);
  assert.throws(() => T.parseTable('x : 1 ; 2\nf : + ; 0 ; +; 0'), /cellules/);
  const tree = T.parseTree('A : 0,3\n  B : 0,6\n  non B : 0,4\nnon A : 0,7\n  B : 1/5\n  non B : 4/5');
  assert.equal(tree.children[1].label, 'Ā');
  near(tree.children[1].children[0].p, 0.2);
});

function fakeCtx() {
  const noop = () => {};
  return new Proxy({ measureText: (t) => ({ width: String(t).length * 7 }) }, {
    get: (target, key) => (key in target ? target[key] : noop),
    set: (target, key, value) => { target[key] = value; return true; },
  });
}
