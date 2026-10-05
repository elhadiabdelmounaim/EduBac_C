# AI Multi-Provider — EduBac

## Architecture

```
AIService (ai/services.py)
        │
        ▼
get_provider(name)  →  ai/providers/
        ├── groq.py
        ├── openrouter.py
        └── gemini.py
```

Le Quiz Generator (`generate_quiz_from_lesson`) ne dépend jamais d’un fournisseur concret.

## Variables .env

```
AI_DEFAULT_PROVIDER=groq

GROQ_API_KEY=
GROQ_MODEL=llama-3.1-8b-instant

OPENROUTER_API_KEY=
OPENROUTER_MODEL=openrouter/free

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
```

## Usage code

```python
from ai.services import AIService

ai = AIService(provider="openrouter", model="meta-llama/llama-3.1-8b-instruct:free")
data = ai.generate_quiz_from_lesson(lesson, question_count=10, difficulty="moyen")
```

## Ajouter un provider (OpenAI, Anthropic, …)

1. Créer `ai/providers/mon_provider.py` héritant de `BaseProvider`
2. Implémenter `chat(...)`
3. Enregistrer dans `ai/providers/__init__.py` → `PROVIDERS`
4. Aucune modification du Quiz Generator

## Tuteur interactif

Après connexion, ouvrir `/ai/assistant/` ou le lien d'aide d'une leçon.
Choisir une leçon et un niveau d'explication, puis poser une question ou envoyer
sa tentative de solution. « M'entraîner » propose un exercice sans solution
immédiate ; les échanges suivants permettent de demander des indices et une
correction. L'historique permet de reprendre une conversation ou d'en commencer
une nouvelle.

Le tuteur utilise le contenu de la leçon et les 12 derniers messages de la
conversation. Les conversations restent privées à leur propriétaire. La
reformulation utilise la réponse sauvegardée côté serveur, pas un texte envoyé
par le navigateur. Aucune nouvelle migration n'est nécessaire.

Le fournisseur par défaut reste Groq. Configurer `GROQ_API_KEY` dans les Secrets
du projet (jamais dans le code ni dans le chat). Sans fournisseur configuré,
la page affiche une erreur explicite et conserve la question sans enregistrer
de réponse fictive.

Vérification locale : `python EduBac/manage.py test ai --noinput`.
Ces tests simulent le fournisseur ; ils ne valident pas une connexion API réelle.
