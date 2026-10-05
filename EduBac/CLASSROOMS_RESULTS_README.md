# Gestion des classes, résultats et Excel — EduBac

## Ce qui a été ajouté / finalisé

### Classes (app `classrooms`)
- **Créer** une classe (existant) — l’enseignant connecté est automatiquement propriétaire
- **Lister** ses classes uniquement
- **Voir** le détail (élèves, stats, quiz)
- **Modifier** nom / niveau (`/classrooms/<id>/modifier/`)
- **Supprimer** (POST + CSRF + confirmation) — les comptes élèves ne sont **jamais** supprimés
- **Résultats** par classe (`/classrooms/<id>/resultats/`)
- **Télécharger Excel** de la classe ou d’un quiz seul
- **Régénérer Excel** depuis la base Django

### Excel (openpyxl)
- Fichier **par classe** : `media/results/classes/classe_<slug>_<id>/results.xlsx`
- **Une feuille par quiz**
- Colonnes : Élève, Email, Score (%), Note /20, Questions, Bonnes, Mauvaises, Temps, Date, Heure, Tentative ID
- **Sync automatique** à chaque fin de quiz (résultat d’abord en base Django)
- Si l’écriture Excel échoue → le résultat Django est conservé (log uniquement)
- **Régénération** complète possible depuis la page résultats

### Architecture respectée
```
Élève termine le quiz
  → Attempt enregistré en DB (source principale)
  → sync Excel des classes de l’élève
```

## Fichiers modifiés / créés

| Fichier | Action |
|---------|--------|
| `classrooms/views.py` | Réécrit : edit, delete, results, downloads |
| `classrooms/urls.py` | Nouvelles routes |
| `classrooms/services/excel_results.py` | **Nouveau** — logique Excel |
| `classrooms/services/__init__.py` | Nouveau |
| `templates/classrooms/detail.html` | Enrichi (stats, actions) |
| `templates/classrooms/list.html` | Boutons Voir / Modifier / Résultats / Supprimer |
| `templates/classrooms/edit.html` | **Nouveau** |
| `templates/classrooms/delete_confirm.html` | **Nouveau** |
| `templates/classrooms/results.html` | **Nouveau** |
| `quizzes/views.py` | Hook `_sync_excel_after_submit` après `calculate_score` |

**Aucune migration** : les modèles n’ont pas changé.

## Prérequis

```bash
pip install openpyxl   # déjà dans requirements.txt
```

`MEDIA_ROOT` est déjà configuré dans `config/settings.py`.

## Comment tester

1. Connecter un **enseignant** → Créer une classe (ex. `2BAC PC-SVT`)
2. Noter le **code** d’invitation
3. Connecter 2–3 **élèves** → Rejoindre avec le code
4. Enseignant → Envoyer / publier un quiz et l’affecter
5. Élève → Terminer le quiz
6. Vérifier :
   - Résultat dans l’admin / page « Résultats des élèves »
   - Fichier créé sous `media/results/classes/classe_.../results.xlsx`
7. Enseignant → Classe → **Résultats** → Télécharger Excel
8. Tenter de supprimer la classe → confirmation, comptes élèves intacts
9. Un autre enseignant ne doit **pas** pouvoir accéder / télécharger / supprimer cette classe

## URLs utiles

```
/classrooms/
/classrooms/creer/
/classrooms/<id>/
/classrooms/<id>/modifier/
/classrooms/<id>/supprimer/
/classrooms/<id>/resultats/
/classrooms/<id>/resultats/excel/
/classrooms/<id>/resultats/regenerer/   (POST)
/classrooms/<id>/quiz/<quiz_id>/resultats/excel/
```
