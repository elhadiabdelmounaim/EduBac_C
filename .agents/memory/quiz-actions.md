---
name: Quiz actions stay in the site
description: User requirement for teacher-facing quiz management.
---

The user does not want the quiz Edit button to open Admin; they requested a Refuser or Delete button instead.

**Why:** The user explicitly rejected the Admin redirect.

**How to apply:** Keep teacher-facing quiz deletion inside the site's confirmation flow; do not reintroduce an Admin edit link in the quiz list.

Après la modification du quiz, on peut retourner à la page du quiz à partir d’« Enregistrer », sans rejeter le quiz.

**Why:** The user explicitly asked to return to the same quiz after saving edits.

**How to apply:** Saving manual edits and returning from the editor must reopen the persisted quiz preview, not an empty generation form. Returning must not generate, delete, or discard the quiz.
