/* Situation problème « le travail d'une force » (produit scalaire, 1ère Bac SE).
   Scène Three.js (static/vendor/three) : une personne tire une caisse de A vers B ; vecteurs
   F, AB, angle θ, composantes, poids et réaction. Huit étapes, de l'observation à la définition.
   → / ← (cours.js) parcourent les étapes : racine.etapesInternes = { avancer, reculer }.
   Sans WebGL, la figure SVG de secours reste affichée et les calculs restent interactifs. */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ------------------------------------------------------------------ Calculs (affichés en français)
const RAD = Math.PI / 180;
function nombre(x, decimales = 1) {
  if (Math.abs(x) < 1e-9) x = 0;
  return x.toLocaleString('fr-FR', { maximumFractionDigits: decimales }).replace('-', '−');
}
function cosinus(deg) {
  const c = Math.cos(deg * RAD);
  return Math.abs(c) < 1e-12 ? 0 : c;
}
export function travail(F, d, theta) { return F * d * cosinus(theta); }
function texteCos(theta) {
  const exacts = { 0: '1', 60: '0,5', 90: '0', 120: '−0,5', 180: '−1' };
  return exacts[theta] ?? nombre(cosinus(theta), 3);
}

function demarrer(racine) {
  const $ = (sel) => racine.querySelector(sel);
  const $$ = (sel) => Array.from(racine.querySelectorAll(sel));
  const etapes = $$('.sp-etape');
  const curseurs = { F: $('[data-r="F"]'), theta: $('[data-r="theta"]'), d: $('[data-r="d"]') };
  const sorties = { F: $('[data-o="F"]'), theta: $('[data-o="theta"]'), d: $('[data-o="d"]') };
  const etat = { F: 40, theta: 60, d: 5, x: 0, mode: 'physique', montrer: new Set(), etape: 0, revele: new Set() };
  const reduit = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Points de progression
  const points = $('[data-points]');
  etapes.forEach(() => points.appendChild(document.createElement('li')));

  let scene3d = null;
  try { scene3d = creerScene($('[data-scene]'), racine, etat); } catch (e) { scene3d = null; }
  if (scene3d) {
    racine.classList.add('en-3d');
    $('[data-aide-3d]').hidden = false;
  } else {
    ['[data-lancer]', '[data-replacer]', '[data-vue]'].forEach((s) => { $(s).hidden = true; });
  }

  // ---------------------------------------------------------------- Valeurs affichées
  function majValeurs() {
    const { F, theta, d } = etat;
    sorties.F.textContent = `${F} N`;
    sorties.theta.textContent = `${theta}°`;
    sorties.d.textContent = `${nombre(d)} m`;
    $('[data-mesures]').textContent = `F = ${F} N · θ = ${theta}° · AB = ${nombre(d)} m`;
    const Fx = F * cosinus(theta);
    const W = travail(F, d, theta);
    const w = $('[data-v="W"]');
    if (w) w.textContent = `Fx × AB = ${nombre(Fx, 2)} × ${nombre(d)} = ${nombre(W, 2)} J`;
    const p = $('[data-v="produit"]');
    if (p) p.textContent = `${F} × ${nombre(d)} × ${texteCos(theta)} = ${nombre(W, 2)}`;
    const signe = $('[data-v="signe"]');
    if (signe) {
      const genre = Math.abs(W) < 1e-9 ? 'nul' : (W > 0 ? 'positif' : 'negatif');
      const mot = { positif: 'positif', nul: 'nul', negatif: 'négatif' }[genre];
      signe.innerHTML = '';
      signe.append(`= ${F} × ${nombre(d)} × cos ${theta}° = ${nombre(W, 2)} : `);
      const b = document.createElement('span');
      b.className = genre;
      b.textContent = mot;
      signe.append(b);
    }
    $$('[data-angle]').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.angle) === theta)));
    $('[data-scene]').setAttribute('aria-label', etat.mode === 'physique'
      ? `Scène : une personne tire une caisse de A vers B ; F = ${F} N, θ = ${theta}°, AB = ${nombre(d)} m.`
      : `Scène : vecteurs F et AB formant un angle de ${theta}° ; produit scalaire ${nombre(W, 2)}.`);
    if (scene3d) scene3d.maj();
  }

  let cadrerPlusTard = false;
  Object.entries(curseurs).forEach(([cle, input]) => {
    input.addEventListener('input', () => {
      etat[cle] = Number(input.value);
      etat.x = 0;
      majValeurs();
    });
    // Nouvelle distance AB : la vue de face reprend tout le trajet.
    if (cle === 'd') input.addEventListener('change', () => { if (scene3d) scene3d.vueDeFace(); });
  });
  $$('[data-angle]').forEach((b) => b.addEventListener('click', () => {
    etat.theta = Number(b.dataset.angle);
    curseurs.theta.value = String(etat.theta);
    majValeurs();
  }));

  // ---------------------------------------------------------------- Lancer / replacer / vue
  let animation = null;
  $('[data-lancer]').addEventListener('click', () => {
    cancelAnimationFrame(animation);
    if (reduit || !scene3d) { etat.x = etat.d; majValeurs(); return; }
    if (scene3d) scene3d.vueDeFace();
    const debut = performance.now();
    const duree = 2200;
    etat.x = 0;
    const pas = (t) => {
      const u = Math.min(1, (t - debut) / duree);
      etat.x = etat.d * (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
      scene3d.maj();
      if (u < 1) animation = requestAnimationFrame(pas);
    };
    animation = requestAnimationFrame(pas);
  });
  $('[data-replacer]').addEventListener('click', () => { cancelAnimationFrame(animation); etat.x = 0; majValeurs(); });
  $('[data-vue]').addEventListener('click', () => { if (scene3d) scene3d.vueDeFace(); });

  // ---------------------------------------------------------------- Étapes
  function montrerReponse(i) {
    const section = etapes[i];
    const reponse = section.querySelector('[data-reponse]');
    if (!reponse) return;
    etat.revele.add(i);
    reponse.classList.add('revelee');
    const bouton = section.querySelector('[data-reveler]');
    if (bouton) bouton.setAttribute('aria-expanded', 'true');
    appliquerScene();
  }

  function appliquerScene() {
    const section = etapes[etat.etape];
    const montrer = new Set((section.dataset.montrer || '').split(/\s+/).filter(Boolean));
    if (etat.revele.has(etat.etape)) {
      (section.dataset.reponseMontrer || '').split(/\s+/).filter(Boolean).forEach((m) => montrer.add(m));
    }
    etat.montrer = montrer;
    const mode = section.dataset.mode || 'physique';
    if (mode !== etat.mode) {
      etat.mode = mode;
      cadrerPlusTard = true;
      etat.x = 0;
      // En physique, la corde tire vers l'avant (θ ≤ 80°) ; en généralisation, tous les angles.
      curseurs.theta.max = mode === 'abstrait' ? '180' : '80';
      if (mode === 'physique' && etat.theta > 80) { etat.theta = 60; curseurs.theta.value = '60'; }
    }
    $('[data-reglages]').hidden = !('reglagesVisibles' in section.dataset);
    $('[data-preselections]').hidden = !('preselectionsVisibles' in section.dataset);
    const lancer = 'lancerVisible' in section.dataset && Boolean(scene3d) && mode === 'physique';
    $('[data-lancer]').hidden = !lancer;
    $('[data-replacer]').hidden = !lancer;
    majValeurs();
    if (cadrerPlusTard && scene3d) { cadrerPlusTard = false; scene3d.vueDeFace(); }
  }

  function afficherEtape(i) {
    etat.etape = Math.max(0, Math.min(etapes.length - 1, i));
    etapes.forEach((s, k) => {
      s.classList.toggle('active', k === etat.etape);
      s.setAttribute('aria-hidden', String(k !== etat.etape));
      s.querySelectorAll('button').forEach((b) => { b.tabIndex = k === etat.etape ? 0 : -1; });
    });
    Array.from(points.children).forEach((li, k) => {
      li.classList.toggle('ici', k === etat.etape);
      li.classList.toggle('fait', k < etat.etape);
    });
    $('[data-compteur]').textContent =
      `Étape ${etat.etape + 1} / ${etapes.length} — ${etapes[etat.etape].dataset.titre}`;
    $('[data-precedente]').disabled = etat.etape === 0;
    $('[data-suivante]').disabled = etat.etape === etapes.length - 1;
    appliquerScene();
  }

  etapes.forEach((section, i) => {
    const bouton = section.querySelector('[data-reveler]');
    if (bouton) {
      bouton.setAttribute('aria-expanded', 'false');
      bouton.addEventListener('click', () => montrerReponse(i));
    }
  });
  $('[data-precedente]').addEventListener('click', () => afficherEtape(etat.etape - 1));
  $('[data-suivante]').addEventListener('click', () => afficherEtape(etat.etape + 1));
  $('[data-commencer]').addEventListener('click', () => {
    if (document.documentElement.classList.contains('pagine')) {
      document.dispatchEvent(new CustomEvent('cours:suivante'));
    } else {
      document.getElementById('s1')?.scrollIntoView({ behavior: reduit ? 'auto' : 'smooth' });
    }
  });

  // Télécommande / flèches : la réponse d'une étape, puis l'étape suivante ; false = fin.
  racine.etapesInternes = {
    avancer() {
      const reponse = etapes[etat.etape].querySelector('[data-reponse]');
      if (reponse && !etat.revele.has(etat.etape)) { montrerReponse(etat.etape); return true; }
      if (etat.etape < etapes.length - 1) { afficherEtape(etat.etape + 1); return true; }
      return false;
    },
    reculer() {
      if (etat.etape > 0) { afficherEtape(etat.etape - 1); return true; }
      return false;
    },
    get etape() { return etat.etape; },
    get valeurs() { return { F: etat.F, theta: etat.theta, d: etat.d, W: travail(etat.F, etat.d, etat.theta) }; },
  };
  racine.dataset.pret = '1';
  afficherEtape(0);
}

