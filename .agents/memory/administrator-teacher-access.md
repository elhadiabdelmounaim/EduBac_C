---
name: Administrator teacher access
description: EduBac's Django staff and superuser accounts must use teacher capabilities without changing the stored application role.
---

Treat Django staff and superusers as teachers for EduBac access, routing, and permissions even when their stored `role` is `student`.

**Why:** The user asked that newly created Django superusers enter the teacher area and receive teacher permissions without changing the role value saved in the database.

**How to apply:** Base authorization on `is_staff` / `is_superuser` alongside the role helper. Keep student-only areas unavailable to administrators, and do not rewrite their `role` field to make teacher routing work.
