---
name: Whiteboard tutor constraints
description: Product scope and verification boundaries for EduBac's interactive tutor.
---

Extend the existing Whiteboard and provider service, not a parallel app. Preserve existing features and compatibility with student and teacher dashboards.

**Why:** The user explicitly required a real contextual tutor inside the current Django project, not a standalone or cosmetic chatbot.

**How to apply:** Questions must use the current board, selection, lesson and student level. AI additions remain board objects, with only data-only allowed actions and role permissions; student editing is no longer allowed.

Do not present model judgment as formal mathematical verification.

**Why:** Exact checking intentionally covers only simple linear equations; general mathematical correctness is not guaranteed by an LLM. Live model responses also wrapped equation actions in display delimiters despite the prompt.

**How to apply:** Keep validation independent of prompting, normalize equation delimiters before KaTeX rendering and disclose the boundary of deterministic checks.

The post-quiz Whiteboard is rule-only, unlike the ordinary tutor's solution mode. Opening it must discard all previous board content and resolution steps, then show the general rule and a short explanation of its purpose in one centered light-green box.

**Why:** The user explicitly requested this distinction, the light-green presentation, a short general explanation (not calculations), and the exact existing Generate → Explanation math rendering without a new renderer.

**How to apply:** Preserve the rule-only scope when extending quiz correction flows. Never use a worked solution as a fallback; if rule identification fails, leave the board empty and show an explicit error.

Students must see read-only whiteboards with only the board frame, the question result and the existing rule, without editing controls. Teacher editing remains unchanged.
Keep a “Retour aux résultats” navigation button above the student correction board, aligned right.

**Why:** The user explicitly requested removing student Whiteboard editing and displaying only the inner frame, question result and existing rule.

**How to apply:** Enforce read-only access server-side as well as in the interface, including student-owned and classroom boards. Reveal the question result only after submission; preserve the existing rule rendering.

Use Mathpix as the selected handwriting/math recognition provider for the existing Whiteboard.

**Why:** The user chose Mathpix after comparing it with general-purpose AI.

**How to apply:** Keep recognition separate from tutoring. Provider selection alone does not authorize buying a subscription. Preserve original strokes until the teacher previews and confirms the recognition result; do not promise Arabic handwriting support.
