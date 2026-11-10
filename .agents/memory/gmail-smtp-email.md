---
name: Gmail SMTP email
description: EduBac email transport requirements for Replit and PythonAnywhere.
---

EduBac uses Gmail SMTP for verification, password resets, notifications, and reminders. Store the Gmail account address and Google App Password only in each host's private environment; never use the account's ordinary password or expose either value in logs. Test SMTP authentication separately on Replit and PythonAnywhere, then send at most one administrator-directed test message before claiming delivery works.

**Why:** The user explicitly requested a complete migration from Brevo to Gmail SMTP. SMTP egress and Google account policy can differ across hosts, so a working application configuration alone does not prove the service is reachable.

**How to apply:** Use Django's shared SMTP backend with `smtp.gmail.com`, port `587`, and STARTTLS. Keep email verification enabled. Report a failed host test without sending any test mail, and don't treat Replit credentials or connectivity as proof that PythonAnywhere is configured.
