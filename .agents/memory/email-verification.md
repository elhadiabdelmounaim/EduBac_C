---
name: Email verification compatibility
description: Preserve legacy email-verification behavior while student signup uses usernames and admin approval.
---
Student registration must not display or require an email address. Students register with a full name, username, password confirmation, and an active class code; their account remains pending until the principal administrator approves it.

**Why:** The user specified that EduBac signup should not be by email and defined administrator approval as the gate before student access.

**How to apply:** Do not send a registration verification email or require email for new student accounts. Preserve email addresses and verified states for existing accounts; keep email verification separate for legacy accounts that have an address.

Existing email-verification behavior remains: resend cooldowns start only after Django's email backend confirms one accepted message. Keep concurrent-send locking separate, release it on send failure, retain the IP-based rate limit, and never log recipient addresses or verification tokens.

**Why:** Reserving the cooldown at request start made interrupted or rejected sends appear successful and prevented legitimate retries.

**How to apply:** Store the successful-send timestamp after the backend returns one message, derive remaining time from `EMAIL_VERIFICATION_RESEND_COOLDOWN`, and preserve anti-abuse limits independently.
