# EduBac

Imported Django application; source remains in `EduBac/`. Keep the existing
Python/Django stack and structure. The UI and educational content are in French.

## Development

Root `pyproject.toml` and `uv.lock` are the Replit dependency environment.
The imported dependency list is `EduBac/requirements.txt`.

- System checks: `python EduBac/manage.py check`
- Tutor tests: `python EduBac/manage.py test ai --noinput`
- Navbar browser gate (before publishing): `python EduBac/manage.py test browser_tests --settings=browser_tests.settings --noinput`
  See `EduBac/browser_tests/README.md` for Chromium setup, coverage and diagnostics.

Run workflow: `cd EduBac && python manage.py migrate --noinput && python manage.py load_curriculum && python manage.py runserver 0.0.0.0:5000`.
The curriculum loader adds missing courses and lessons without replacing existing records.
Run the complete test suite from the application directory:
`cd EduBac && python manage.py test --noinput`. Running unlabelled discovery from
the workspace root does not discover the application's tests.

Development preview host and CSRF origin are restricted to the current Replit
development domain. Authentication is unchanged; signed-in pages are covered by
integration tests, not the public screenshot tool.

## AI

The tutor extends the existing `/ai/assistant/` flow and uses the existing
conversation tables. See `EduBac/AI_MULTI_PROVIDER.md`.
Keep provider credentials server-side in Secrets. `GROQ_MODEL` selects the model.
Tests mock external providers and never require a key.

## Storage caution

The imported SQLite default is under `/tmp`; it is not durable storage.
Do not silently replace the existing database backend or discard data.
