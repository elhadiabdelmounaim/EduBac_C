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
