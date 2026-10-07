---
name: QCM answer integrity
description: Preserve valid questions and never invent a correct answer while repairing AI output.
---

Repair or replace only invalid QCM questions, preserving valid questions and their order. Never designate the first answer as correct merely because the model omitted or contradicted the answer.

**Why:** The user explicitly requires at least two choices, preferably four distinct choices, exactly one valid correct answer belonging to the choices, and preservation of already valid questions.

**How to apply:** Validate before saving or displaying. Use bounded targeted AI correction followed by replacement; if neither yields a valid QCM, refuse the invalid quiz rather than fabricate answers or silently drop questions. Keep existing novelty checks and mathematical rendering intact.
