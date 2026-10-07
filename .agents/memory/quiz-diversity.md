---
name: Quiz diversity policy
description: Standing requirement for genuine novelty across repeated lesson quiz generations.
---

Every quiz generation must be genuinely different even when the teacher selects identical parameters. Reordering questions or changing only numbers, variables, wording or answer choices is not sufficient.

**Why:** The user explicitly requires varied situations or reasoning, not superficial variants.

**How to apply:** Keep level, lesson, difficulty, question count and teacher objectives intact while checking prior lesson generations and duplicates within the new quiz. If attempts cannot satisfy diversity, show an error rather than save a duplicate or silently change the constraints.

Do not treat high wording similarity alone as proof of duplicate mathematical reasoning.

**Why:** Derivative and primitive exercises with otherwise identical wording exceeded 90% text similarity, causing valid distinct reasoning to be rejected before semantic review.

**How to apply:** Reject canonical repetitions locally; retain mandatory semantic review for non-exact matches before persistence. An invalid review response must fail closed with an availability/validation error, not claim that a duplicate was confirmed.
