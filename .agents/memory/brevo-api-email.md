---
name: Brevo email API
description: EduBac production email transport and deployment constraints for PythonAnywhere.
---

Use Brevo's REST API over HTTPS for EduBac email instead of SMTP. Keep Django's email backend as the central transport so verification, notifications, and password resets share the same delivery path. The production host needs its own `BREVO_API_KEY`; Replit secrets and integrations do not transfer to PythonAnywhere.

**Why:** The user explicitly requested migration away from SMTP for PythonAnywhere Free and forbids IP allowlisting or SMTP keys for this path.

**How to apply:** Configure the API key privately on the deployment host and set an email sender already verified in Brevo. Keep API keys, token-bearing links, and provider response bodies out of logs. Use the project's API connection/send test command after deployment.
