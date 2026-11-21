/* Livre 3D : un livre ouvert posé sur un bureau. Page de gauche = leçon (HTML projeté
   avec CSS3DRenderer), page de droite = figures en papier qui se dressent, dessinées à l'encre.
   Three.js r160 (static/vendor/three), sans autre dépendance. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS3DRenderer, CSS3DObject } from 'three/addons/renderers/CSS3DRenderer.js';

const app = document.getElementById('livre');
const racineDom = document.documentElement;
const donnees = JSON.parse(document.getElementById('livre-donnees').textContent);
const lecons = donnees.spreads;
const CLE = 'edubac-livre3d:' + app.dataset.cle;
const CLE_REGLAGES = 'edubac-livre3d-reglages';

// ---------------------------------------------------------------- Réglages et progression
function lire(cle, defaut) {
  try { const v = localStorage.getItem(cle); return v ? JSON.parse(v) : defaut; } catch (e) { return defaut; }
}
function ecrire(cle, valeur) {
  try { localStorage.setItem(cle, JSON.stringify(valeur)); } catch (e) { /* stockage indisponible */ }
}
const reglages = Object.assign({ son: false, contraste: false, mouvement: null }, lire(CLE_REGLAGES, {}));
const progression = Object.assign({ faits: {}, tampons: {}, predictions: {}, page: 0 }, lire(CLE, {}));
const reduit = () => racineDom.classList.contains('mouvement-reduit');
const sauver = () => ecrire(CLE, progression);

// ---------------------------------------------------------------- Constantes du livre
const W = 1.0;            // largeur d'une page
const D = 1.36;           // profondeur (hauteur de page)
const H = 0.07;           // hauteur du dessus des pages
const CX = 0.53;          // centre de la zone de figures (page de droite)
const CZ = -0.03;
const PAPIER = new THREE.Color(0xf3ede0);
const PAPIER_CONTRASTE = new THREE.Color(0xffffff);
const COULEURS = {
  orange: new THREE.Color(0xd9822b), turquoise: new THREE.Color(0x1f9f92), petrole: new THREE.Color(0x1f5a7a),
  rouge: new THREE.Color(0xc0485c), or: new THREE.Color(0xd9a62e), violet: new THREE.Color(0x6b5bb5),
};
const ENCRE = 0x1d1a16;

function hauteurPage(u) {            // u : distance au dos du livre (0 → W)
  return H - 0.032 * Math.exp(-u * 11) - 0.005 * (u / W) * (u / W);
}

// ---------------------------------------------------------------- Rendu
const conteneur = document.getElementById('scene3d');
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
} catch (e) {
  document.getElementById('livreErreur').hidden = false;
  document.getElementById('livreChargement').hidden = true;
  throw e;
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
conteneur.appendChild(renderer.domElement);

const rendererCss = new CSS3DRenderer();
rendererCss.domElement.classList.add('couche-css');
conteneur.appendChild(rendererCss.domElement);

const scene = new THREE.Scene();
const sceneCss = new THREE.Scene();
scene.background = new THREE.Color(0x3b3128);
scene.fog = new THREE.Fog(0x3b3128, 6, 13);

const camera = new THREE.PerspectiveCamera(38, 1, 0.02, 40);

// ---------------------------------------------------------------- Textures dessinées
function canevas(l, h) { const c = document.createElement('canvas'); c.width = l; c.height = h; return c; }
function texture(c, repete) {
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  if (repete) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(repete[0], repete[1]); }
  return t;
}
function grain(ctx, l, h, force, n) {
  for (let i = 0; i < n; i++) {
    const v = Math.random();
    ctx.fillStyle = v > 0.5 ? `rgba(255,255,255,${force * Math.random()})` : `rgba(60,40,20,${force * Math.random()})`;
    ctx.fillRect(Math.random() * l, Math.random() * h, 1 + Math.random() * 2, 1 + Math.random() * 2);
  }
}
function texturePapier(couleur = '#f6f0e3') {
  const c = canevas(1024, 1393), ctx = c.getContext('2d');
  ctx.fillStyle = couleur; ctx.fillRect(0, 0, c.width, c.height);
  grain(ctx, c.width, c.height, 0.05, 26000);
  return c;
}
function textureBureau() {
  const c = canevas(1024, 1024), ctx = c.getContext('2d');
  ctx.fillStyle = '#6d5a48'; ctx.fillRect(0, 0, 1024, 1024);
  for (let i = 0; i < 90; i++) {           // fibres d'un bois mat
    ctx.strokeStyle = `rgba(${Math.random() > 0.5 ? '40,28,18' : '140,118,92'},${0.05 + Math.random() * 0.08})`;
    ctx.lineWidth = 1 + Math.random() * 3;
    ctx.beginPath();
    const y = Math.random() * 1024;
    ctx.moveTo(0, y);
    for (let x = 0; x <= 1024; x += 64) ctx.lineTo(x, y + Math.sin(x / 140 + i) * 6);
    ctx.stroke();
  }
  grain(ctx, 1024, 1024, 0.08, 40000);
  return c;
}
function textureToile(teinte) {
  const c = canevas(256, 256), ctx = c.getContext('2d');
  ctx.fillStyle = teinte; ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 256; i += 3) {
    ctx.fillStyle = 'rgba(0,0,0,0.06)'; ctx.fillRect(i, 0, 1, 256);
    ctx.fillStyle = 'rgba(255,255,255,0.05)'; ctx.fillRect(0, i, 256, 1);
  }
  grain(ctx, 256, 256, 0.08, 3000);
  return c;
}
function textureTranche(verticales) {   // tranche du bloc de pages : fines lignes
  const c = canevas(512, 512), ctx = c.getContext('2d');
  ctx.fillStyle = '#efe6d2'; ctx.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 512; i += 4) {
    ctx.fillStyle = `rgba(120,100,70,${0.12 + Math.random() * 0.14})`;
    if (verticales) ctx.fillRect(i, 0, 1, 512); else ctx.fillRect(0, i, 512, 1);
  }
  const t = texture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(verticales ? 4 : 1, verticales ? 1 : 4);
  return t;
}
function textureStores() {               // lumière à travers des stores
  const c = canevas(512, 512), ctx = c.getContext('2d');
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 512, 512);
  for (let y = 0; y < 512; y += 46) {
    const g = ctx.createLinearGradient(0, y, 0, y + 30);
    g.addColorStop(0, 'rgba(255,255,255,0)'); g.addColorStop(0.25, '#fff'); g.addColorStop(0.75, '#fff'); g.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = g; ctx.fillRect(0, y, 512, 30);
  }
  const t = texture(c);
  return t;
}

// ---------------------------------------------------------------- Lumières
scene.add(new THREE.HemisphereLight(0xfff1dc, 0x3a2c20, 1.15));
const soleil = new THREE.DirectionalLight(0xffe0b5, 1.6);
soleil.position.set(-2.2, 3.6, -1.4);
soleil.castShadow = true;
soleil.shadow.mapSize.set(2048, 2048);
Object.assign(soleil.shadow.camera, { left: -1.8, right: 1.8, top: 1.6, bottom: -1.6, near: 0.5, far: 9 });
soleil.shadow.bias = -0.0004;
soleil.shadow.radius = 4;
scene.add(soleil);
const stores = new THREE.SpotLight(0xfff0d2, 9, 0, 0.62, 0.5, 0);
stores.position.set(-2.6, 3.0, -2.0);
stores.target.position.set(0.2, 0, 0.1);
stores.castShadow = true;
stores.shadow.mapSize.set(1024, 1024);
stores.map = textureStores();
scene.add(stores, stores.target);

// ---------------------------------------------------------------- Bureau et livre
const bureau = new THREE.Mesh(new THREE.PlaneGeometry(14, 14),
  new THREE.MeshStandardMaterial({ map: texture(textureBureau(), [5, 5]), roughness: 0.92 }));
bureau.rotation.x = -Math.PI / 2;
bureau.receiveShadow = true;
scene.add(bureau);

const livre = new THREE.Group();
scene.add(livre);
const toile = new THREE.MeshStandardMaterial({ map: texture(textureToile('#d7a53c'), [3, 3]), roughness: 0.85 });
for (const s of [-1, 1]) {
  const plat = new THREE.Mesh(new THREE.BoxGeometry(W + 0.035, 0.012, D + 0.06), toile);
  plat.position.set(s * (W + 0.035) / 2 + s * 0.012, 0.006, 0);
  plat.castShadow = plat.receiveShadow = true;
  livre.add(plat);
}
const dos = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, D + 0.06, 24, 1, false, Math.PI / 2, Math.PI), toile);
dos.rotation.x = Math.PI / 2;
dos.rotation.y = Math.PI;
dos.position.set(0, 0.012, 0);
livre.add(dos);

const trancheHaut = new THREE.MeshStandardMaterial({ map: textureTranche(false), roughness: 0.95 });
const trancheCote = new THREE.MeshStandardMaterial({ map: textureTranche(true), roughness: 0.95 });
function blocPages(signe) {
  const profil = new THREE.Shape();
  const N = 40;
  profil.moveTo(0, 0.012);
  profil.lineTo(signe * W, 0.012);
  for (let i = N; i >= 0; i--) { const u = (i / N) * W; profil.lineTo(signe * u, hauteurPage(u) - 0.0015); }
  const geo = new THREE.ExtrudeGeometry(profil, { depth: D, bevelEnabled: false, curveSegments: 1 });
  geo.translate(0, 0, -D / 2);
  const bloc = new THREE.Mesh(geo, [trancheHaut, trancheCote]);
  bloc.castShadow = bloc.receiveShadow = true;
  return bloc;
}
livre.add(blocPages(-1), blocPages(1));

function feuilleCourbe(signe, materiau) {
  const geo = new THREE.PlaneGeometry(W, D, 48, 1);
  geo.rotateX(-Math.PI / 2);
  geo.translate(signe * W / 2, 0, 0);
  const pos = geo.attributes.position;
  for (let i = 0; i < pos.count; i++) pos.setY(i, hauteurPage(Math.abs(pos.getX(i))));
  geo.computeVertexNormals();
  const m = new THREE.Mesh(geo, materiau);
  m.receiveShadow = true;
  return m;
}
const papierGauche = texture(texturePapier());
const pageGaucheMesh = feuilleCourbe(-1, new THREE.MeshStandardMaterial({ map: papierGauche, roughness: 0.95 }));
const canevasDroite = texturePapier();
const textureDroite = texture(canevasDroite);
const pageDroiteMesh = feuilleCourbe(1, new THREE.MeshStandardMaterial({ map: textureDroite, roughness: 0.95 }));
livre.add(pageGaucheMesh, pageDroiteMesh);

// Signet en tissu bleu, qui sort du bas du dos
(function signet() {
  const courbe = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0.005, H - 0.025, 0.25), new THREE.Vector3(0.012, H - 0.005, 0.6),
    new THREE.Vector3(0.02, 0.05, D / 2 + 0.02), new THREE.Vector3(0.035, 0.012, D / 2 + 0.09),
    new THREE.Vector3(0.06, 0.0015, D / 2 + 0.2), new THREE.Vector3(0.09, 0.0015, D / 2 + 0.3),
  ]);
  const pts = courbe.getPoints(60), l = 0.013, sommets = [], ix = [];
  pts.forEach((p, i) => {
    sommets.push(p.x - l, p.y, p.z, p.x + l, p.y, p.z);
    if (i) { const a = (i - 1) * 2; ix.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(sommets, 3));
  geo.setIndex(ix);
  geo.computeVertexNormals();
  const ruban = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x2f5fa8, roughness: 0.7, side: THREE.DoubleSide }));
  ruban.castShadow = true;
  livre.add(ruban);
})();

