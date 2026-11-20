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
| IA | service FastAPI indépendant (`ai_service/`) | **désactivé** (`MATHBOARD_AI_ENABLED=0` par défaut : ni bouton ni API) ; code conservé |

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

## 5. Fonctions de classe (`mathboard/api_class.py`, `static/mathboard/mb-class.js`)

* **Préparer sans partager** : à la création, choisir une classe puis
  « Préparer sans partager » (choix par défaut). Le document est rattaché à la
  classe (`class_visible` faux) mais les élèves ne le voient pas, n'y accèdent
  pas et ne reçoivent rien. Le professeur le prépare ; la liste l'indique
  « Préparé · non partagé ». Le bandeau « Partager maintenant » de l'éditeur
  (ou la case « Visible par les élèves » dans « Partager ») le rend visible et
  prévient la classe une seule fois. Sans le champ, l'API partage tout de suite
  comme avant.
* **Travail à rendre** : dans « Partager », cocher « Travail à rendre » (date
  limite facultative). Chaque élève clique sur « Faire ce travail » et obtient
  sa **copie** (même contenu que le sujet). Droits : l'élève gère sa copie tant
  qu'elle est « en cours », puis la lit seulement une fois rendue ; le
  professeur du sujet ne la voit qu'une fois rendue, l'annote directement,
  met une note et une appréciation, puis « Rendre la correction » ou
  « Demander une reprise » (la copie redevient modifiable). Une version est
  créée à chaque étape. Liste « Travaux à corriger » et « Mes travaux » sur la
  page d'accueil du tableau ; « Copies des élèves » montre l'état de chaque élève.
* **Notifications** (dans EduBac et sur le téléphone, jamais par e-mail) :
  partage avec une classe, travail à rendre, invitation, copie rendue, copie
  corrigée ou à reprendre.
* **Présenter (« suivez-moi »)** : les participants voient la page et la zone du
  professeur, adaptées à leur écran ; chacun peut « Ne plus suivre ». Sans
  signal du présentateur pendant 90 s (onglet fermé), la présentation s'arrête.
  Sur PythonAnywhere, la vue suit toutes les 2 s environ.
* **Participation** : éléments par auteur, « Montrer » (sélection et zoom),
  « Supprimer » tous ses éléments (version créée avant).
* **Téléphone et stylet** : deux doigts zooment ; avec un stylet, l'épaisseur
  suit la pression et, dès qu'un stylet a servi, le doigt ou la paume déplacent
  la vue au lieu d'écrire.
* **Texte arabe** : écrit automatiquement de droite à gauche.
* **Images** : envoyées comme fichiers (`media/mathboard/<document>/`, nom
  aléatoire, métadonnées supprimées, 1600 px au plus) ; seule l'adresse est
  dans la base. Hors ligne, l'image voyage dans l'opération (2 Mo au plus) puis
  `mathboard_cleanup` la déplace en fichier. Les fichiers de `/media/` sont
  publics pour qui connaît leur adresse (aléatoire), comme les autres médias.
* **Hors connexion** : la page d'un tableau déjà ouvert et la dernière copie de
  son contenu sont gardées sur l'appareil ; le tableau s'ouvre sans réseau et
  les modifications partent au retour du réseau. Cette copie est effacée à la
  déconnexion (page) et quand un autre compte ouvre un tableau (contenu).
* **Anciens tableaux** : bouton « Convertir vers le tableau mathématique » dans
  la liste de l'ancien tableau (ou `python manage.py mathboard_convert_legacy --all`).
  L'ancien tableau reste intact. Non repris : coups de gomme, réponses aux
  repères ; les curseurs d'un repère deviennent des commentaires (`#`).
