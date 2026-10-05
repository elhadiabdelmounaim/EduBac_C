# EduBac

Imported Django application; source remains in `EduBac/`. Keep the existing
Python/Django stack and structure. The UI and educational content are in French.

## Development

Root `pyproject.toml` and `uv.lock` are the Replit dependency environment.
The imported dependency list is `EduBac/requirements.txt`.

- System checks: `python EduBac/manage.py check`
- Tutor tests: `python EduBac/manage.py test ai --noinput`

No run workflow is configured. Current verification uses Django tests and live
provider calls, not a browser session. Setting up a public preview requires
appropriate host/CSRF configuration and applying the existing migrations.

## AI

The tutor extends the existing `/ai/assistant/` flow and uses the existing
conversation tables. See `EduBac/AI_MULTI_PROVIDER.md`.
Keep provider credentials server-side in Secrets. `GROQ_MODEL` selects the model.
Tests mock external providers and never require a key.

## Storage caution

The imported SQLite default is under `/tmp`; it is not durable storage.
Do not silently replace the existing database backend or discard data.
