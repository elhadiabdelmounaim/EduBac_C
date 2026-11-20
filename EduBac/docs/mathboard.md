# Tableau mathématique collaboratif (`mathboard`)

Adresse : `/tableau-maths/`. Application Django indépendante de l’ancien tableau
(`whiteboard`), qui reste disponible. Comptes, rôles et classes : modèles EduBac
existants.

## 1. Architecture

| Couche | Technologie | Rôle |
|---|---|---|
| Canevas | Fabric.js 6 | dessin libre, formes, texte, images, sélection multiple, calques, zoom, déplacement de la vue |
| Saisie mathématique | MathLive | formules (fractions, racines, puissances, limites, dérivées, intégrales, matrices, systèmes, vecteurs, ensembles, trigonométrie) |
| Rendu mathématique | MathJax 3 (SVG) | rendu des formules et des tableaux de variations |
| Géométrie et courbes | JSXGraph | points, droites, segments, cercles, triangles, angles, vecteurs, constructions, fonctions, tangentes, intersections |
| Calcul exact | SymPy (module `edubac_math`) | simplifier, développer, factoriser, dériver, intégrer, limites, résoudre (équations, inéquations, systèmes), matrices, asymptotes, tableaux de variations |
| API | Django REST Framework | documents, état, opérations, membres, versions, calcul, présence, export/import, IA |
| Temps réel | Django Channels + Redis | diffusion des opérations, présence, curseurs |
| Stockage | PostgreSQL (SQLite accepté) | source de vérité : opérations, état des pages, versions |
| IA | service FastAPI indépendant (`ai_service/`) | analyser, résoudre, expliquer, vérifier, indice, exercices |

Bibliothèques JavaScript servies par le site (`static/vendor/`) : aucune dépendance à un CDN.

### Couche d’intégration Fabric.js ↔ JSXGraph ↔ MathJax (`static/mathboard/mb-render.js`)

Chaque fonction n’existe qu’à un seul endroit :

* un objet **« math »** est stocké sous forme LaTeX ; MathJax en produit un SVG
  que Fabric affiche comme image ;
* un objet **« geometry »** est stocké sous forme de *script de construction*
  (ex. `A = (1, 2)`, `c = Cercle(A, B)`, `f(x) = x^2`) ; JSXGraph construit la figure
  (hors écran pour le rendu, de façon interactive dans l’éditeur) et Fabric
  n’en reçoit que le SVG ;
* les asymptotes et les tableaux de variations sont calculés **exactement** par
  SymPy côté serveur, puis dessinés par JSXGraph (droites) ou MathJax (tableau).

Un double-clic rouvre l’éditeur d’origine (MathLive ou JSXGraph) : l’objet reste
modifiable, et identique chez tous les participants, car seule la source circule.

## 2. Modèles

`WhiteboardDocument`, `WhiteboardPage`, `WhiteboardMember`, `WhiteboardOperation`,
`WhiteboardSnapshot`, `WhiteboardSession` (voir `mathboard/models.py`).

Droits (`mathboard/access.py`) : **gestion** (propriétaire, administrateur,
enseignant de la classe, membre « gestion »), **modification** (membre
« modification », élève de la classe si « les élèves peuvent écrire »),
**lecture** (membre « lecture », élève de la classe partagée). Un utilisateur
« modification » ne modifie que ses propres éléments.

## 3. Opérations, révisions et conflits (`mathboard/operations.py`)

* Chaque modification est une opération avec un identifiant unique (`op_id`)
  choisi par le client ; le serveur lui attribue la **révision** suivante du
  document, dans une transaction (verrou de ligne sur PostgreSQL).
* Une opération renvoyée après une coupure n’est jamais appliquée deux fois.
* Conflits : modifier un objet supprimé ou créer un identifiant existant est
  refusé explicitement ; deux modifications d’un même objet sont fusionnées
  propriété par propriété (la dernière arrivée l’emporte) et signalées
  (`stale`).
* Rattrapage : `GET …/operations/?since=<révision>` ; si l’écart est trop grand
  ou si une version a été restaurée, le client recharge l’état complet.

### Étude Yjs / CRDT

Yjs (ou y-py côté Python) apporte une fusion sans serveur central, utile pour
l’édition simultanée de **texte long** caractère par caractère. Pour un tableau
fait d’objets indépendants, le journal d’opérations ordonné par le serveur
donne déjà : convergence (même ordre partout), droits vérifiés à chaque
opération, historique et versions exploitables, et aucun état à fusionner hors
de PostgreSQL. Yjs imposerait un second format de données (documents binaires),
rendrait le contrôle des droits par objet beaucoup plus difficile et ajouterait
un serveur de synchronisation. **Décision : journal d’opérations conservé.** Si
l’édition à plusieurs d’un même long texte devient nécessaire, un objet
« texte collaboratif » pourra embarquer un document Yjs sans changer le reste.

## 4. Enregistrement automatique et coupures réseau (`static/mathboard/mb-sync.js`)

* Envoi groupé après 250 ms ; file d’attente conservée dans `localStorage`
  (rechargement, fermeture d’onglet, perte du réseau : rien n’est perdu).
* Nouvel essai progressif (1 s → 15 s) ; session expirée : les modifications
  sont gardées et renvoyées après reconnexion.
* Statut affiché : « Enregistré · en direct / synchronisé », « Enregistrement… »,
  « Hors ligne — n modifications en attente », erreurs.
* Versions : automatiques toutes les 300 opérations et toutes les 10 minutes
  d’activité (50 conservées), manuelles, et avant chaque restauration.

## 5. Utilisation

**Enseignant** : créer un document (niveau, chapitre, classe) ; écrire,
dessiner, insérer formules et figures ; calcul exact (menu « Formule ») ;
asymptotes et tableau de variations d’une fonction (menu « Figure ») ;
« Partager » : classe, écriture des élèves, membres invités ; « Versions » ;
« Exporter » : PNG, SVG, PDF, fichier EduBac (réimportable).

**Élève** : brouillons personnels (et invitation de camarades), exercices
partagés par le professeur, calculs, graphiques, assistant IA (indice,
explication, vérification de sa réponse — vérifiée par SymPy quand c’est
possible).

Raccourcis : V sélection, H vue, P crayon, E gomme, T texte, R rectangle,
O ellipse, L ligne, A flèche, Ctrl+Z / Ctrl+Y, Ctrl+C / X / V, Ctrl+D,
Ctrl+A, Suppr, Espace + glisser (vue), molette (zoom).

Langage des figures : `A = (x, y)`, `Segment(A, B)`, `Droite(A, B)`,
`DemiDroite(A, B)`, `Cercle(A, B)` ou `Cercle(A, r)`, `Triangle(A, B, C)`,
`Polygone(…)`, `Angle(B, A, C)`, `Vecteur(A, B)`, `Milieu(A, B)`,
`Perpendiculaire(C, d)`, `Parallele(C, d)`, `Intersection(a, b[, n])`,
`f(x) = …`, `Tangente(f, a)`, `Verticale(a)`, `Texte((x, y), "…")` ;
options en fin de ligne : `[rouge pointillé épais]`.

## 6. Tests

```bash
python manage.py test mathboard edubac_math ai_service      # serveur + SymPy + service IA
python manage.py test browser_tests.test_mathboard --settings=browser_tests.settings
# Production (ASGI + WebSocket + Redis + PostgreSQL), voir docs/mathboard-deploiement.md :
BROWSER_TEST_POSTGRES=1 REDIS_URL=redis://… DATABASE_URL=postgresql://… \
  python manage.py test browser_tests.test_mathboard_realtime --settings=browser_tests.settings
```
