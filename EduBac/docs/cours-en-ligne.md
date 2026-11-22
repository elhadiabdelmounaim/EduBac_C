# Cours en ligne : cahier et livre 3D

Chaque leçon peut avoir, en plus de ses PDF, deux présentations interactives :

| Présentation | Adresse | Fichier à fournir |
|---|---|---|
| **Cahier** (pages tournées une à une, mode « Présenter » pour le vidéoprojecteur, réservé aux professeurs et aux administrateurs) | `/lecon/<id>/cours/` | `templates/education/cours/<NIVEAU>/<NN_titre>.html` |
| **Livre 3D** (Three.js : leçon à gauche, figures en relief à droite) | `/lecon/<id>/livre-3d/` | le même chemin, avec l'extension `.livre.json` |

`<NIVEAU>/<NN_titre>` est le nom du dossier de la leçon dans `media/lessons`
(exemple : `1BAC_SE/04_le-produit-scalaire-dans-le-plan`). Les boutons apparaissent
automatiquement dès que le fichier existe ; aucune migration n'est nécessaire.

## Cahier

Copier la structure du fichier existant : un bloc `hero`, puis un bloc `cours` contenant des
`<section class="chap" id="s1" data-toc="Titre court">`. Le contenu est entre `{% verbatim %}`,
le LaTeX (MathJax) s'écrit avec `\( … \)` et `\[ … \]`.

Types de blocs (`<div class="bloc …">`) : `def` (Définition), `prop` (Propriété / Proposition),
`ex` (Exemples), `app` (Application), `rem` (Remarque), `act` (Activité), `meth` (Méthode),
`att` (Attention), `ret` (À retenir). Dans les formules, écrire `&lt;` et `&gt;` au lieu de
`<` et `>`. Un tableau se met dans `<div class="tableau"><table>…</table></div>` ; un bloc ne se
coupe pas au milieu d'un tableau : le garder court (au plus 3 ou 4 lignes par bloc).

Cours disponibles : les 12 leçons de `1BAC_SE` (01 à 12). Les leçons 01–03 et 06–12 ont été
générées depuis les fichiers LaTeX de l'enseignant (figures TikZ/pgfplots/tkz-tab redessinées en SVG) ;
le PDF d'origine est dans le dossier `Cours` de chaque leçon. Un bloc trop haut se coupe entre deux
pages (listes, tableaux ligne par ligne avec en-tête répété).

Tronc commun scientifique (`TCS`) : les 15 leçons (01 à 15), générées de la même façon depuis les
fichiers `TC_*.tex` ; le PDF d'origine (`TC_*.pdf`) est dans le dossier `Cours` de chaque leçon. Les
numéros suivent l'ordre du site (pas le « Leçon N » des PDF). Le volume horaire de chaque leçon
(130 h au total) est dans `education/data/repartition_horaire.json` (entrée `TCS`) : c'est une
**proposition à valider**, aucun document officiel n'ayant été fourni pour ce niveau.

## Livre 3D

Le fichier `.livre.json` décrit une « double page » par partie du cours :

```json
{
  "lesson": {"title": "...", "subtitle": "...", "level": "...", "author": "..."},
  "spreads": [{
    "id": "s1", "number": "I", "title": "...",
    "concept": "Deux phrases.",
    "formula": ["formule LaTeX centrée", "texte mêlé de \\( formules \\)"],
    "vocabulary": [{"term": "...", "definition": "..."}],
    "predict": {"question": "...", "choices": ["...", "..."], "answer": 0},
    "flap": "Explication sous le rabat « Pourquoi ? ».",
    "scene": {"type": "produit", "description": "...", "interactions": ["u", "v", "bocal"]},
    "demo": [{"shot": "close", "target": "u", "caption": "...", "action": "u"}]
  }]
}
```

- `answer` est l'indice de la bonne réponse ; l'ordre affiché des choix est mélangé.
- `scene.type` choisit la figure construite dans `static/js/livre3d.js` (objet `SCENES`).
  Une nouvelle leçon demande en général d'y ajouter ses figures.
