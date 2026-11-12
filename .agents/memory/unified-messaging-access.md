---
name: Unified messaging access
description: Preserve the role and class boundaries for peer chats, consultations, and the shared admin inbox.
---

Peer direct conversations use one canonical thread per student pair and remain accessible while the students share any active class. Teacher consultations remain separate by class, so a student and teacher assigned to multiple shared classes can have a consultation for each one.

Current assumption: student-to-admin messages are attached to the first active superuser, falling back to the first active staff account. Other active staff members can read and reply to that shared inbox.

**Why:** The app has no separate admin identity model; shared access prevents student support threads from depending on one staff member being available.

**How to apply:** Keep contact discovery and message APIs class-aware on the server. Do not turn teacher consultations into peer DMs or split the admin inbox by staff account unless the product explicitly changes.
