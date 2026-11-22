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