- Le tampon de la page s'encre quand toutes les `interactions` ont été touchées.
- `shot` : `overview`, `close`, `low`, `top` ou `side`.
- Dans une formule, éviter `\text{…}` avec des lettres accentuées (police MathJax) :
  écrire plutôt une ligne mêlée, par exemple `"\\(f(M)<0\\) : intérieur"`.

Three.js r160 est servi depuis `static/vendor/three` (licence MIT) : aucune installation.
Les progrès (prédictions, tampons) sont gardés dans le navigateur de l'élève.

## Cahier de textes

Dans un cours en ligne, l'enseignant ouvre le panneau **« 📋 Séance »** (bouton de la barre du
haut, de la barre des pages en présentation, ou touche **S**). Il y choisit la date et la classe,
coche les parties, sous-titres et blocs traités, puis clique sur **Enregistrer**. Enregistrer de
nouveau la même date met la séance à jour. Les séances se consultent dans
**Cahier de textes** (menu des enseignants, `/cahier-de-textes/`).

Les éléments cochables sont lus dans le gabarit du cours : `section.chap` (parties), `h3`
(sous-titres) et `div.bloc` (avec leur `.tag` : Définition, Proposition, Exemples…). Leur clé
dépend de leur position (`s1-b3` = 3e bloc de la partie s1) : réorganiser un cours déjà utilisé
ne change pas les séances enregistrées (les titres y sont copiés), mais peut décaler les ✓.

## Répartition horaire et minuteur

Les heures de chaque leçon viennent de la répartition annuelle
(`docs/references/Repartition_horaire_1ere_Bac_Sciences_2026-2027.pdf`), recopiée dans
`education/data/repartition_horaire.json` (niveau → numéro de leçon → heures, semaines…).
Pour une nouvelle année ou un autre niveau, mettre ce fichier à jour.

Ces heures sont réparties entre les blocs du cours (pas de 5 min), au prorata de leur volume
et de leur nature : Applications ×2, Exemples et Activités ×1,5, Définition / Proposition /
Méthode ×1, Remarque et Attention ×0,5
(`cahier/rubriques.py`). Pour imposer une durée : `<div class="bloc app" data-minutes="30">`,
le reste est réparti entre les autres blocs.

Ces minutes apparaissent dans le panneau « Séance », dans le cahier de textes (durée de la
séance, progression de la leçon) et, en présentation, dans le **minuteur** en haut à droite :
il décompte le temps du paragraphe en cours jusqu'à zéro (clic : pause / reprise,
double-clic : recommencer ; revenir à un paragraphe reprend son temps restant).

## Cahier de textes : niveaux et PDF

`/cahier-de-textes/` affiche une carte par niveau (niveaux des cours enregistrés, `Course.NIVEAU_CHOICES`)
avec le nombre de séances. Chaque carte ouvre `/cahier-de-textes/niveau/<niveau>/` : séances de la plus
récente à la plus ancienne, numérotées par classe (rang chronologique), recherche (titre, contenu,
observations), filtre par période et par classe, pagination (15 par page), observations modifiables.

PDF générés sur le serveur avec reportlab (`cahier/pdf.py`, polices DejaVu dans `cahier/fonts`) :
une séance (`seance/<pk>/pdf/`), une sélection (`niveau/<niveau>/pdf/?ids=…`, ordre chronologique) ou
tout le niveau (`niveau/<niveau>/pdf/`, avec couverture, période et sommaire).

Droits : un enseignant ne voit que ses séances ; un compte « staff » ou superutilisateur voit celles de
tous les enseignants (lecture et PDF), mais seul l'auteur d'une séance la modifie ou la supprime.

## Documents d'une leçon (boutons COURS et EXERCICES)

En bas de la page d'une leçon, deux boutons ouvrent la liste des documents :

