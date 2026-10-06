# Whiteboard tutor

This extends the existing board and provider registry; it is not another chatbot
or board implementation. POST `/tableau/<id>/tutor/` accepts current structured
objects, selection, question, help mode, attempts, exercise and an optional image.
The lesson and student level are resolved on the server. Conversation history is
bounded in the authenticated session, not trusted from client-supplied role messages.

Only `add_text`, `add_equation`, `add_note` responses pass validation. The frontend
requires explicit insertion, applies a batch as one undo step and saves using the
existing board API. Read-only students can ask and select but cannot insert.
Personal student boards use the existing model and ownership permissions.

Text uses the configured provider. Images use the same provider with
`WHITEBOARD_VISION_MODEL` when configured; Groq uses `qwen/qwen3.8-27b` for vision
(verified against its live model inventory). No credentials are sent to the browser.
If a provider cannot process images, requests fail explicitly rather than invent
an image interpretation. Gemini's existing text adapter is not multimodal here.

The exact arithmetic check supports simple linear equations in x only, with
rational arithmetic and an AST allowlist (no eval). Other mathematics is assessed
by the model and visibly identified as AI assessment, not a formal proof.

Rate limits: 12 requests/user/minute and 60 global/minute in Django's configured
cache. For multiple server processes, use a shared cache to make limits global
across workers; the default local cache only coordinates within one process.
Chat history survives page reload in the session for model context, but the
frontend transcript is not replayed after reload. Board objects are persisted.

Checks:

    cd EduBac
    python manage.py test --noinput
    node --test whiteboard/frontend.test.cjs

The signed-in board UI requires browser verification with an authenticated account;
public screenshots intentionally show login. Tests exercise both roles, context,
the hint / erroneous attempt / solution flow, safe actions, persistence, image
transport, undo/redo and failure paths.
