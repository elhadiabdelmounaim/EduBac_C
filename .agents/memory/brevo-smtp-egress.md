---
name: Brevo SMTP egress IP
description: Brevo IP allowlisting constraints when sending mail from Replit or PythonAnywhere.
---

Keep Brevo's SMTP IP blocking enabled per the user's choice. Direct SMTP from Replit or PythonAnywhere cannot be durably allowlisted because their outbound IPs are dynamic. A Brevo 525 response means the sending IP was rejected; it does not confirm whether SMTP credentials are valid.

**Why:** The user selected PythonAnywhere for production and chose to keep Brevo's IP blocking. Brevo requires SMTP client IPs to be authorized manually, while both hosting environments report dynamic outbound IPs.

**How to apply:** Use a fixed-egress host or TCP proxy and authorize its stable IP in Brevo. Disabling only SMTP-key IP blocking is an alternative, but requires the user's explicit approval. Replit secrets and environment variables do not transfer to PythonAnywhere; configure PythonAnywhere's private settings separately and keep credentials out of the repository.
