---
name: Email verification compatibility
description: Preserve access for existing EduBac users while requiring new password signups to verify email.
---
Existing user records must remain email-verified when the verification feature is introduced. Only newly created password signups are marked unverified; verification is a separate state from account activation.

**Why:** The user requires new accounts to verify their email without locking existing active accounts, including any that may have been created through an earlier social-login flow.

**How to apply:** Keep migration defaults verified for existing rows. Set verification explicitly for new signup paths, and gate their custom login/session paths without bulk-disabling accounts.
