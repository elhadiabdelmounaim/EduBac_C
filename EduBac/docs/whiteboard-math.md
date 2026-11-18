# Tableau blanc : outils mathématiques

Trois nouveaux boutons dans la barre d'outils du tableau :

| Bouton | Objet | Contenu |
| --- | --- | --- |
| **Repère** | repère interactif | fonctions, curseurs, géométrie dynamique, analyse, exercices |
| **Tableau** | tableau de variations ou de signes | texte simple, aperçu immédiat |
| **Arbre** | arbre de probabilités | texte indenté, produits calculés |

## Repère interactif

Chaque élément est une commande (séparateur `;`). Les modèles du menu « Modèle » donnent un point de départ.

- Fonctions : `f(x)=x^2-2x`, `g(x)=si(x<0; -x; x^2)`, `h(x)=ln(x) [1;5]`, `y=2x+1`
- Curseurs : `a=Curseur(min;max;pas;valeur)`, puis `f(x)=a x^2`
- Points : `A=(1;2)` (mobile), `M=Point(f;1)` (sur une courbe, un cercle ou une droite)
- Analyse : `Dérivée(f)`, `Tangente(f;M)`, `Racines(f)`, `Extremums(f)`, `Asymptotes(f)`, `Intersection(f;g)`, `Intégrale(f;a;b)`, `Aire(f;g;a;b)`
- Géométrie : `Droite`, `Segment`, `DemiDroite`, `Vecteur`, `Cercle(O;2)`, `Polygone(A;B;C)`, `Milieu`, `Perpendiculaire(d;A)`, `Parallèle(d;A)`, `Médiatrice(A;B)`, `Bissectrice(A;B;C)`
- Mesures : `Distance(A;B)`, `Angle(A;B;C)`, `Aire(p)` ; une mesure nommée se réutilise : `k=2*S1`
- Transformations : `Translation(p;u)`, `Symétrie(p;O)` / `Symétrie(p;d)`, `Homothétie(p;O;k)`, `Rotation(p;O;90)`
- `Barycentre(A;2;B;3)`, `Lieu(I;M)`, `Trace(M)`
- `CercleTrigo(t)`, `Suite(f;u0;n)` (escalier / escargot), `z=Complexe(2;1)` (module, argument)
- Exercice : `Placer(A;2;3)` — chaque élève touche le repère pour placer A ; il voit tout de suite ✓ ou ✗,
  le professeur voit toutes les réponses avec le nom de l'élève et le nombre de réponses justes.

Sur le tableau : glisser un point ou un curseur, déplacer la vue à la main, molette pour zoomer,
boutons − + ⟲ dans l'en-tête, coin bas-droit pour redimensionner, double-clic pour modifier.
Un élève sans droit de modification peut explorer (curseurs, zoom) sur son écran sans changer le tableau des autres.

## Sécurité

Les expressions sont analysées par `static/js/whiteboard-math.js` : aucun code n'est exécuté (plus de `new Function`).
Le serveur limite un repère à 60 commandes de 600 caractères (`whiteboard/collab.py`).

## Tests

- Moteur : `node --test whiteboard/js_tests/` (lancé aussi par `python manage.py test whiteboard` si Node.js est installé).
- Navigateur : `browser_tests/test_whiteboard_math.py`.