- **COURS** : les PDF du dossier `media/lessons/<niveau>/<leçon>/Cours`, les documents de l'admin de
  catégorie « Cours », le PDF historique de la leçon et, s'il existe, le cours en ligne.
- **EXERCICES** : les PDF du dossier `Exercices` et les documents de catégorie « Exercices ».

Chaque document a « Ouvrir » (affichage dans le navigateur : PDF, images, texte) et « Télécharger ».
Les formats non lisibles par le navigateur (Word, PowerPoint, Excel, GeoGebra, ZIP…) n'ont que
« Télécharger ». Les documents de catégorie « Autre ressource » restent dans « Ressources
pédagogiques complémentaires ».

**Admin › Leçons › une leçon › Documents de la leçon** : ajouter autant de documents que nécessaire
(catégorie, ordre, titre, description, fichier). Remplacer le fichier d'un document supprime
l'ancien fichier ; supprimer le document supprime son fichier. Le « Gestionnaire de fichiers »
(Admin › Cours) continue de ranger les PDF dans les dossiers `Cours` / `Exercices`.

## Suivi du temps d'enseignement

- **Durée prévue** d'une leçon : Admin › Leçon › « Durée prévue (minutes) ». Vide : volume de
  `education/data/repartition_horaire.json` (1BAC_SE, TCS).
- **Durée réalisée** d'une séance : saisie dans le panneau « Séance » (proposée d'après les éléments
  cochés) ou modifiée sur la page du niveau (« Ajouter une observation · durée »). Une séance
  ancienne sans durée compte la durée prévue de ses éléments.
- Réalisé = somme des durées des séances (même enseignant, même classe, même leçon) ; restant =
  prévu − réalisé (jamais négatif) ; progression = réalisé / prévu × 100 (deux décimales). Le calcul
  est refait à chaque affichage : enregistrer de nouveau, modifier ou supprimer une séance ne
  déduit jamais deux fois.
- La barre (prévu, réalisé, restant, % réalisé / % restant) apparaît dans le panneau « Séance »
  après chaque enregistrement, en haut de la page du niveau (« Progression des leçons ») et sur
  chaque séance.

## Outil de conversion LaTeX → cours en ligne

`tools/tex2html.py` (aucune dépendance). Voir l'aide en tête du fichier, par exemple :

    python tools/tex2html.py TC_Polynomes.tex 4 templates/education/cours/TCS/04_les-polynomes.html \
        "Tronc commun scientifique" TCS "8 heures"

## Situation problème 3D (Produit scalaire, 1ère Bac SE)

Le cours `1BAC_SE/04_le-produit-scalaire-dans-le-plan.html` commence par une partie `s0`
(« ★ Situation problème : le travail d'une force »), placée juste après la couverture et le
sommaire. Elle contient un bloc `act` de durée fixe (`data-minutes="30"` : cahier de textes et
minuteur de présentation). Les clés des autres blocs (`s1-b1`…) ne changent pas.

- Scène Three.js : `static/js/situation-produit-scalaire.js` (module, Three.js local),
  styles `static/css/situation.css`, chargés par le bloc `scripts_cours` du gabarit. Sans WebGL,
  une figure SVG de secours reste affichée et les calculs restent interactifs.
- Huit étapes : Observer → Question 1 a) → 1 b) → Question 2 → Manipuler → Vers les mathématiques
  → Généraliser → Vers le cours. La définition du produit scalaire n'apparaît qu'à l'étape 6.
- → / télécommande : affiche la réponse de l'étape, puis l'étape suivante ; après la dernière,
  la page suivante (partie I). ← revient en arrière. Mécanisme générique de `cours.js` :
  un élément `[data-etapes-internes]` expose `el.etapesInternes = { avancer(), reculer() }`,
  et `[data-insecable]` empêche de le couper entre deux pages.
- La hauteur du bloc ne varie pas d'une étape à l'autre (étapes superposées, réglages réservés) :
  la pagination reste exacte sur ordinateur, téléphone et vidéoprojecteur.