// ------------------------------------------------------------------ Scène 3D
function creerScene(conteneur, racine, etat) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  conteneur.insertBefore(renderer.domElement, conteneur.firstChild);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 16 / 11, 0.1, 100);
  const controles = new OrbitControls(camera, renderer.domElement);
  controles.enableDamping = true;
  controles.enablePan = false;
  controles.minDistance = 3;
  controles.maxDistance = 40;
  controles.maxPolarAngle = Math.PI / 2 - 0.04;
  // Vue de face cadrée sur toute la scène (trajet A → B et personne, ou vecteurs autour de O).
  function vueDeFace() {
    const w = conteneur.clientWidth || 16;
    const h = conteneur.clientHeight || 11;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    const physique = etat.mode === 'physique';
    const xmin = physique ? -0.9 : -2.6;
    const xmax = physique ? etat.d + 2.5 : 4.2;
    const cx = (xmin + xmax) / 2;
    const fovV = camera.fov * RAD;
    const fovH = 2 * Math.atan(Math.tan(fovV / 2) * camera.aspect);
    const dist = 1.02 * Math.max((xmax - xmin) / 2 / Math.tan(fovH / 2), 1.9 / Math.tan(fovV / 2));
    controles.target.set(cx, physique ? 0.85 : 0.6, 0);
    camera.position.set(cx - 0.5, (physique ? 0.85 : 0.6) + dist * 0.3, dist);
    controles.update();
  }
  vueDeFace();

  scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6));
  const soleil = new THREE.DirectionalLight(0xffffff, 1.4);
  soleil.position.set(-3, 8, 6);
  scene.add(soleil);

  // Couleurs : variables CSS (thème clair / sombre)
  const couleur = (nom, defaut) => new THREE.Color(getComputedStyle(racine).getPropertyValue(nom).trim() || defaut);
  const mat = (c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.75 });
  const plein = (c) => new THREE.MeshBasicMaterial({ color: c });
  // Vecteurs toujours visibles, même derrière la caisse ou sous le sol (poids).
  const devant = (c) => new THREE.MeshBasicMaterial({ color: c, depthTest: false, transparent: true });

  // Sol et repères A, B
  const sol = new THREE.Mesh(new THREE.PlaneGeometry(22, 8), mat(0xcfd8de));
  sol.rotation.x = -Math.PI / 2;
  sol.position.set(3, 0, 0);
  scene.add(sol);
  const bord = new THREE.Mesh(new THREE.BoxGeometry(22, 0.04, 0.04), plein(0x445566));
  bord.position.set(3, 0.01, 0.9);
  scene.add(bord);
  const repere = (c) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 0.02, 24), plein(c));
    scene.add(m);
    return m;
  };
  const pointA = repere(0x1f2937);
  const pointB = repere(0x1f2937);

  // Mobile : caisse + corde + personne
  const mobile = new THREE.Group();
  scene.add(mobile);
  const toile = document.createElement('canvas');
  toile.width = toile.height = 128;
  const g = toile.getContext('2d');
  g.fillStyle = '#E8A55B'; g.fillRect(0, 0, 128, 128);
  g.strokeStyle = '#8A4B12'; g.lineWidth = 10; g.strokeRect(5, 5, 118, 118);
  g.lineWidth = 7; g.beginPath(); g.moveTo(8, 8); g.lineTo(120, 120); g.moveTo(120, 8); g.lineTo(8, 120); g.stroke();
  const texture = new THREE.CanvasTexture(toile);
  texture.colorSpace = THREE.SRGBColorSpace;
  const caisse = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.8, 0.8), new THREE.MeshStandardMaterial({ map: texture, roughness: 0.9 }));
  caisse.position.set(0, 0.4, 0);
  mobile.add(caisse);
  const ombre = new THREE.Mesh(new THREE.CircleGeometry(0.75, 32),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.12 }));
  ombre.rotation.x = -Math.PI / 2;
  ombre.position.set(0, 0.005, 0);
  mobile.add(ombre);

  const corde = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 1, 10), mat(0x8a6a3a));
  mobile.add(corde);
  const personne = new THREE.Group();
  mobile.add(personne);
  const peau = mat(0xf2c9a0);
  const habit = mat(0x2b6cb0);
  const pantalon = mat(0x1d3f7a);
  const segment = (materiau, r) => {
    const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 1, 12), materiau);
    personne.add(m);
    return m;
  };
  const tete = new THREE.Mesh(new THREE.SphereGeometry(0.17, 24, 16), peau);
  personne.add(tete);
  const tronc = segment(habit, 0.14);
  const jambe1 = segment(pantalon, 0.075);
  const jambe2 = segment(pantalon, 0.075);
  const bras1 = segment(habit, 0.055);
  const bras2 = segment(habit, 0.055);

  const haut = new THREE.Vector3(0, 1, 0);
  function poser(m, a, b) {
    const v = new THREE.Vector3().subVectors(b, a);
    m.position.copy(a).addScaledVector(v, 0.5);
    m.scale.set(1, v.length(), 1);
    m.quaternion.setFromUnitVectors(haut, v.clone().normalize());
  }

  // Flèches (corps + pointe), traits pointillés, arc d'angle
  function fleche(c) {
    const groupe = new THREE.Group();
    const corps = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 1, 12), devant(c));
    const pointe = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.26, 16), devant(c));
    corps.renderOrder = pointe.renderOrder = 10;
    groupe.add(corps, pointe);
    scene.add(groupe);
    return {
      groupe, couleurs: [corps.material, pointe.material],
      poser(depart, vecteur) {
        const n = vecteur.length();
        groupe.visible = n > 1e-3;
        if (!groupe.visible) return;
        const dir = vecteur.clone().normalize();
        const tige = Math.max(0.001, n - 0.24);
        poser(corps, depart, depart.clone().addScaledVector(dir, tige));
        pointe.position.copy(depart).addScaledVector(dir, n - 0.13);
        pointe.quaternion.setFromUnitVectors(haut, dir);
      },
    };
  }
  function pointilles(c) {
    const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(1, 0, 0)]);
    const ligne = new THREE.Line(geo, new THREE.LineDashedMaterial({ color: c, dashSize: 0.12, gapSize: 0.08, depthTest: false, transparent: true }));
    ligne.renderOrder = 9;
    scene.add(ligne);
    return {
      ligne,
      poser(a, b) {
        geo.setFromPoints([a, b]);
        ligne.computeLineDistances();
      },
    };
  }
  const arcGeo = new THREE.BufferGeometry();
  const arc = new THREE.Line(arcGeo, new THREE.LineBasicMaterial({ color: 0x1f2937, depthTest: false, transparent: true }));
  arc.renderOrder = 9;
  scene.add(arc);

  const fF = fleche(0xc0392b);
  const fd = fleche(0x2e8b57);
  const fFx = fleche(0xe08a1e);
  const fFy = fleche(0xe08a1e);
  const fP = fleche(0x1d4e89);
  const fR = fleche(0x1d4e89);
  const fProj = fleche(0xe08a1e);
  const tFx = pointilles(0xe08a1e);
  const tFy = pointilles(0xe08a1e);
  const tProj = pointilles(0x888888);
  const origine = new THREE.Mesh(new THREE.SphereGeometry(0.07, 16, 12), plein(0x1f2937));
  scene.add(origine);

  function recolorer() {
    const F = couleur('--sp-F', '#c0392b');
    const d = couleur('--sp-d', '#2e8b57');
    const proj = couleur('--sp-proj', '#e08a1e');
    const texte = couleur('--texte', '#1f2937');
    const meth = couleur('--meth', '#1d4e89');
    fF.couleurs.forEach((m) => m.color.copy(F));
    fd.couleurs.forEach((m) => m.color.copy(d));
    [fFx, fFy, fProj].forEach((f) => f.couleurs.forEach((m) => m.color.copy(proj)));
    [fP, fR].forEach((f) => f.couleurs.forEach((m) => m.color.copy(meth)));
    tFx.ligne.material.color.copy(proj);
    tFy.ligne.material.color.copy(proj);
    tProj.ligne.material.color.copy(texte);
    arc.material.color.copy(texte);
    pointA.material.color.copy(texte);
    pointB.material.color.copy(texte);
    origine.material.color.copy(texte);
    sol.material.color.copy(couleur('--sp-sol', '#8fa1ae')).lerp(new THREE.Color(0xffffff), 0.45);
  }
  recolorer();
  new MutationObserver(recolorer).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', recolorer);

  // Étiquettes HTML (formules MathJax) placées sur les points 3D
  const etiquettes = {};
  racine.querySelectorAll('[data-etiquette]').forEach((el) => { etiquettes[el.dataset.etiquette] = { el, pos: null }; });
  const tmp = new THREE.Vector3();
  function placerEtiquettes() {
    const w = conteneur.clientWidth;
    const h = conteneur.clientHeight;
    Object.entries(etiquettes).forEach(([cle, e]) => {
      const visible = e.pos && etat.montrer.has(cle);
      e.el.classList.toggle('visible', Boolean(visible));
      if (!visible) return;
      tmp.copy(e.pos).project(camera);
      e.el.style.transform = `translate(${((tmp.x + 1) / 2 * w).toFixed(1)}px, ${((1 - tmp.y) / 2 * h).toFixed(1)}px) translate(-50%, -50%)`;
    });
  }

  const v3 = (x, y, z = 0) => new THREE.Vector3(x, y, z);
  const ECHELLE = 1.7 / 40;          // 40 N → 1,7 m de flèche

  function maj() {
    const { F, theta, d, x, mode, montrer } = etat;
    const physique = mode === 'physique';
    const c = cosinus(theta);
    const s = Math.sin(theta * RAD);
    pointA.position.set(0, 0.01, 0);
    pointB.position.set(d, 0.01, 0);
    pointA.visible = physique;
    pointB.visible = physique;

    // Mobile (physique) : caisse au point x ; corde de longueur adaptée ; personne qui tire.
    mobile.visible = physique;
    mobile.position.set(x, 0, 0);
    const attache = v3(0.55, 0.42);
    const L = Math.max(1.25, Math.min(3.2, 0.85 / Math.max(s, 0.01)));
    const mains = attache.clone().add(v3(L * c, L * s));
    poser(corde, attache, mains);
    const hanches = v3(mains.x + 0.62, 0.92);
    const epaules = hanches.clone().add(v3(0.22, 0.56));
    poser(tronc, hanches, epaules);
    poser(jambe1, hanches, v3(hanches.x - 0.32, 0.02, 0.12));
    poser(jambe2, hanches, v3(hanches.x + 0.4, 0.02, -0.12));
    poser(bras1, epaules.clone().setZ(0.16), mains.clone().setZ(0.04));
    poser(bras2, epaules.clone().setZ(-0.16), mains.clone().setZ(-0.04));
    tete.position.copy(epaules).add(v3(0.1, 0.27));

    // Origine des vecteurs : point d'attache de la corde (physique) ou O = A (abstrait).
    const O = physique ? v3(x + 0.55, 0.42, 0.42) : v3(0, 0.02, 0.0);
    const kF = F * ECHELLE * (physique ? 1 : 1.25);
    const vF = v3(kF * c, kF * s);
    fF.poser(O, vF);
    fF.groupe.visible = montrer.has('F');

    const kd = physique ? d : Math.min(d, 6) * 0.7;
    const departD = physique ? v3(0, 0.03, 1.15) : O;
    fd.poser(departD, v3(kd, 0, 0));
    fd.groupe.visible = montrer.has('d');

    fFx.poser(O, v3(vF.x, 0));
    fFy.poser(O, v3(0, vF.y));
    fFx.groupe.visible = montrer.has('Fx') && Math.abs(vF.x) > 0.05;
    fFy.groupe.visible = montrer.has('Fy') && Math.abs(vF.y) > 0.05;
    tFx.poser(O.clone().add(v3(vF.x, 0)), O.clone().add(vF));
    tFy.poser(O.clone().add(v3(0, vF.y)), O.clone().add(vF));
    tFx.ligne.visible = fFx.groupe.visible && fFy.groupe.visible;
    tFy.ligne.visible = tFx.ligne.visible;

    // Généralisation : projection de F sur la droite (AB)
    fProj.poser(O, v3(vF.x, 0));
    fProj.groupe.visible = !physique && montrer.has('proj') && Math.abs(vF.x) > 0.05;
    tProj.poser(O.clone().add(vF), O.clone().add(v3(vF.x, 0)));
    tProj.ligne.visible = !physique && montrer.has('proj') && Math.abs(vF.y) > 0.05;
    origine.visible = !physique;
    origine.position.copy(O);

    const centre = v3(x, 0.4, 0.42);
    fP.poser(centre, v3(0, -1.05));
    fP.groupe.visible = physique && montrer.has('P');
    fR.poser(v3(x - 0.2, 0.0, 0.42), v3(0, 1.05));
    fR.groupe.visible = physique && montrer.has('R');

    // Arc de l'angle θ
    const r = 0.55;
    const pts = [];
    const n = Math.max(2, Math.round(theta / 3));
    for (let k = 0; k <= n; k++) {
      const a = theta * RAD * k / n;
      pts.push(O.clone().add(v3(r * Math.cos(a), r * Math.sin(a))));
    }
    arcGeo.setFromPoints(pts);
    arc.visible = montrer.has('theta') && theta > 0;

    // Positions des étiquettes
    etiquettes.F.pos = O.clone().add(vF.clone().multiplyScalar(1.08)).add(v3(0.12 * -s, 0.22 * c + 0.12));
    etiquettes.d.pos = departD.clone().add(v3(kd / 2, 0.32));
    etiquettes.theta.pos = O.clone().add(v3(0.85 * Math.cos(theta * RAD / 2), 0.85 * Math.sin(theta * RAD / 2) + 0.02));
    etiquettes.A.pos = physique ? v3(0, -0.05, 1.5) : v3(-0.25, -0.15, 0.2);
    etiquettes.B.pos = physique ? v3(d, -0.05, 1.5) : null;
    etiquettes.P.pos = centre.clone().add(v3(0.32, -0.95));
    etiquettes.R.pos = v3(x - 0.5, 1.0, 0.42);
    etiquettes.Fx.pos = O.clone().add(v3(vF.x / 2, -0.25));
    etiquettes.Fy.pos = O.clone().add(v3(-0.35, vF.y / 2));
    if (!physique) {
      etiquettes.A.pos = null;
      etiquettes.B.pos = null;
    }
    demander();
  }

  // Rendu : seulement quand la scène est visible (page courante, onglet actif).
  function visible() {
    if (document.hidden || !conteneur.offsetParent) return false;
    const feuille = conteneur.closest('.feuille');
    return !feuille || feuille.classList.contains('visible');
  }
  let enCours = false;
  let derniereTaille = '';
  function dessiner() {
    enCours = false;
    if (!visible()) return;
    const w = conteneur.clientWidth;
    const h = conteneur.clientHeight;
    const taille = `${w}x${h}`;
    if (taille !== derniereTaille && w && h) {
      derniereTaille = taille;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      if (!manuel) vueDeFace();          // nouvelle taille : on recadre, sauf si l'élève a tourné la vue
    }
    const bouge = controles.update();
    renderer.render(scene, camera);
    placerEtiquettes();
    if (bouge) demander();
  }
  function demander() {
    if (enCours) return;
    enCours = true;
    requestAnimationFrame(dessiner);
  }
  let manuel = false;
  controles.addEventListener('start', () => { manuel = true; });
  controles.addEventListener('change', demander);
  new ResizeObserver(demander).observe(conteneur);
  document.addEventListener('visibilitychange', demander);
  // La page du cours devient visible (pagination, présentation) : redessiner.
  new MutationObserver(demander).observe(document.documentElement, { attributes: true, subtree: true, attributeFilter: ['class'] });

  return { maj, vueDeFace: () => { manuel = false; vueDeFace(); demander(); } };
}

// Démarrage (après les déclarations ci-dessus).
const racinePage = document.querySelector('[data-situation]');
if (racinePage) demarrer(racinePage);
