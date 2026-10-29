---
name: QCM answer integrity
description: Preserve valid questions and never invent a correct answer while repairing AI output.
---

When a math reviewer rejects a question, missing competency metadata must not prevent targeted repair of that question. Keep the requirement for a meaningful mathematical reason and solution; require competency metadata only before approving and saving an accepted question.

**Why:** Live review of a false polynomial-root question correctly rejected it but omitted its competency, and strict validation discarded the entire generated quiz instead of repairing the bad question.

**How to apply:** Treat incomplete explanation/review structure as a failed-closed error, but keep fields used only for accepted questions optional during rejected-slot repair.

Repair or replace only invalid QCM questions, preserving valid questions and their order. Never designate the first answer as correct merely because the model omitted or contradicted the answer.

**Why:** The user explicitly requires at least two choices, preferably four distinct choices, exactly one valid correct answer belonging to the choices, and preservation of already valid questions.

**How to apply:** Validate before saving or displaying. Use bounded targeted AI correction followed by replacement; if neither yields a valid QCM, refuse the invalid quiz rather than fabricate answers or silently drop questions. Keep existing novelty checks and mathematical rendering intact.

Do not describe structural QCM validation as a guarantee of mathematical correctness.

**Why:** Live resource-based generation produced a well-formed question claiming an error in an actually correct equation-solving procedure.

**How to apply:** Report input grounding and structural validation separately from mathematical verification. Teacher review remains necessary unless an independent mathematical check has actually verified the question and correction.