// ---------------------------------------------------------------- Matériaux « encre et papier »
const degrade = (() => {
  const t = new THREE.DataTexture(new Uint8Array([90, 175, 255]), 3, 1, THREE.RedFormat);
  t.minFilter = t.magFilter = THREE.NearestFilter;
  t.needsUpdate = true;
  return t;
})();
const uniformsHachure = { uHachure: { value: 6 * renderer.getPixelRatio() } };
function hachurer(m) {    // hachures croisées dans les zones sombres (calculées à l'écran)
  m.onBeforeCompile = (shader) => {
    shader.uniforms.uHachure = uniformsHachure.uHachure;
    shader.fragmentShader = 'uniform float uHachure;\n' + shader.fragmentShader.replace('#include <dithering_fragment>', `
      #include <dithering_fragment>
      float lum = dot(gl_FragColor.rgb, vec3(0.299, 0.587, 0.114));
      vec2 fc = gl_FragCoord.xy / uHachure;
      float h1 = step(fract(fc.x + fc.y), 0.16);
      float h2 = step(fract(fc.x - fc.y), 0.16);
      float ombre = h1 * smoothstep(0.62, 0.42, lum) + h2 * smoothstep(0.42, 0.25, lum);
      gl_FragColor.rgb = mix(gl_FragColor.rgb, vec3(0.11, 0.10, 0.09), clamp(ombre, 0.0, 1.0) * 0.55);`);
  };
  return m;
}
function matPapier(teinte) {
  const m = new THREE.MeshToonMaterial({ color: PAPIER.clone(), gradientMap: degrade, side: THREE.DoubleSide });
  m.userData.teinte = teinte || null;
  m.userData.base = PAPIER.clone();
  return hachurer(m);
}
const matEncre = new THREE.LineBasicMaterial({ color: ENCRE });
const materiauxPapier = new Set();
function papier(teinte, force = 0.28) {
  const m = matPapier(teinte);
  if (teinte) m.color.copy(PAPIER).lerp(teinte, force);
  m.userData.force = force;
  materiauxPapier.add(m);
  return m;
}
function encrer(mesh, seuil = 28) {
  mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, seuil), matEncre));
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

// ---------------------------------------------------------------- Animation (tweens maison)
const tweens = new Set();
const ease = {
  inOut: (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  out: (p) => 1 - Math.pow(1 - p, 3),
  ressort: (p) => 1 - Math.exp(-6.5 * p) * Math.cos(9.5 * p),
  lin: (p) => p,
};
function animer(duree, maj, { courbe = ease.inOut, delai = 0, force = false } = {}) {
  return new Promise((fin) => {
    if ((reduit() && !force) || duree <= 0) { maj(1); fin(); return; }
    tweens.add({ debut: performance.now() + delai * 1000, duree: duree * 1000, maj, courbe, fin });
  });
}
const attendre = (s) => new Promise((r) => setTimeout(r, reduit() ? Math.min(s, 0.6) * 1000 : s * 1000));

// ---------------------------------------------------------------- Son (synthétisé, sans fichier)
let audio = null;
function son(type) {
  if (!reglages.son) return;
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const t = audio.currentTime;
    const sortie = audio.createGain();
    sortie.connect(audio.destination);
    if (type === 'page' || type === 'tampon') {
      const duree = type === 'page' ? 0.55 : 0.18;
      const buf = audio.createBuffer(1, audio.sampleRate * duree, audio.sampleRate);
      const d = buf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / d.length);
      const src = audio.createBufferSource(); src.buffer = buf;
      const filtre = audio.createBiquadFilter();
      filtre.type = 'bandpass'; filtre.frequency.value = type === 'page' ? 2200 : 400; filtre.Q.value = 0.7;
      src.connect(filtre); filtre.connect(sortie);
      sortie.gain.setValueAtTime(0.0001, t);
      sortie.gain.exponentialRampToValueAtTime(type === 'page' ? 0.35 : 0.8, t + 0.03);
      sortie.gain.exponentialRampToValueAtTime(0.0001, t + duree);
      src.start(t);
    } else {
      const osc = audio.createOscillator();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(type === 'juste' ? 660 : type === 'faux' ? 220 : 520, t);
      if (type === 'juste') osc.frequency.exponentialRampToValueAtTime(990, t + 0.12);
      osc.connect(sortie);
      sortie.gain.setValueAtTime(0.0001, t);
      sortie.gain.exponentialRampToValueAtTime(0.18, t + 0.01);
      sortie.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
      osc.start(t); osc.stop(t + 0.25);
    }
  } catch (e) { /* audio indisponible */ }
}

