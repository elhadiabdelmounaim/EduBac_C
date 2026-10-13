---
name: Teacher quiz grounding
description: User-approved scope for teacher quiz inputs and the agent's prior knowledge.
---

The teacher must be able to select existing lesson files and upload new files together. Generation combines those choices with the teacher's description and the agent's mathematical knowledge.

The agent may add related knowledge and questions not explicitly present in the documents, while respecting the chosen school level and teacher objectives. Resource-free generation using the description and agent knowledge is allowed.

**Why:** The user explicitly selected all three behaviors when clarifying teacher quiz generation. A document-only restriction would contradict their choice.

**How to apply:** Limit file grounding to the teacher's explicit choices, but do not restrict the questions to quotations or notions appearing in those files. Keep complementary knowledge tied to the same subject and school level.