* **Alertes d'erreurs** (tout le site) : une erreur serveur (500) ou une erreur
  JavaScript chez un utilisateur crée une notification pour les administrateurs
  (une fois par heure par erreur, avec le nombre d'occurrences).

## 5 bis. Écriture manuscrite, sans IA générative (`static/mathboard/mb-ink.js`, `mathboard/recognition.py`)

Deux systèmes indépendants : la reconnaissance de l'écriture (ci-dessous) ne
dépend d'aucune IA générative ; l'assistant pédagogique IA reste à part et
désactivé (`MATHBOARD_AI_ENABLED`). Tout ce qui suit fonctionne sans lui.

* **Tracés bruts** : chaque trait (souris, doigt, stylet) enregistre sa ligne
  centrale `ink = {x, y, t, width}` (repère du chemin : elle suit déplacements et
  agrandissements). Base de la reconnaissance, des formes et de la gomme partielle.
  Les traits plus anciens sont lus depuis leur chemin.
* **Lasso** (outil `Q`) : entourer à main levée ; seuls les éléments dont au
  moins 60 % du tracé (ou le centre et 3 coins) sont dans la boucle sont
  sélectionnés. Barre de sélection : En texte, En formule, Forme, Écriture
  originale, Réduire / Agrandir, copier, supprimer… ; la palette change la couleur.
* **Formes** (bouton « Forme », ou « Formes automatiques » dans les options du
  crayon) : analyse géométrique locale — segment (redressé à l'horizontale /
  verticale à 6° près), cercle, ellipse, triangle, rectangle, carré, polygone
  (5 à 8 côtés), flèche (un trait, ou un segment + une pointe en « V »), angle.
  Écriture comparée à l'ellipse et au polygone ajustés ; un tracé de moins de
  40 px n'est jamais transformé automatiquement (lettres, chiffres). Le tracé
  d'origine est gardé dans `ink_source` : « Écriture originale » le rétablit.
* **Gomme** (options de la gomme) : objet entier (par défaut, comme avant),
  partie d'un trait (le trait est coupé sous la gomme), formules seulement,
  textes seulement. Une passe de gomme = une action annulable.
* **Conversion en texte / en formule** : les tracés bruts sélectionnés (x, y, t,
  sans image) partent au serveur, qui interroge **MyScript** (API REST « batch »,
  requête signée HMAC-SHA512 ; les clés restent sur le serveur). Fenêtre de
  relecture : texte modifiable (langue français / arabe, taille, police) ou
  formule dans MathLive ; Accepter / Refuser / Relancer. L'écriture d'origine
  est conservée par défaut ; « Remplacer » la range dans `ink_source`.
  Désactivé sans configuration (boutons masqués). Pas de conversion automatique
  pendant l'écriture : chaque pause coûterait une requête au quota MyScript.

## 6. Utilisation

**Enseignant** : créer un document (niveau, chapitre, classe) ; écrire,
dessiner, insérer formules et figures ; calcul exact (menu « Formule ») ;
asymptotes et tableau de variations d’une fonction (menu « Figure ») ;
« Partager » : classe, écriture des élèves, travail à rendre, membres invités ;
« Présenter » ; « Participation » ; « Versions » ;
« Exporter » : PNG, SVG, PDF, fichier EduBac (réimportable).

**Élève** : brouillons personnels (et invitation de camarades), exercices
partagés par le professeur, travaux à rendre (copie, rendu, correction),
calculs exacts, graphiques.

Raccourcis : V sélection, H vue, P crayon, E gomme, T texte, R rectangle,
O ellipse, L ligne, A flèche, Ctrl+Z / Ctrl+Y, Ctrl+C / X / V, Ctrl+D,
Ctrl+A, Suppr, Espace + glisser (vue), molette (zoom).
Sur téléphone et tablette : un doigt dessine (ou déplace la vue avec l’outil main),
deux doigts écartés ou rapprochés zooment et déplacent la vue.

Langage des figures : `A = (x, y)`, `Segment(A, B)`, `Droite(A, B)`,
`DemiDroite(A, B)`, `Cercle(A, B)` ou `Cercle(A, r)`, `Triangle(A, B, C)`,
`Polygone(…)`, `Angle(B, A, C)`, `Vecteur(A, B)`, `Milieu(A, B)`,
`Perpendiculaire(C, d)`, `Parallele(C, d)`, `Intersection(a, b[, n])`,
`f(x) = …`, `Tangente(f, a)`, `Verticale(a)`, `Texte((x, y), "…")` ;
options en fin de ligne : `[rouge pointillé épais]`.

## 7. Tests

```bash
python manage.py test mathboard edubac_math ai_service      # serveur + SymPy + service IA
python manage.py test browser_tests.test_mathboard browser_tests.test_mathboard_class --settings=browser_tests.settings
# Production (ASGI + WebSocket + Redis + PostgreSQL), voir docs/mathboard-deploiement.md :
BROWSER_TEST_POSTGRES=1 REDIS_URL=redis://… DATABASE_URL=postgresql://… \
  python manage.py test browser_tests.test_mathboard_realtime --settings=browser_tests.settings
```
