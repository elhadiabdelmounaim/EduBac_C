---
name: Whiteboard tutor constraints
description: Product scope and verification boundaries for EduBac's interactive tutor.
---

Extend the existing Whiteboard and provider service, not a parallel app. Preserve existing features and compatibility with student and teacher dashboards.

**Why:** The user explicitly required a real contextual tutor inside the current Django project, not a standalone or cosmetic chatbot.

**How to apply:** Questions must use the current board, selection, lesson and student level. AI additions remain editable board objects, with only data-only allowed actions and existing permissions.

Do not present model judgment as formal mathematical verification.

**Why:** Exact checking intentionally covers only simple linear equations; general mathematical correctness is not guaranteed by an LLM. Live model responses also wrapped equation actions in display delimiters despite the prompt.

**How to apply:** Keep validation independent of prompting, normalize equation delimiters before KaTeX rendering and disclose the boundary of deterministic checks.
