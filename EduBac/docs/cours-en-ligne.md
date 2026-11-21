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
