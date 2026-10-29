---
name: Teacher quiz grounding
description: User-approved scope for teacher quiz inputs and the agent's prior knowledge.
---

The teacher must be able to select existing lesson files and upload new files together. Generation combines those choices with the teacher's description and the agent's mathematical knowledge.

The agent may add related knowledge and questions not explicitly present in the documents, while respecting the chosen school level and teacher objectives. Resource-free generation using the description and agent knowledge is allowed.

**Why:** The user explicitly selected all three behaviors when clarifying teacher quiz generation. A document-only restriction would contradict their choice.

**How to apply:** Limit file grounding to the teacher's explicit choices, but do not restrict the questions to quotations or notions appearing in those files. Keep complementary knowledge tied to the same subject and school level.

The user adopted the sequential generation protocol while explicitly keeping resources optional: analyze the available pedagogical context, consult accessible history, generate, verify answers and novelty, then save.

**Why:** They selected “Intégrer en conservant les ressources facultatives” when asked how to apply their supplied protocol.

**How to apply:** Do not reintroduce mandatory files or disable quality checks merely to speed generation. Unavailable checks must be reported honestly; do not invent successful verification or fill the requested count with repetitions. Distinguish AI cross-review from mathematical proof.
