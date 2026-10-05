# Schéma Whiteboard de correction (v1)

Document JSON validé **uniquement côté serveur** (`whiteboard/schema.py`).

## Racine

| Champ | Contrainte |
|-------|------------|
| `version` | entier = 1 |
| `title` | texte ≤ 120 car. |
| `elements` | liste ≤ 60 |
| `connections` | liste ≤ 100 |
| Taille totale JSON | ≤ 200 Ko |

## Élément (champs communs)

- `id` : `^[a-z0-9_-]{1,40}$`, unique
- `type` ∈ title, text, step, formula, rule, calculation, result, table, chart, diagram
- `position` : `{x, y}` entiers −5000…5000 (assignés par le layout serveur si absents)
- `size` : `{width, height}` 40…2000
- `zIndex` : entier
- `locked` : booléen
- `group` : id optionnel
- `style.emphasis` ∈ normal, success, warning, error

## Contenu par type

- **title / text / rule / result** : `text` ≤ 2000
- **step** : `text` ≤ 2000, `label` ≤ 40
- **formula / calculation** : `latex` ≤ 500
- **table** : headers ≤ 8, rows ≤ 20, cellule ≤ 100
- **chart** : kind line|bar|scatter, series ≤ 5, points ≤ 200
- **diagram** : kind geometry|flow, ≤ 30 primitives déclaratives (pas de SVG brut)

## Connexions

`id`, `from`/`to` `{elementId, anchor}`, `label` ≤ 60. Références existantes, pas d’auto-référence.

## Révélation

- Mode **full** : tentative soumise → bonne réponse autorisée dans le contexte IA.
- Mode **hint** : tentative en cours → aucune bonne réponse ni résultat final.