// ---------------------------------------------------------------- Étiquettes à l'encre (sprites)
function etiquette(texte, { hauteur = 0.045, couleur = '#1d1a16', fond = null } = {}) {
  const c = canevas(16, 16);
  const tex = texture(c);
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false });
  const s = new THREE.Sprite(mat);
  s.center.set(0.5, 0);
  s.renderOrder = 5;
  let actuel = null;
  s.userData.ecrire = (t) => {
    if (t === actuel) return;
    actuel = t;
    const ctx = c.getContext('2d');
    const taille = 72;
    ctx.font = `italic 600 ${taille}px Newsreader, Georgia, serif`;
    const lignes = String(t).split('\n');
    const larg = Math.max(...lignes.map((l) => ctx.measureText(l).width)) + 40;
    c.width = Math.ceil(larg); c.height = Math.ceil(taille * 1.25 * lignes.length + 24);
    ctx.font = `italic 600 ${taille}px Newsreader, Georgia, serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    if (fond) { ctx.fillStyle = fond; ctx.beginPath(); ctx.roundRect(2, 2, c.width - 4, c.height - 4, 22); ctx.fill(); ctx.strokeStyle = '#1d1a16'; ctx.lineWidth = 4; ctx.stroke(); }
    lignes.forEach((l, i) => {
      const y = 12 + taille * 1.25 * (i + 0.5);
      if (!fond) { ctx.lineWidth = 14; ctx.strokeStyle = 'rgba(246,240,227,0.92)'; ctx.strokeText(l, c.width / 2, y); }
      ctx.fillStyle = couleur; ctx.fillText(l, c.width / 2, y);
    });
    tex.dispose();
    const neuf = texture(c);
    mat.map = neuf;
    mat.needsUpdate = true;
    s.scale.set(hauteur * lignes.length * c.width / c.height, hauteur * lignes.length, 1);
  };
  s.userData.ecrire(texte);
  return s;
}

// ---------------------------------------------------------------- Boîte à outils des figures
function creerOutils(root, fenetre) {
  const [x0, x1, y0, y1] = fenetre;
  const s = Math.min(0.84 / (x1 - x0), 1.1 / (y1 - y0));
  const xm = (x0 + x1) / 2, ym = (y0 + y1) / 2;
  const P = (x, y, h = 0) => new THREE.Vector3((x - xm) * s, h, -(y - ym) * s);
  const cibles = new Map();
  const maj = [];
  const o = {
    s, P, cibles, maj, root,
    ajouter(obj) { root.add(obj); return obj; },
    cible(id, obj, rayon) {
      obj.userData.cible = id;
      if (rayon) {
        const proxy = new THREE.Mesh(new THREE.SphereGeometry(rayon, 10, 8), new THREE.MeshBasicMaterial({ visible: false }));
        proxy.userData.cible = id;
        obj.add(proxy);
      }
      cibles.set(id, obj);
      return obj;
    },
    fleche(couleur, { haut = 0.05, epais = 0.017 } = {}) {
      const g = new THREE.Group();
      const mat = papier(couleur, 0.35);
      const mesh = new THREE.Mesh(new THREE.BufferGeometry(), mat);
      mesh.position.y = haut;
      const tenons = [0, 1].map(() => {
        const t = encrer(new THREE.Mesh(new THREE.BoxGeometry(0.012, haut, 0.003), papier()));
        t.position.y = haut / 2;
        g.add(t);
        return t;
      });
      const proxy = new THREE.Mesh(new THREE.BoxGeometry(1, 0.08, 0.06), new THREE.MeshBasicMaterial({ visible: false }));
      g.add(mesh, proxy);
      let lien = null;
      g.userData.mat = mat;
      g.userData.couleur = couleur;
      g.userData.placer = (a, b) => {
        const dx = b.x - a.x, dz = b.z - a.z, L = Math.hypot(dx, dz);
        const tete = Math.min(0.065, L * 0.38), lt = epais * 2.7;
        const sh = new THREE.Shape();
        sh.moveTo(0, -epais / 2); sh.lineTo(L - tete, -epais / 2); sh.lineTo(L - tete, -lt / 2); sh.lineTo(L, 0);
        sh.lineTo(L - tete, lt / 2); sh.lineTo(L - tete, epais / 2); sh.lineTo(0, epais / 2); sh.closePath();
        const geo = new THREE.ExtrudeGeometry(sh, { depth: 0.009, bevelEnabled: false });
        geo.rotateX(-Math.PI / 2);
        mesh.geometry.dispose();
        mesh.geometry = geo;
        if (lien) { mesh.remove(lien); lien.geometry.dispose(); }
        lien = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 28), matEncre);
        mesh.add(lien);
        mesh.castShadow = true;
        tenons[0].position.x = L * 0.28; tenons[1].position.x = L * 0.68;
        proxy.scale.set(L, 1, 1); proxy.position.set(L / 2, 0.04, 0);
        g.position.copy(a);
        g.rotation.y = Math.atan2(-dz, dx);
      };
      return g;
    },
    epingle(couleur, { haut = 0.085, tete = 0.017 } = {}) {
      const g = new THREE.Group();
      const tige = new THREE.Mesh(new THREE.CylinderGeometry(0.0035, 0.0035, haut, 8), new THREE.MeshStandardMaterial({ color: 0x6b6258, metalness: 0.6, roughness: 0.4 }));
      tige.position.y = haut / 2;
      tige.castShadow = true;
      const mat = papier(couleur, 0.85);
      const boule = encrer(new THREE.Mesh(new THREE.SphereGeometry(tete, 20, 14), mat), 60);
      boule.position.y = haut;
      const pied = new THREE.Mesh(new THREE.RingGeometry(0.004, 0.012, 20), new THREE.MeshBasicMaterial({ color: ENCRE, side: THREE.DoubleSide }));
      pied.rotation.x = -Math.PI / 2; pied.position.y = 0.002;
      g.add(tige, boule, pied);
      g.userData.mat = mat; g.userData.couleur = couleur; g.userData.tete = boule;
      return g;
    },
    mur(rayon, { haut = 0.045, couleur = null } = {}) {
      const geo = new THREE.CylinderGeometry(rayon, rayon, haut, 120, 1, true);
      geo.translate(0, haut / 2, 0);
      const m = encrer(new THREE.Mesh(geo, papier(couleur, 0.25)), 10);
      m.userData.mat = m.material;
      return m;
    },
    bande(couleur, { haut = 0.04, epais = 0.005 } = {}) {   // règle / mur de papier entre deux points
      const geo = new THREE.BoxGeometry(1, haut, epais);
      geo.translate(0.5, haut / 2, 0);
      const m = encrer(new THREE.Mesh(geo, papier(couleur, 0.3)));
      const proxy = new THREE.Mesh(new THREE.BoxGeometry(1, 0.07, 0.06), new THREE.MeshBasicMaterial({ visible: false }));
      proxy.position.set(0.5, 0.035, 0);
      m.add(proxy);
      m.userData.mat = m.material;
      m.userData.placer = (a, b) => {
        const dx = b.x - a.x, dz = b.z - a.z;
        m.position.copy(a);
        m.scale.x = Math.max(Math.hypot(dx, dz), 1e-4);
        m.rotation.y = Math.atan2(-dz, dx);
      };
      return m;
    },
    trait(couleur = ENCRE, { pointille = true, h = 0.004 } = {}) {
      const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
      const mat = pointille ? new THREE.LineDashedMaterial({ color: couleur, dashSize: 0.014, gapSize: 0.009 })
                            : new THREE.LineBasicMaterial({ color: couleur });
      const l = new THREE.Line(geo, mat);
      l.userData.placer = (...pts) => {
        l.geometry.setFromPoints(pts.map((p) => new THREE.Vector3(p.x, (p.y || 0) + h, p.z)));
        if (pointille) l.computeLineDistances();
      };
      return l;
    },
    angleDroit(taille = 0.028) {
      const l = o.trait(ENCRE, { pointille: false, h: 0.005 });
      l.userData.orienter = (c, d1, d2) => {
        const a = d1.clone().setY(0).normalize().multiplyScalar(taille), b = d2.clone().setY(0).normalize().multiplyScalar(taille);
        l.userData.placer(c.clone().add(a), c.clone().add(a).add(b), c.clone().add(b));
      };
      return l;
    },
    arc(couleur) {
      const mat = new THREE.MeshToonMaterial({ color: couleur, gradientMap: degrade });
      const m = new THREE.Mesh(new THREE.BufferGeometry(), mat);
      m.castShadow = true;
      m.userData.mat = mat;
      m.userData.placer = (c, r, a0, a1, h = 0.012) => {
        const n = Math.max(4, Math.ceil(Math.abs(a1 - a0) * 24));
        const pts = [];
        for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * (i / n); pts.push(new THREE.Vector3(c.x + r * Math.cos(a), h, c.z - r * Math.sin(a))); }
        m.geometry.dispose();
        m.geometry = pts.length > 1 ? new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), n * 2, 0.0045, 6, false) : new THREE.BufferGeometry();
      };
      return m;
    },
    bocal(couleur, { min = -1, max = 1, rayon = 0.042, haut = 0.2 } = {}) {
      const g = new THREE.Group();
      const verre = new THREE.Mesh(new THREE.CylinderGeometry(rayon, rayon, haut, 40, 1, true).translate(0, haut / 2, 0),
        new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.16, roughness: 0.08, depthWrite: false, side: THREE.DoubleSide }));
      verre.add(new THREE.LineSegments(new THREE.EdgesGeometry(verre.geometry, 10), matEncre));
      const socle = encrer(new THREE.Mesh(new THREE.CylinderGeometry(rayon * 1.25, rayon * 1.3, 0.012, 32), papier()), 30);
      socle.position.y = 0.006;
      const signe = min < 0;
      const zero = signe ? haut / 2 : 0.012;
      const anneau = new THREE.Mesh(new THREE.TorusGeometry(rayon * 1.02, 0.0018, 6, 40), new THREE.MeshBasicMaterial({ color: ENCRE }));
      anneau.rotation.x = Math.PI / 2; anneau.position.y = zero; anneau.visible = signe;
      const matL = new THREE.MeshStandardMaterial({ color: couleur, emissive: couleur, emissiveIntensity: 0.35, roughness: 0.3, transparent: true, opacity: 0.88 });
      const liquide = new THREE.Mesh(new THREE.CylinderGeometry(rayon * 0.88, rayon * 0.88, 1, 32).translate(0, 0.5, 0), matL);
      liquide.scale.y = 0.0001;
      const lab = etiquette('', { hauteur: 0.036 });
      lab.position.y = haut + 0.02;
      g.add(socle, verre, anneau, liquide, lab);
      const plage = Math.max(Math.abs(min), Math.abs(max));
      let valeur = 0;
      g.userData.mat = matL;
      g.userData.etiquette = lab;
      g.userData.afficher = (v) => {
        valeur = v;
        const k = Math.max(-1, Math.min(1, v / plage));
        const utile = signe ? haut / 2 - 0.012 : haut - 0.024;
        liquide.scale.y = Math.max(0.0001, Math.abs(k) * utile);
        liquide.position.y = k >= 0 ? zero : zero - liquide.scale.y;
        matL.color.copy(k >= 0 ? couleur : COULEURS.rouge);
        matL.emissive.copy(matL.color);
      };
      g.userData.valeur = () => valeur;
      g.userData.vers = (v, duree = 0.9) => { const a = valeur; return animer(duree, (p) => g.userData.afficher(a + (v - a) * p)); };
      g.userData.afficher(0);
      return g;
    },
    flux(couleur, n = 22) {    // particules lumineuses qui suivent un chemin
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(n * 3), 3));
      const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color: couleur, size: 0.016, transparent: true, opacity: 0.95, depthWrite: false, blending: THREE.AdditiveBlending }));
      pts.visible = false;
      let chemin = null, t = 0;
      pts.userData.lancer = (a, b, duree = 2.2) => {
        if (reduit()) return;
        chemin = [a.clone().setY(0.03), b.clone().setY(0.03)];
        pts.visible = true; t = 0;
        setTimeout(() => { pts.visible = false; chemin = null; }, duree * 1000);
      };
      maj.push((dt) => {
        if (!chemin) return;
        t += dt;
        const p = geo.attributes.position;
        for (let i = 0; i < n; i++) {
          const k = (i / n + t * 0.6) % 1;
          p.setXYZ(i, chemin[0].x + (chemin[1].x - chemin[0].x) * k, 0.03 + Math.sin(k * Math.PI) * 0.025, chemin[0].z + (chemin[1].z - chemin[0].z) * k);
        }
        p.needsUpdate = true;
      });
      return pts;
    },
    socle(rayon, haut = 0.03) {
      const m = encrer(new THREE.Mesh(new THREE.CylinderGeometry(rayon, rayon * 1.04, haut, 48).translate(0, haut / 2, 0), papier()), 30);
      m.userData.mat = m.material;
      return m;
    },
    eclairer(obj, k = 1) {   // remplissage coloré « actif »
      const mat = obj.userData.mat;
      const teinte = obj.userData.couleur || mat?.userData?.teinte;
      if (!mat || !teinte) return Promise.resolve();
      const base = mat.color.clone();
      const cible = PAPIER.clone().lerp(teinte, 0.35 + 0.65 * k);
      return animer(0.5, (p) => {
        mat.color.copy(base).lerp(cible, p);
        if (mat.emissive) mat.emissive.copy(teinte).multiplyScalar(0.25 * k * p);
      });
    },
    pulser(obj) {
      const s0 = obj.scale.clone();
      return animer(0.6, (p) => obj.scale.copy(s0).multiplyScalar(1 + Math.sin(p * Math.PI) * 0.18), { courbe: ease.lin });
    },
    apparaitre(obj, duree = 0.5) {
      obj.visible = true;
      const s0 = obj.userData.echelle || (obj.userData.echelle = obj.scale.clone());
      return animer(duree, (p) => obj.scale.copy(s0).multiplyScalar(Math.max(0.001, p)), { courbe: ease.ressort });
    },
  };
  return o;
}

const fr = (v, d = 2) => {
  const r = Math.round(v * 10 ** d) / 10 ** d;
  return (Math.abs(r) < 1e-9 ? 0 : r).toString().replace('.', ',').replace('-', '−');
};

// ---------------------------------------------------------------- Impression sur la page de droite
const IMP = { l: canevasDroite.width, h: canevasDroite.height };
function versPage(v) { return [((CX + v.x) / W) * IMP.l, ((CZ + v.z + D / 2) / D) * IMP.h]; }
function imprimerBase(ctx, lecon, o, { grille = true, axes = true, fenetre } = {}) {
  ctx.drawImage(papierDroiteBase, 0, 0);
  const encre = racineDom.classList.contains('contraste') ? '#000' : '#2b2620';
  if (fenetre && (grille || axes)) {
    const [x0, x1, y0, y1] = fenetre;
    ctx.lineWidth = 1.2;
    if (grille) {
      ctx.strokeStyle = 'rgba(120,100,70,0.22)';
      for (let x = Math.ceil(x0); x <= x1; x++) { const [a, b] = versPage(o.P(x, y0)), [c, d] = versPage(o.P(x, y1)); ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke(); }
      for (let y = Math.ceil(y0); y <= y1; y++) { const [a, b] = versPage(o.P(x0, y)), [c, d] = versPage(o.P(x1, y)); ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke(); }
    }
    if (axes && x0 < 0 && x1 > 0 && y0 < 0 && y1 > 0) {
      ctx.strokeStyle = encre; ctx.fillStyle = encre; ctx.lineWidth = 2.4;
      const fl = (p, q) => {
        const [a, b] = versPage(p), [c, d] = versPage(q);
        ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke();
        const ang = Math.atan2(d - b, c - a);
        ctx.beginPath(); ctx.moveTo(c, d); ctx.lineTo(c - 16 * Math.cos(ang - 0.4), d - 16 * Math.sin(ang - 0.4));
        ctx.lineTo(c - 16 * Math.cos(ang + 0.4), d - 16 * Math.sin(ang + 0.4)); ctx.closePath(); ctx.fill();
      };
      fl(o.P(x0, 0), o.P(x1, 0)); fl(o.P(0, y0), o.P(0, y1));
      const [ox, oy] = versPage(o.P(0, 0));
      ctx.font = 'italic 30px Newsreader, Georgia, serif';
      ctx.fillText('O', ox - 28, oy + 30);
      const [ix, iy] = versPage(o.P(1, 0)); ctx.fillText('1', ix - 6, iy + 32);
    }
  }
  // Légende imprimée en bas de page
  ctx.fillStyle = encre;
  ctx.font = '600 22px Lexend, sans-serif';
  ctx.fillText(`FIGURE ${lecon.number}`, 90, IMP.h - 120);
  ctx.font = 'italic 27px Newsreader, Georgia, serif';
  lignesTexte(ctx, lecon.scene.description, 90, IMP.h - 84, IMP.l - 180, 32);
  // numéro de page
  ctx.font = '22px Newsreader, Georgia, serif';
  ctx.fillText(String(2 * (lecons.indexOf(lecon) + 1)), IMP.l - 110, 70);
}
function lignesTexte(ctx, texte, x, y, largeur, interligne) {
  const mots = texte.split(' ');
  let ligne = '', n = 0;
  for (const m of mots) {
    const essai = ligne ? ligne + ' ' + m : m;
    if (ctx.measureText(essai).width > largeur && ligne) { ctx.fillText(ligne, x, y + n * interligne); ligne = m; n++; if (n > 1) { ctx.fillText(ligne + '…', x, y + n * interligne); return; } }
    else ligne = essai;
  }
  ctx.fillText(ligne, x, y + n * interligne);
}
function legendeImprimee(ctx, point, texte, dx, dy) {     // étiquette imprimée reliée par un trait
  const [a, b] = versPage(point);
  ctx.strokeStyle = 'rgba(43,38,32,0.75)'; ctx.lineWidth = 1.6;
  ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(a + dx, b + dy); ctx.stroke();
  ctx.beginPath(); ctx.arc(a, b, 3.5, 0, Math.PI * 2); ctx.fill();
  ctx.font = 'italic 30px Newsreader, Georgia, serif';
  ctx.textAlign = dx < 0 ? 'right' : 'left';
  ctx.fillText(texte, a + dx + (dx < 0 ? -8 : 8), b + dy + 9);
  ctx.textAlign = 'left';
}
const papierDroiteBase = (() => { const c = canevas(IMP.l, IMP.h); c.getContext('2d').drawImage(canevasDroite, 0, 0); return c; })();

// ---------------------------------------------------------------- Les neuf figures
const SCENES = {
  produit(o, lecon) {
    const F = [-1.5, 8.6, -3.6, 7.2];
    const O = o.P(0, 0), U = o.P(3, -2), V = o.P(4, 6);
    const u = o.ajouter(o.cible('u', o.fleche(COULEURS.orange))); u.userData.placer(O, U);
    const v = o.ajouter(o.cible('v', o.fleche(COULEURS.turquoise))); v.userData.placer(O, V);
    const bocal = o.ajouter(o.cible('bocal', o.bocal(COULEURS.turquoise, { min: -15, max: 15 }), 0.07));
    bocal.position.copy(o.P(6.4, 0.2));
    bocal.userData.etiquette.userData.ecrire('u·v');
    const guides = {};
    for (const [id, tip, x, y] of [['u', U, 3, -2], ['v', V, 4, 6]]) {
      const lx = o.ajouter(o.trait()), ly = o.ajouter(o.trait());
      lx.userData.placer(tip, o.P(x, 0)); ly.userData.placer(tip, o.P(0, y));
      const ex = o.ajouter(etiquette(id === 'u' ? 'x = 3' : "x' = 4", { hauteur: 0.032 })), ey = o.ajouter(etiquette(id === 'u' ? 'y = −2' : "y' = 6", { hauteur: 0.032 }));
      ex.position.copy(o.P(x, 0, 0.01)).add(new THREE.Vector3(0, 0, 0.03)); ey.position.copy(o.P(0, y, 0.01)).add(new THREE.Vector3(-0.07, 0, 0));
      guides[id] = [lx, ly, ex, ey];
      guides[id].forEach((g) => { g.visible = false; });
    }
    const droit = o.ajouter(o.angleDroit(0.035)); droit.userData.orienter(O, U.clone().sub(O), V.clone().sub(O)); droit.visible = false;
    const flux = o.ajouter(o.flux(COULEURS.or));
    const montrer = async (id, fleche, tip) => {
      o.eclairer(fleche); guides[id].forEach((g) => o.apparaitre(g, 0.45)); flux.userData.lancer(O, tip);
    };
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { fenetre: F });
        legendeImprimee(ctx, U, 'u(3 ; −2)', 40, 40);
        legendeImprimee(ctx, V, 'v(4 ; 6)', -40, -30);
      },
      interactions: {
        u: () => montrer('u', u, U),
        v: () => montrer('v', v, V),
        bocal: async () => {
          o.eclairer(bocal);
          bocal.userData.etiquette.userData.ecrire("xx' = 3×4 = 12");
          await bocal.userData.vers(12);
          await attendre(0.6);
          bocal.userData.etiquette.userData.ecrire("+ yy' = (−2)×6 = −12");
          await bocal.userData.vers(0, 1.1);
          bocal.userData.etiquette.userData.ecrire('u·v = 0  ⇒  u ⟂ v');
          o.apparaitre(droit);
        },
      },
    };
  },

  angle(o, lecon) {
    const F = [-3.3, 3.3, -1.7, 3.4];
    const O = o.P(0, 0), ru = Math.hypot(1, 2), au = Math.atan2(2, 1);
    const etat = { theta: Math.PI / 2 };
    const u = o.ajouter(o.fleche(COULEURS.orange)); u.userData.placer(O, o.P(1, 2));
    const v = o.ajouter(o.cible('v', o.fleche(COULEURS.turquoise)));
    const arc = o.ajouter(o.cible('arc', o.arc(COULEURS.violet), 0.05));
    const lt = o.ajouter(etiquette('θ', { hauteur: 0.04 }));
    const jc = o.ajouter(o.bocal(COULEURS.turquoise, { min: -1, max: 1, haut: 0.18, rayon: 0.036 }));
    const js = o.ajouter(o.bocal(COULEURS.petrole, { min: -1, max: 1, haut: 0.18, rayon: 0.036 }));
    jc.position.copy(o.P(-2.6, -0.9)); js.position.copy(o.P(-1.75, -0.9));
    o.cible('jauges', jc, 0.07);
    js.userData.cible = 'jauges';
    const proxy = new THREE.Mesh(new THREE.SphereGeometry(0.07, 10, 8), new THREE.MeshBasicMaterial({ visible: false }));
    proxy.userData.cible = 'jauges'; proxy.position.y = 0.09; js.add(proxy);
    const NOMS = { '0': '0', '1': 'π/4', '2': 'π/2', '3': '3π/4', '4': 'π', '-1': '−π/4', '-2': '−π/2', '-3': '−3π/4' };
    let sens = etiquette('', { hauteur: 0.032 }); o.ajouter(sens); sens.visible = false;
    o.maj.push(() => {
      let t = etat.theta;
      t = Math.atan2(Math.sin(t), Math.cos(t));
      const av = au + etat.theta;
      v.userData.placer(O, o.P(ru * Math.cos(av), ru * Math.sin(av)));
      arc.userData.placer(O, 0.55 * o.s, au, au + t);
      const mil = au + t / 2;
      lt.position.copy(O).add(new THREE.Vector3(0.75 * o.s * Math.cos(mil), 0.01, -0.75 * o.s * Math.sin(mil)));
      const k = Math.round(t / (Math.PI / 4));
      lt.userData.ecrire(Math.abs(t - k * Math.PI / 4) < 0.02 ? `θ = ${NOMS[String(k === -4 ? 4 : k)]}` : 'θ');
      jc.userData.afficher(Math.cos(t)); js.userData.afficher(Math.sin(t));
      jc.userData.etiquette.userData.ecrire(`cos θ = ${fr(Math.cos(t))}`);
      js.userData.etiquette.userData.ecrire(`sin θ = ${fr(Math.sin(t))}`);
      sens.position.copy(O).add(new THREE.Vector3(0, 0.05, 0.08));
      sens.userData.ecrire(t >= 0 ? 'sin θ > 0 : sens direct ↺' : 'sin θ < 0 : sens indirect ↻');
    });
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { fenetre: F });
        legendeImprimee(ctx, o.P(1, 2), 'u(1 ; 2)', 40, -20);
      },
      interactions: {
        v: async () => { o.eclairer(v); const a = etat.theta; await animer(1.1, (p) => { etat.theta = a + (Math.PI / 4) * p; }, { courbe: ease.ressort }); },
        arc: async () => { o.eclairer(arc); sens.visible = true; await o.apparaitre(sens); },
        jauges: async () => { o.eclairer(jc); o.eclairer(js); o.pulser(jc); await o.pulser(js); },
      },
    };
  },

  droite(o, lecon) {
    const F = [-3.3, 4.6, -3.6, 4.6];
    const pt = (x) => o.P(x, (4 * x + 4) / 3);
    const D1 = pt(-2.75), D2 = pt(2.05), A = o.P(2, -1), Hh = o.P(-0.4, 0.8), P0 = o.P(-1, 0);
    const dirD = D2.clone().sub(D1).normalize();
    const mur = o.ajouter(o.cible('D', o.bande(COULEURS.petrole, { haut: 0.045 }))); mur.userData.placer(D1, D2);
    const n = o.ajouter(o.cible('n', o.fleche(COULEURS.orange, { haut: 0.03 }))); n.userData.placer(P0, o.P(-1 + 4 * 0.32, -3 * 0.32));
    const a = o.ajouter(o.cible('A', o.epingle(COULEURS.rouge), 0.03)); a.position.copy(A);
    const h = o.ajouter(o.epingle(COULEURS.or, { haut: 0.05, tete: 0.012 })); h.position.copy(Hh); h.visible = false;
    const ah = o.ajouter(o.trait(ENCRE)); ah.visible = false;
    const dH = o.ajouter(o.angleDroit()); dH.userData.orienter(Hh, dirD, A.clone().sub(Hh)); dH.visible = false;
    const d0 = o.ajouter(o.angleDroit()); d0.userData.orienter(P0, dirD, o.P(4, -3).sub(o.P(0, 0))); d0.visible = false;
    const lab = o.ajouter(etiquette('AH = 3', { hauteur: 0.038 })); lab.position.copy(A.clone().add(Hh).multiplyScalar(0.5)).setY(0.06); lab.visible = false;
    const labN = o.ajouter(etiquette('n(4 ; −3)', { hauteur: 0.034 })); labN.position.copy(o.P(0.5, -1.4, 0.04)); labN.visible = false;
    const m = o.ajouter(o.epingle(COULEURS.turquoise, { haut: 0.06, tete: 0.013 })); m.visible = false;
    const am = o.ajouter(o.trait(COULEURS.turquoise)); am.visible = false;
    const labM = o.ajouter(etiquette('AM·n = −15', { hauteur: 0.036 })); labM.visible = false;
    const flux = o.ajouter(o.flux(COULEURS.or));
    const etat = { k: 0.2 };
    o.maj.push(() => {
      if (!m.visible) return;
      const M = D1.clone().lerp(D2, etat.k);
      m.position.copy(M); am.userData.placer(A, M);
      labM.position.copy(M).add(new THREE.Vector3(0, 0.09, 0));
    });
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { fenetre: F });
        legendeImprimee(ctx, D2, '(D) : 4x − 3y + 4 = 0', 30, 10);
        legendeImprimee(ctx, A, 'A(2 ; −1)', 40, 30);
      },
      interactions: {
        A: async () => {
          o.eclairer(a); ah.visible = true;
          await animer(0.9, (p) => ah.userData.placer(A, A.clone().lerp(Hh, p)));
          o.apparaitre(h); o.apparaitre(dH); o.apparaitre(lab); flux.userData.lancer(A, Hh);
        },
        n: async () => { o.eclairer(n); o.apparaitre(d0); await o.apparaitre(labN); },
        D: async () => {
          o.eclairer(mur); m.visible = am.visible = labM.visible = true;
          await animer(1.4, (p) => { etat.k = 0.2 + 0.6 * p; });
          await animer(1.4, (p) => { etat.k = 0.8 - 0.5 * p; });
        },
      },
    };
  },

  cercle(o, lecon) {
    const F = [-4.2, 8.4, -9.2, 3.3];
    const Om = o.P(2, -3), R = 5, A = o.P(-3, -3), B = o.P(7, -3);
    const etat = { a: Math.PI / 3, triangle: false };
    const mur = o.ajouter(o.mur(R * o.s, { couleur: COULEURS.turquoise }));
    mur.position.copy(Om);
    const om = o.ajouter(o.cible('omega', o.epingle(COULEURS.petrole), 0.03)); om.position.copy(Om);
    for (const p of [A, B]) { const e = o.ajouter(o.epingle(COULEURS.or, { haut: 0.05, tete: 0.011 })); e.position.copy(p); }
    const dia = o.ajouter(o.cible('diametre', o.bande(COULEURS.or, { haut: 0.012 }))); dia.userData.placer(A, B);
    const m = o.ajouter(o.cible('M', o.epingle(COULEURS.orange), 0.03));
    const bras = o.ajouter(o.trait(COULEURS.petrole, { pointille: false, h: 0.03 }));
    const lab = o.ajouter(etiquette('ΩM = 5', { hauteur: 0.04 })); lab.visible = false;
    const rayons = [];
    for (let i = 0; i < 8; i++) { const r = o.ajouter(o.trait(COULEURS.petrole)); r.visible = false; rayons.push(r); }
    const ma = o.ajouter(o.trait(COULEURS.orange, { pointille: false, h: 0.006 })), mb = o.ajouter(o.trait(COULEURS.orange, { pointille: false, h: 0.006 }));
    const droit = o.ajouter(o.angleDroit(0.032));
    const labT = o.ajouter(etiquette('AM·BM = 0', { hauteur: 0.038 }));
    [ma, mb, droit, labT].forEach((x) => { x.visible = false; });
    o.maj.push(() => {
      const M = o.P(2 + R * Math.cos(etat.a), -3 + R * Math.sin(etat.a));
      m.position.copy(M);
      bras.userData.placer(Om, M);
      lab.position.copy(Om.clone().lerp(M, 0.5)).setY(0.06);
      if (etat.triangle) {
        ma.userData.placer(M, A); mb.userData.placer(M, B);
        droit.userData.orienter(M, A.clone().sub(M), B.clone().sub(M));
        labT.position.copy(M).add(new THREE.Vector3(0, 0.11, 0));
      }
    });
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { fenetre: F, axes: true });
        legendeImprimee(ctx, Om, 'Ω(2 ; −3)', -50, 40);
        legendeImprimee(ctx, A, 'A', -30, -30);
        legendeImprimee(ctx, B, 'B', 30, -30);
      },
      interactions: {
        omega: async () => {
          o.eclairer(om);
          rayons.forEach((r, i) => {
            const ang = (i / 8) * Math.PI * 2; r.visible = true;
            animer(0.7, (p) => r.userData.placer(Om, o.P(2 + R * p * Math.cos(ang), -3 + R * p * Math.sin(ang))), { delai: i * 0.05 });
          });
          o.apparaitre(lab);
          await attendre(0.9);
        },
        M: async () => { o.eclairer(m); lab.visible = true; const a0 = etat.a; await animer(2.6, (p) => { etat.a = a0 + p * Math.PI * 2; }); },
        diametre: async () => {
          o.eclairer(dia); etat.triangle = true;
          [ma, mb].forEach((x) => { x.visible = true; });
          o.apparaitre(droit); await o.apparaitre(labT);
          const a0 = etat.a; await animer(2.2, (p) => { etat.a = a0 + Math.sin(p * Math.PI) * 0.9; });
        },
      },
    };
  },

  parametrique(o, lecon) {
    const F = [-4.3, 2.6, -0.9, 8.3];
    const xa = -1, yb = 5, R = 2, Om = o.P(xa, yb);
    const etat = { t: Math.PI / 6 };
    const mur = o.ajouter(o.mur(R * o.s, { couleur: COULEURS.turquoise, haut: 0.035 })); mur.position.copy(Om);
    const om = o.ajouter(o.epingle(COULEURS.petrole, { haut: 0.05, tete: 0.012 })); om.position.copy(Om);
    const m = o.ajouter(o.cible('M', o.epingle(COULEURS.orange), 0.03));
    const bras = o.ajouter(o.trait(COULEURS.petrole, { pointille: false, h: 0.02 }));
    const vx = o.ajouter(o.trait()), vy = o.ajouter(o.trait());
    const perle = (c) => encrer(new THREE.Mesh(new THREE.SphereGeometry(0.016, 18, 12), papier(c, 0.85)), 60);
    const bx = o.ajouter(o.cible('projx', perle(COULEURS.orange), 0.035));
    const by = o.ajouter(o.cible('projy', perle(COULEURS.violet), 0.035));
    bx.userData.mat = bx.material; bx.userData.couleur = COULEURS.orange;
    by.userData.mat = by.material; by.userData.couleur = COULEURS.violet;
    const arc = o.ajouter(o.arc(COULEURS.violet));
    const lx = o.ajouter(etiquette('', { hauteur: 0.032 })), ly = o.ajouter(etiquette('', { hauteur: 0.032 }));
    lx.visible = ly.visible = false;
    const lt = o.ajouter(etiquette('θ', { hauteur: 0.034 }));
    o.maj.push(() => {
      const t = etat.t, x = xa + R * Math.cos(t), y = yb + R * Math.sin(t), M = o.P(x, y);
      m.position.copy(M); bras.userData.placer(Om, M);
      vx.userData.placer(M, o.P(x, 0)); vy.userData.placer(M, o.P(0, y));
      bx.position.copy(o.P(x, 0, 0.016)); by.position.copy(o.P(0, y, 0.016));
      const tt = ((t % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
      arc.userData.placer(Om, 0.6 * o.s, 0, tt || 0.0001);
      lt.position.copy(Om).add(new THREE.Vector3(0.9 * o.s * Math.cos(tt / 2), 0.01, -0.9 * o.s * Math.sin(tt / 2)));
      lx.position.copy(bx.position).add(new THREE.Vector3(0, 0.03, 0.06));
      ly.position.copy(by.position).add(new THREE.Vector3(-0.14, 0.03, 0));
      lx.userData.ecrire(`x = −1 + 2cos θ = ${fr(x, 1)}`);
      ly.userData.ecrire(`y = 5 + 2sin θ = ${fr(y, 1)}`);
    });
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { fenetre: F });
        legendeImprimee(ctx, Om, 'Ω(−1 ; 5)', -40, 50);
      },
      interactions: {
        M: async () => { o.eclairer(m); const t0 = etat.t; await animer(3, (p) => { etat.t = t0 + p * Math.PI * 2; }); },
        projx: async () => { o.eclairer(bx); lx.visible = true; await o.apparaitre(lx); },
        projy: async () => { o.eclairer(by); ly.visible = true; await o.apparaitre(ly); },
      },
    };
  },

  ensemble(o, lecon) {
    const F = [0, 10, 0, 10];
    const cas = [
      { id: 'vide', x: 1.9, d: -2, eq: ['x² + y² − 4x', '+ 6y + 15 = 0'], texte: 'd = 4 + 9 − 15 = −2 < 0  ⇒  ∅', c: COULEURS.rouge },
      { id: 'point', x: 5, d: 0, eq: ['x² + y² − 2x', '+ 6y + 10 = 0'], texte: 'd = 1 + 9 − 10 = 0  ⇒  {Ω(1 ; −3)}', c: COULEURS.or },
      { id: 'cercle', x: 8.1, d: 16, eq: ['x² + y² + 6x', '− 2y − 6 = 0'], texte: 'd = 9 + 1 + 6 = 16  ⇒  cercle, R = 4', c: COULEURS.turquoise },
    ];
    const bocal = o.ajouter(o.bocal(COULEURS.turquoise, { min: -16, max: 16, haut: 0.22 }));
    bocal.position.copy(o.P(5, 2.2));
    bocal.userData.etiquette.userData.ecrire('d = ?');
    const socles = {};
    for (const k of cas) {
      const g = o.ajouter(o.cible(k.id, new THREE.Group(), 0.09));
      g.position.copy(o.P(k.x, 6.4));
      const s = o.socle(0.085); s.userData.couleur = k.c; g.add(s); g.userData.mat = s.material; g.userData.couleur = k.c;
      if (k.id === 'vide') {
        const c = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(Array.from({ length: 48 }, (_, i) => new THREE.Vector3(0.055 * Math.cos(i / 48 * Math.PI * 2), 0.032, 0.055 * Math.sin(i / 48 * Math.PI * 2)))),
          new THREE.LineDashedMaterial({ color: ENCRE, dashSize: 0.01, gapSize: 0.008 }));
        c.computeLineDistances(); g.add(c);
        const e = etiquette('∅', { hauteur: 0.05 }); e.position.y = 0.04; g.add(e);
      } else if (k.id === 'point') {
        const e = o.epingle(COULEURS.or, { haut: 0.06, tete: 0.014 }); e.position.y = 0.03; g.add(e);
      } else {
        const m = o.mur(0.06, { couleur: COULEURS.turquoise, haut: 0.035 }); m.position.y = 0.03; g.add(m);
      }
      const t = etiquette(k.id === 'vide' ? 'd < 0' : k.id === 'point' ? 'd = 0' : 'd > 0', { hauteur: 0.036 });
      t.position.set(0, 0.11, 0); g.add(t);
      socles[k.id] = g;
    }
    const monter = async (k) => {
      for (const c of cas) { const g = socles[c.id]; const y0 = g.position.y; const y1 = c === k ? 0.035 : 0; animer(0.5, (p) => { g.position.y = y0 + (y1 - y0) * p; }, { courbe: ease.ressort }); }
      o.eclairer(socles[k.id]);
      bocal.userData.etiquette.userData.ecrire(k.texte);
      await bocal.userData.vers(k.d);
    };
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { grille: false, axes: false });
        ctx.font = 'italic 29px Newsreader, Georgia, serif';
        ctx.fillStyle = racineDom.classList.contains('contraste') ? '#000' : '#2b2620';
        ctx.textAlign = 'center';
        for (const k of cas) {    // l'équation sur deux lignes, sous chaque socle
          const [a, b] = versPage(o.P(k.x, 4.7));
          ctx.fillText(k.eq[0], a, b); ctx.fillText(k.eq[1], a, b + 34);
        }
        ctx.textAlign = 'left';
      },
      interactions: Object.fromEntries(cas.map((k) => [k.id, () => monter(k)])),
    };
  },

  interieur(o, lecon) {
    const F = [-2.9, 4.9, -5.5, 2.5];
    const Om = o.P(1, -2), R = Math.sqrt(5);
    const disque = new THREE.Mesh(new THREE.CircleGeometry(R * o.s, 80), new THREE.MeshBasicMaterial({ color: COULEURS.turquoise, transparent: true, opacity: 0.18, depthWrite: false }));
    disque.rotation.x = -Math.PI / 2; disque.position.copy(Om).setY(0.002); o.ajouter(disque);
    const mur = o.ajouter(o.mur(R * o.s, { couleur: COULEURS.turquoise, haut: 0.035 })); mur.position.copy(Om);
    const om = o.ajouter(o.epingle(COULEURS.petrole, { haut: 0.05, tete: 0.012 })); om.position.copy(Om);
    const points = [
      { id: 'dedans', x: 1.2, y: -1.2, f: 1.44 + 1.44 - 2.4 - 4.8, txt: 'f(M) = −4,32 < 0\nà l’intérieur', c: COULEURS.turquoise },
      { id: 'dessus', x: 3, y: -1, f: 0, txt: 'f(M) = 9 + 1 − 6 − 4 = 0\nsur le cercle', c: COULEURS.or },
      { id: 'dehors', x: 0, y: 1, f: 5, txt: 'f(A) = 0 + 1 − 0 + 4 = 5 > 0\nà l’extérieur', c: COULEURS.rouge },
    ];
    const act = {};
    for (const p of points) {
      const e = o.ajouter(o.cible(p.id, o.epingle(p.c), 0.03)); e.position.copy(o.P(p.x, p.y));
      const carte = o.ajouter(etiquette(p.txt, { hauteur: 0.03, fond: '#fbf6ea' }));
      carte.position.copy(e.position).add(new THREE.Vector3(0, 0.11, 0)); carte.visible = false;
      const lien = o.ajouter(o.trait()); lien.visible = false;
      act[p.id] = async () => {
        o.eclairer(e); lien.visible = true;
        await animer(0.6, (k) => lien.userData.placer(Om, Om.clone().lerp(e.position, k)));
        await o.apparaitre(carte);
      };
    }
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { fenetre: F });
        legendeImprimee(ctx, o.P(1, -2 - R), '(𝒞) : x² + y² − 2x + 4y = 0', 40, 50);
        legendeImprimee(ctx, o.P(0, 1), 'A(0 ; 1)', -40, -30);
      },
      interactions: act,
    };
  },

  positions(o, lecon) {
    const F = [-3.1, 6.9, -4.3, 4.5];
    const Om = o.P(2, -1), R = 2;
    const nx = 1 / Math.sqrt(5), ny = -2 / Math.sqrt(5), tx = 2 / Math.sqrt(5), ty = 1 / Math.sqrt(5);
    const ETATS = [
      { id: 'exterieure', d: -7 / Math.sqrt(5), txt: 'd = 7/√5 ≈ 3,13 > R = 2\naucun point commun' },
      { id: 'tangente', d: -2, txt: 'd = R = 2\nla droite est tangente en H' },
      { id: 'secante', d: -1, txt: 'd = 1 < R = 2\ndeux points A et B' },
    ];
    const etat = { d: ETATS[0].d, i: 0 };
    const mur = o.ajouter(o.mur(R * o.s, { couleur: COULEURS.turquoise, haut: 0.035 })); mur.position.copy(Om);
    const om = o.ajouter(o.epingle(COULEURS.petrole, { haut: 0.05, tete: 0.012 })); om.position.copy(Om);
    const regle = o.ajouter(o.cible('regle', o.bande(COULEURS.orange, { haut: 0.04 })));
    const dist = o.ajouter(o.trait());
    const lab = o.ajouter(etiquette(ETATS[0].txt, { hauteur: 0.03, fond: '#fbf6ea' }));
    const pins = [0, 1].map(() => { const p = o.ajouter(o.epingle(COULEURS.rouge, { haut: 0.06, tete: 0.013 })); p.visible = false; return p; });
    o.maj.push(() => {
      const cx = 2 + etat.d * nx, cy = -1 + etat.d * ny, L = 3.6;
      regle.userData.placer(o.P(cx - L * tx, cy - L * ty), o.P(cx + L * tx, cy + L * ty));
      dist.userData.placer(Om, o.P(cx, cy));
      lab.position.copy(o.P(cx + 2.2 * tx, cy + 2.2 * ty)).setY(0.08);
      const reste = R * R - etat.d * etat.d;
      if (reste >= -1e-3) {
        const h = Math.sqrt(Math.max(0, reste));
        pins[0].position.copy(o.P(cx - h * tx, cy - h * ty)); pins[1].position.copy(o.P(cx + h * tx, cy + h * ty));
      }
    });
    const aller = async (id) => {
      const i = ETATS.findIndex((e) => e.id === id);
      etat.i = i;
      o.eclairer(regle);
      pins.forEach((p) => { p.visible = false; });
      const d0 = etat.d;
      await animer(1.1, (p) => { etat.d = d0 + (ETATS[i].d - d0) * p; });
      lab.userData.ecrire(ETATS[i].txt);
      if (id === 'tangente') o.apparaitre(pins[0]);
      if (id === 'secante') { o.apparaitre(pins[0]); o.apparaitre(pins[1]); }
      o.marquer(id);
    };
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { fenetre: F });
        legendeImprimee(ctx, Om, 'Ω(2 ; −1), R = 2', 40, 60);
      },
      interactions: {
        regle: () => aller(ETATS[(etat.i + (o.vus.has(ETATS[etat.i].id) ? 1 : 0)) % 3].id),
        exterieure: () => aller('exterieure'),
        tangente: () => aller('tangente'),
        secante: () => aller('secante'),
      },
    };
  },

  tangente(o, lecon) {
    const F = [-2.3, 7.4, -5.2, 4.7];
    const xo = 2, yo = -1, R = Math.sqrt(10), Om = o.P(xo, yo), a0 = Math.atan2(3, 1);
    const etat = { a: a0, k: 0 };
    const mur = o.ajouter(o.mur(R * o.s, { couleur: COULEURS.turquoise, haut: 0.035 })); mur.position.copy(Om);
    const om = o.ajouter(o.epingle(COULEURS.petrole, { haut: 0.05, tete: 0.012 })); om.position.copy(Om);
    const a = o.ajouter(o.cible('A', o.epingle(COULEURS.rouge), 0.03));
    const rayon = o.ajouter(o.cible('rayon', o.bande(COULEURS.petrole, { haut: 0.02 })));
    const t = o.ajouter(o.cible('T', o.bande(COULEURS.orange, { haut: 0.04 })));
    const droit = o.ajouter(o.angleDroit(0.034)); droit.visible = false;
    const m = o.ajouter(o.epingle(COULEURS.turquoise, { haut: 0.06, tete: 0.013 })); m.visible = false;
    const ao = o.ajouter(o.trait()), am = o.ajouter(o.trait(COULEURS.turquoise));
    ao.visible = am.visible = false;
    const lab = o.ajouter(etiquette('ΩA ⟂ (T)', { hauteur: 0.036 })); lab.visible = false;
    const labM = o.ajouter(etiquette('AΩ·AM = 0', { hauteur: 0.036 })); labM.visible = false;
    o.maj.push(() => {
      const ax = xo + R * Math.cos(etat.a), ay = yo + R * Math.sin(etat.a), A = o.P(ax, ay);
      const ux = -Math.sin(etat.a), uy = Math.cos(etat.a);
      a.position.copy(A);
      rayon.userData.placer(Om, A);
      t.userData.placer(o.P(ax - 3.2 * ux, ay - 3.2 * uy), o.P(ax + 3.2 * ux, ay + 3.2 * uy));
      droit.userData.orienter(A, Om.clone().sub(A), o.P(ax + ux, ay + uy).sub(A));
      lab.position.copy(Om.clone().lerp(A, 0.5)).setY(0.07);
      const M = o.P(ax + etat.k * ux, ay + etat.k * uy);
      m.position.copy(M); ao.userData.placer(A, Om); am.userData.placer(A, M);
      labM.position.copy(M).add(new THREE.Vector3(0, 0.1, 0));
    });
    return {
      imprimer(ctx) {
        imprimerBase(ctx, lecon, o, { fenetre: F });
        legendeImprimee(ctx, Om, 'Ω(2 ; −1)', -40, 50);
        legendeImprimee(ctx, o.P(3, 2), 'A(3 ; 2)', 50, -30);
      },
      interactions: {
        rayon: async () => { o.eclairer(rayon); o.apparaitre(droit); await o.apparaitre(lab); },
        T: async () => {
          o.eclairer(t); m.visible = ao.visible = am.visible = labM.visible = true;
          await animer(1.3, (p) => { etat.k = 2.4 * p; });
          await animer(1.6, (p) => { etat.k = 2.4 - 4.4 * p; });
        },
        A: async () => {
          o.eclairer(a);
          await animer(1.8, (p) => { etat.a = a0 + p * Math.PI / 2; });
          await animer(1.8, (p) => { etat.a = a0 + Math.PI / 2 - p * Math.PI / 2; });
        },
      },
    };
  },
};

// ---------------------------------------------------------------- Page de gauche (HTML dans le livre)
const gabarit = document.getElementById('gabaritPage').content.firstElementChild;
const pageDom = gabarit.cloneNode(true);
const pageCss = new CSS3DObject(pageDom);
const LARG_PAGE = 0.92;
pageCss.scale.setScalar(LARG_PAGE / 1000);
pageCss.rotation.x = -Math.PI / 2;
pageCss.position.set(-(0.065 + LARG_PAGE / 2), H + 0.0015, 0);
sceneCss.add(pageCss);
// Rabat « Pourquoi ? » : objet 3D à part, articulé sur son bord supérieur (coordonnées en px de la page).
const rabatEl = pageDom.querySelector('.pg-rabat');
rabatEl.remove();
const charniere = new THREE.Object3D();
charniere.position.set(92 + 329 - 500, -(1050 - 680), 1);
const rabatCss = new CSS3DObject(rabatEl);
rabatCss.position.set(0, -125, 0);
charniere.add(rabatCss);
pageCss.add(charniere);
// Commandes de la page : un appui dessus ne fait pas tourner la caméra.
for (const el of [pageDom, rabatEl]) el.addEventListener('pointerdown', (e) => { if (e.target.closest('button')) e.stopPropagation(); });
function ouvrirRabat(ouvert, instantane) {
  rabatEl.classList.toggle('ouvert', ouvert);
  rabatEl.setAttribute('aria-expanded', ouvert ? 'true' : 'false');
  const a = charniere.rotation.x, b = ouvert ? -THREE.MathUtils.degToRad(76) : 0;
  if (instantane) { charniere.rotation.x = b; return Promise.resolve(); }
  return animer(0.9, (p) => { charniere.rotation.x = a + (b - a) * p; }, { courbe: ouvert ? ease.ressort : ease.inOut });
}

function melanger(lecon) {   // ordre des réponses propre à chaque leçon, stable d'une visite à l'autre
  const idx = lecon.predict.choices.map((_, i) => i);
  let graine = [...lecon.id].reduce((a, c) => a * 31 + c.charCodeAt(0), 7);
  for (let i = idx.length - 1; i > 0; i--) { graine = (graine * 1103515245 + 12345) % 2147483648; const j = graine % (i + 1); [idx[i], idx[j]] = [idx[j], idx[i]]; }
  return idx;
}

const mathPret = (() => {
  const m = window.MathJax;
  return (m && m.startup && m.startup.promise) ? m.startup.promise.catch(() => {}) : Promise.resolve();
})();
async function typeset(el) {
  await mathPret;
  const m = window.MathJax;
  if (!m || !m.typesetPromise) return;
  try { m.typesetClear([el]); await m.typesetPromise([el]); } catch (e) { /* formule invalide : texte brut */ }
}

async function remplirPage(i) {
  const lecon = lecons[i];
  const q = (s) => pageDom.querySelector(s);
  q('.pg-num').textContent = `Leçon ${lecon.number} · ${i + 1}/${lecons.length}`;
  q('.pg-cours').textContent = donnees.lesson.title;
  q('.pg-titre').textContent = lecon.title;
  q('.pg-concept').textContent = lecon.concept;
  const formule = q('.pg-formule'); formule.replaceChildren();
  for (const f of lecon.formula) {    // ligne déjà mixte (texte + \\( \\)) ou formule seule centrée
    const d = document.createElement('div'); d.className = 'ligne'; d.textContent = f.includes('\\(') ? f : `\\[${f}\\]`; formule.appendChild(d);
  }
  const vocab = q('.pg-vocab'); vocab.replaceChildren();
  for (const v of lecon.vocabulary) {
    const dt = document.createElement('dt'); dt.textContent = v.term;
    const dd = document.createElement('dd'); dd.textContent = v.definition;
    vocab.append(dt, dd);
  }
  q('.pg-question').textContent = lecon.predict.question;
  const choix = q('.pg-choix'); choix.replaceChildren();
  choix.setAttribute('aria-label', 'Choisis ta prédiction');
  const deja = progression.predictions[lecon.id];
  for (const k of melanger(lecon)) {
    const b = document.createElement('button');
    b.type = 'button'; b.textContent = lecon.predict.choices[k]; b.dataset.choix = k;
    b.addEventListener('click', () => predire(lecon, k));
    choix.appendChild(b);
  }
  q('.pg-explication').textContent = lecon.flap;
  ouvrirRabat(false, true);
  majPrediction(lecon, deja);
  majTampon(lecon, false);
  await typeset(pageDom);
  ajusterPage();
}
function ajusterPage() {    // réduit le texte si la page déborde sur le rabat
  const zone = pageDom.querySelector('.pg-rabat-zone');
  const predire = pageDom.querySelector('.pg-predire');
  let taille = 27;
  pageDom.style.fontSize = taille + 'px';
  while (taille > 17 && predire.offsetTop + predire.offsetHeight > zone.offsetTop - 14) {
    taille -= 1; pageDom.style.fontSize = taille + 'px';
  }
}
function majPrediction(lecon, choisi) {
  const rabat = rabatEl;
  pageDom.querySelectorAll('.pg-choix button').forEach((b) => {
    const k = +b.dataset.choix;
    b.disabled = choisi != null;
    b.classList.toggle('choisi', k === choisi);
    b.classList.toggle('juste', choisi != null && k === lecon.predict.answer);
    b.classList.toggle('faux', choisi != null && k === choisi && k !== lecon.predict.answer);
    b.setAttribute('aria-pressed', k === choisi ? 'true' : 'false');
  });
  rabat.disabled = choisi == null;
  rabatEl.querySelector('.rabat-aide').textContent = choisi == null ? "Fais d'abord ta prédiction"
    : (choisi === lecon.predict.answer ? 'Bonne intuition ! Soulève le rabat' : 'Pas tout à fait. Soulève le rabat');
}
function predire(lecon, k) {
  if (progression.predictions[lecon.id] != null || occupe) return;
  progression.predictions[lecon.id] = k;
  sauver();
  son(k === lecon.predict.answer ? 'juste' : 'faux');
  majPrediction(lecon, k);
}
rabatEl.addEventListener('click', () => {
  if (rabatEl.disabled || occupe) return;
  ouvrirRabat(!rabatEl.classList.contains('ouvert'));
  son('page');
});
function majTampon(lecon, animer) {
  const t = pageDom.querySelector('.pg-tampon');
  const fait = !!progression.tampons[lecon.id];
  const n = (progression.faits[lecon.id] || []).length, total = lecon.scene.interactions.length;
  t.classList.toggle('encre', fait);
  if (animer && fait) { t.classList.remove('encre'); void t.offsetWidth; t.classList.add('encre'); }
  t.querySelector('.tampon-etat').textContent = fait ? 'Leçon explorée' : `${n}/${total} figures explorées`;
}

// ---------------------------------------------------------------- Scène courante (page de droite)
let courante = Math.min(Math.max(+progression.page || 0, 0), lecons.length - 1);
let figure = null;        // { root, outils, def }
let occupe = false;       // pendant un tour de page
const groupeFigures = new THREE.Group();
livre.add(groupeFigures);

function construireFigure(i) {
  const lecon = lecons[i];
  const root = new THREE.Group();
  root.position.set(CX, hauteurPage(CX) + 0.0015, CZ);
  const fenetres = { produit: [-1.5, 8.6, -3.6, 7.2], angle: [-3.3, 3.3, -1.7, 3.4], droite: [-3.3, 4.6, -3.6, 4.6], cercle: [-4.2, 8.4, -9.2, 3.3],
    parametrique: [-4.3, 2.6, -0.9, 8.3], ensemble: [0, 10, 0, 10], interieur: [-2.9, 4.9, -5.5, 2.5], positions: [-3.1, 6.9, -4.3, 4.5], tangente: [-2.3, 7.4, -5.2, 4.7] };
  const outils = creerOutils(root, fenetres[lecon.scene.type]);
  outils.vus = new Set(progression.faits[lecon.id] || []);
  outils.marquer = (id) => marquer(lecon, id);
  const def = SCENES[lecon.scene.type](outils, lecon);
  groupeFigures.add(root);
  return { root, outils, def, lecon };
}
function imprimer(fig) {
  const ctx = canevasDroite.getContext('2d');
  fig.def.imprimer(ctx);
  textureDroite.needsUpdate = true;
}
function detruire(fig) {
  if (!fig) return;
  groupeFigures.remove(fig.root);
  fig.root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material && o.material.map && o.isSprite) o.material.map.dispose();
    if (o.material && o.material !== matEncre) { (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => { materiauxPapier.delete(m); m.dispose(); }); }
  });
}
function plier(fig, vers, duree = 0.45) {       // les figures se couchent dans la page / se redressent
  const sprites = [];
  fig.root.traverse((o) => { if (o.isSprite) sprites.push(o); });
  const a = fig.root.scale.y;
  return animer(duree, (p) => {
    fig.root.scale.y = Math.max(0.01, a + (vers - a) * p);
    sprites.forEach((s) => { s.material.opacity = Math.min(1, fig.root.scale.y); });
  }, { courbe: vers > a ? ease.ressort : ease.out });
}
function marquer(lecon, id) {
  if (!lecon.scene.interactions.includes(id)) return;
  const faits = new Set(progression.faits[lecon.id] || []);
  if (faits.has(id)) return;
  faits.add(id);
  progression.faits[lecon.id] = [...faits];
  if (figure && figure.lecon === lecon) figure.outils.vus.add(id);
  const complet = lecon.scene.interactions.every((x) => faits.has(x));
  if (complet && !progression.tampons[lecon.id]) {
    progression.tampons[lecon.id] = true;
    setTimeout(() => son('tampon'), 250);
  }
  sauver();
  majTampon(lecon, complet);
  majSommaire();
}
async function declencher(id) {
  if (!figure || occupe) return;
  const action = figure.def.interactions[id];
  if (!action) return;
  son('clic');
  marquer(figure.lecon, id);
  await action();
}

// ---------------------------------------------------------------- Feuille qui tourne
const geoFeuille = new THREE.PlaneGeometry(W, D, 40, 1).rotateX(-Math.PI / 2).translate(W / 2, 0, 0);
const baseFeuille = geoFeuille.attributes.position.array.slice();
const canevasRecto = canevas(IMP.l, IMP.h);
const textureRecto = texture(canevasRecto);
const feuille = new THREE.Group();
const recto = new THREE.Mesh(geoFeuille, new THREE.MeshStandardMaterial({ map: textureRecto, roughness: 0.95, side: THREE.FrontSide }));
const verso = new THREE.Mesh(geoFeuille, new THREE.MeshStandardMaterial({ map: papierGauche, roughness: 0.95, side: THREE.BackSide }));
recto.castShadow = verso.castShadow = true;
recto.frustumCulled = verso.frustumCulled = false;   // la feuille sort de sa boîte englobante en tournant
feuille.add(recto, verso);
feuille.visible = false;
livre.add(feuille);
function plierFeuille(t) {          // t = 0 : à droite, t = 1 : à gauche
  const pos = geoFeuille.attributes.position;
  const boucle = -Math.sin(t * Math.PI) * 0.85;
  for (let i = 0; i < pos.count; i++) {
    const r = baseFeuille[i * 3];
    const u = r / W;
    const ang = t * Math.PI + boucle * u * u;
    pos.setX(i, r * Math.cos(ang));
    pos.setY(i, H + 0.004 + r * Math.sin(ang) * 0.92 + Math.sin(t * Math.PI) * 0.02);
  }
  pos.needsUpdate = true;
  geoFeuille.computeVertexNormals();
}

async function allerA(i, { sens } = {}) {
  if (occupe || i === courante || i < 0 || i >= lecons.length) return;
  arreterDemo();
  occupe = true;
  majHud();
  controls.enabled = false;
  const avant = sens != null ? sens : i > courante;
  const ancienne = figure;
  son('page');
  pageDom.classList.add('change');
  rabatEl.classList.add('change');
  if (reduit()) {
    detruire(ancienne);
    courante = i;
    figure = construireFigure(i);
    imprimer(figure);
    await remplirPage(i);
    pageDom.classList.remove('change'); rabatEl.classList.remove('change');
  } else {
    await plier(ancienne, 0.01, 0.4);
    canevasRecto.getContext('2d').drawImage(avant ? canevasDroite : papierDroiteBase, 0, 0);
    detruire(ancienne);
    courante = i;
    figure = construireFigure(i);
    figure.root.scale.y = 0.01;
    if (avant) imprimer(figure);
    else { figure.def.imprimer(canevasRecto.getContext('2d')); figure.root.visible = false; }
    textureRecto.needsUpdate = true;
    feuille.visible = true;
    plierFeuille(avant ? 0 : 1);
    const remplir = remplirPage(i);
    await animer(1.25, (p) => plierFeuille(avant ? p : 1 - p), { courbe: ease.inOut });
    feuille.visible = false;
    if (!avant) { imprimer(figure); figure.root.visible = true; }
    await remplir;
    pageDom.classList.remove('change'); rabatEl.classList.remove('change');
    await plier(figure, 1, 0.9);
  }
  progression.page = i;
  sauver();
  occupe = false;
  controls.enabled = !demoActive;
  majHud();
  majSommaire();
}

// ---------------------------------------------------------------- Caméra
const controls = new OrbitControls(camera, conteneur);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 0.45;
controls.maxPolarAngle = 1.36;
controls.minPolarAngle = 0.05;
controls.rotateSpeed = 0.7;
controls.zoomSpeed = 0.9;
controls.screenSpacePanning = true;
controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };
const LIMITES = new THREE.Box3(new THREE.Vector3(-1.3, 0.02, -0.95), new THREE.Vector3(1.3, 0.45, 0.95));
controls.addEventListener('change', () => {          // empêche d'emmener la cible hors du bureau
  const avant = controls.target.clone();
  LIMITES.clampPoint(controls.target, controls.target);
  if (!avant.equals(controls.target)) camera.position.add(controls.target.clone().sub(avant));
  if (camera.position.y < 0.12) camera.position.y = 0.12;
});

function vueInitiale() {
  const aspect = camera.aspect;
  const t = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const dist = Math.max(2.45 / (2 * t * aspect), 1.75 / (2 * t)) * 1.02;
  const pitch = THREE.MathUtils.degToRad(60);
  const cible = new THREE.Vector3(0, 0.04, 0.06);
  return { pos: cible.clone().add(new THREE.Vector3(0, Math.sin(pitch), Math.cos(pitch)).multiplyScalar(dist)), cible, dist };
}
let vol = null;
function voler(pos, cible, duree = 1.6) {
  if (vol) { vol.fin(false); vol = null; }
  if (reduit() || duree <= 0) {
    camera.position.copy(pos); controls.target.copy(cible); camera.lookAt(cible);
    return Promise.resolve(true);
  }
  return new Promise((fin) => {
    vol = { p0: camera.position.clone(), c0: controls.target.clone(), p1: pos.clone(), c1: cible.clone(), debut: performance.now(), duree: duree * 1000, fin };
  });
}
function plan(nom, cibleId) {
  const v = vueInitiale();
  if (nom === 'overview' || !figure) return { pos: v.pos, cible: v.cible };
  const F = new THREE.Vector3();
  const obj = cibleId && figure.outils.cibles.get(cibleId);
  if (obj) obj.getWorldPosition(F); else figure.root.getWorldPosition(F);
  F.y = Math.max(F.y, H) + 0.03;
  const k = Math.max(1, 1.25 / Math.min(camera.aspect, 1.25));
  const decalage = {
    close: new THREE.Vector3(0.16, 0.42, 0.44), low: new THREE.Vector3(0.05, 0.13, 0.62),
    top: new THREE.Vector3(0, 0.98, 0.03), side: new THREE.Vector3(0.72, 0.17, 0.08),
  }[nom] || new THREE.Vector3(0.16, 0.42, 0.44);
  return { pos: F.clone().add(decalage.multiplyScalar(k)), cible: F };
}
function reinitialiserVue() {
  const v = vueInitiale();
  return voler(v.pos, v.cible, 1.2);
}

// ---------------------------------------------------------------- Démonstration guidée
let demoActive = false;
let jetonDemo = 0;
const legende = document.getElementById('livreLegende');
function arreterDemo() {
  if (!demoActive) return;
  demoActive = false;
  jetonDemo++;
  if (vol) { vol.fin(false); vol = null; }
  legende.hidden = true;
  controls.enabled = !occupe;
  majHud();
}
async function lancerDemo() {
  if (occupe || !figure) return;
  if (demoActive) { arreterDemo(); return; }
  demoActive = true;
  const jeton = ++jetonDemo;
  controls.enabled = false;
  majHud();
  const vivant = () => demoActive && jeton === jetonDemo;
  for (const etape of figure.lecon.demo) {
    if (!vivant()) return;
    legende.textContent = etape.caption;
    legende.hidden = false;
    legende.style.animation = 'none'; void legende.offsetWidth; legende.style.animation = '';
    if (!reduit()) { const v = plan(etape.shot, etape.target); await voler(v.pos, v.cible, 1.8); }
    if (!vivant()) return;
    await attendre(0.5);
    if (etape.action) declencher(etape.action);
    await attendre(etape.action ? 3.2 : 2.2);
  }
  if (!vivant()) return;
  legende.hidden = true;
  if (!reduit()) await reinitialiserVue();
  if (vivant()) { demoActive = false; controls.enabled = !occupe; majHud(); }
}

// ---------------------------------------------------------------- Clics sur les figures (sans confondre avec un glissement)
const rayon = new THREE.Raycaster();
const souris = new THREE.Vector2();
let appui = null;
conteneur.addEventListener('pointerdown', (e) => {
  appui = { x: e.clientX, y: e.clientY, t: performance.now() };
  if (demoActive) arreterDemo();        // reprendre la main pendant une démonstration
  if (vol && !demoActive) { vol.fin(false); vol = null; }
}, true);
function pointe(e) {
  const r = renderer.domElement.getBoundingClientRect();
  souris.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  rayon.setFromCamera(souris, camera);
  if (!figure) return null;
  for (const hit of rayon.intersectObject(figure.root, true)) {
    let o = hit.object;
    if (o.isLine || o.isPoints || o.isSprite) continue;
    while (o && o.userData.cible == null && o !== figure.root) o = o.parent;
    if (o && o.userData.cible != null) return o.userData.cible;
  }
  return null;
}
conteneur.addEventListener('pointerup', (e) => {
  if (!appui) return;
  const deplace = Math.hypot(e.clientX - appui.x, e.clientY - appui.y);
  const duree = performance.now() - appui.t;
  appui = null;
  if (deplace > 6 || duree > 700 || e.target.closest('.page-gauche')) return;
  const id = pointe(e);
  if (id) declencher(id);
});
let survol = 0;
conteneur.addEventListener('pointermove', (e) => {
  if (e.buttons || e.pointerType !== 'mouse' || performance.now() - survol < 60) return;
  survol = performance.now();
  conteneur.style.cursor = !e.target.closest('.page-gauche') && pointe(e) ? 'pointer' : '';
});

// ---------------------------------------------------------------- Barre de navigation, sommaire, réglages
const $ = (id) => document.getElementById(id);
function majHud() {
  const l = lecons[courante];
  $('hudTitre').innerHTML = '';
  const b = document.createElement('b'); b.textContent = l.number;
  $('hudTitre').append(b, document.createTextNode(l.title));
  $('hudPrec').disabled = occupe || courante === 0;
  $('hudSuiv').disabled = occupe || courante === lecons.length - 1;
  $('hudDemo').disabled = occupe;
  $('hudDemo').textContent = demoActive ? '❚❚' : '▶';
  $('hudDemo').setAttribute('aria-pressed', demoActive ? 'true' : 'false');
  $('hudDemo').setAttribute('aria-label', demoActive ? 'Arrêter la démonstration' : 'Lancer la démonstration');
  $('hudSon').setAttribute('aria-pressed', reglages.son ? 'true' : 'false');
  $('hudContraste').setAttribute('aria-pressed', reglages.contraste ? 'true' : 'false');
  $('hudMouvement').setAttribute('aria-pressed', reduit() ? 'true' : 'false');
}
function majSommaire() {
  const ol = $('tiroirListe');
  ol.replaceChildren();
  lecons.forEach((l, i) => {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.type = 'button';
    if (i === courante) b.setAttribute('aria-current', 'true');
    const n = document.createElement('span'); n.className = 'n'; n.textContent = l.number;
    const t = document.createElement('span'); t.textContent = l.title;
    const f = document.createElement('span'); f.className = 'fait'; f.textContent = progression.tampons[l.id] ? '✓' : '';
    if (progression.tampons[l.id]) f.setAttribute('aria-label', 'explorée');
    b.append(n, t, f);
    b.addEventListener('click', () => { fermerSommaire(); allerA(i); });
    li.appendChild(b); ol.appendChild(li);
  });
}
function ouvrirSommaire() { $('livreTiroir').hidden = false; $('hudSommaire').setAttribute('aria-expanded', 'true'); $('tiroirListe').querySelector('button')?.focus(); }
function fermerSommaire() { $('livreTiroir').hidden = true; $('hudSommaire').setAttribute('aria-expanded', 'false'); }
$('hudSommaire').addEventListener('click', () => ($('livreTiroir').hidden ? ouvrirSommaire() : fermerSommaire()));
$('tiroirFermer').addEventListener('click', () => { fermerSommaire(); $('hudSommaire').focus(); });
$('hudPrec').addEventListener('click', () => allerA(courante - 1));
$('hudSuiv').addEventListener('click', () => allerA(courante + 1));
$('hudDemo').addEventListener('click', lancerDemo);
$('hudVue').addEventListener('click', () => { arreterDemo(); reinitialiserVue(); });
$('hudSon').addEventListener('click', () => { reglages.son = !reglages.son; ecrire(CLE_REGLAGES, reglages); if (reglages.son) son('clic'); majHud(); });
$('hudContraste').addEventListener('click', () => {
  reglages.contraste = !reglages.contraste; ecrire(CLE_REGLAGES, reglages);
  racineDom.classList.toggle('contraste', reglages.contraste);
  appliquerContraste(); majHud();
});
$('hudMouvement').addEventListener('click', () => {
  const r = !reduit();
  reglages.mouvement = !r; ecrire(CLE_REGLAGES, reglages);
  racineDom.classList.toggle('mouvement-reduit', r);
  if (r) arreterDemo();
  majHud();
});
document.addEventListener('keydown', (e) => {
  if (e.altKey || e.ctrlKey || e.metaKey || e.target.closest('input, textarea, select')) return;
  if (e.key === 'ArrowRight' || e.key === 'PageDown') { allerA(courante + 1); e.preventDefault(); }
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { allerA(courante - 1); e.preventDefault(); }
  else if (e.key === 'Escape') { if (!$('livreTiroir').hidden) fermerSommaire(); else arreterDemo(); }
});
function appliquerContraste() {
  const c = reglages.contraste;
  for (const m of materiauxPapier) {
    const base = c ? PAPIER_CONTRASTE : PAPIER;
    m.color.copy(base);
    if (m.userData.teinte) m.color.lerp(m.userData.teinte, m.userData.force || 0.3);
  }
  bureau.material.color.set(c ? 0x555555 : 0xffffff);
  scene.background.set(c ? 0x1a1a1a : 0x3b3128);
  if (figure) imprimer(figure);
}

// ---------------------------------------------------------------- Taille et boucle de rendu
function redimensionner() {
  const l = conteneur.clientWidth, h = conteneur.clientHeight;
  camera.aspect = l / h;
  camera.updateProjectionMatrix();
  renderer.setSize(l, h);
  rendererCss.setSize(l, h);
  controls.maxDistance = Math.max(4.6, vueInitiale().dist * 1.35);
}
window.addEventListener('resize', redimensionner);

const horloge = new THREE.Clock();
function boucle() {
  const dt = Math.min(horloge.getDelta(), 0.05);
  const now = performance.now();
  for (const tw of tweens) {
    const p = Math.min(1, (now - tw.debut) / tw.duree);
    if (p < 0) continue;
    tw.maj(tw.courbe(p));
    if (p >= 1) { tweens.delete(tw); tw.fin(); }
  }
  if (vol) {
    const p = Math.min(1, (now - vol.debut) / vol.duree), e = ease.inOut(p);
    camera.position.lerpVectors(vol.p0, vol.p1, e);
    controls.target.lerpVectors(vol.c0, vol.c1, e);
    camera.lookAt(controls.target);
    if (p >= 1) { const f = vol.fin; vol = null; f(true); }
  } else if (controls.enabled) {
    controls.update();
  } else {
    camera.lookAt(controls.target);
  }
  if (figure) figure.outils.maj.forEach((f) => f(dt));
  renderer.render(scene, camera);
  rendererCss.render(sceneCss, camera);
  requestAnimationFrame(boucle);
}

// ---------------------------------------------------------------- Démarrage
(async function demarrer() {
  redimensionner();
  const v = vueInitiale();
  camera.position.copy(v.pos);
  controls.target.copy(v.cible);
  controls.update();
  try { await Promise.race([document.fonts.ready, new Promise((r) => setTimeout(r, 2500))]); } catch (e) { /* polices facultatives */ }
  figure = construireFigure(courante);
  imprimer(figure);
  appliquerContraste();
  rendererCss.render(sceneCss, camera);   // la page doit être dans le document avant MathJax
  await remplirPage(courante);
  majHud();
  majSommaire();
  app.classList.add('livre-pret');
  boucle();
  if (!reduit()) { figure.root.scale.y = 0.01; plier(figure, 1, 1.1); }
})();

// Accès pour les tests automatisés et le débogage.
window.Livre3D = {
  lecon: () => courante,
  occupe: () => occupe || !!vol,
  demo: () => demoActive,
  aller: (i) => allerA(i),
  declencher: (id) => declencher(id),
  ecran(id) {
    const o = figure && figure.outils.cibles.get(id);
    if (!o) return null;
    let repere = o;   // le centre de la zone cliquable (invisible) si l'objet en a une
    o.traverse((x) => { if (repere === o && x.isMesh && x.material && x.material.visible === false) repere = x; });
    const p = new THREE.Vector3(); repere.getWorldPosition(p);
    if (repere === o) p.y += 0.03;
    p.project(camera);
    const r = renderer.domElement.getBoundingClientRect();
    return { x: r.left + (p.x + 1) / 2 * r.width, y: r.top + (1 - p.y) / 2 * r.height };
  },
  camera: () => ({ x: camera.position.x, y: camera.position.y, z: camera.position.z, d: camera.position.distanceTo(controls.target) }),
  progression: () => JSON.parse(JSON.stringify(progression)),
  feuille(t) { feuille.visible = t != null; if (t != null) plierFeuille(t); },   // aperçu figé pour les tests
};
