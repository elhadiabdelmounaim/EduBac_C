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

The post-quiz Whiteboard is rule-only, unlike the ordinary tutor's solution mode. Opening it must discard all previous board content and resolution steps, then show the general rule and a short explanation of its purpose in one centered light-green box.

**Why:** The user explicitly requested this distinction, the light-green presentation, a short general explanation (not calculations), and the exact existing Generate → Explanation math rendering without a new renderer.

**How to apply:** Preserve the rule-only scope when extending quiz correction flows. Never use a worked solution as a fallback; if rule identification fails, leave the board empty and show an explicit error.
