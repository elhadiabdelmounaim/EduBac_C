---
name: Admin-managed student password recovery
description: Product and security boundaries for recovering EduBac student accounts
---

Only the superuser may reset a student's password, after directly verifying the student's identity. Recovery must not send email, use Brevo, create a replacement account, or alter school records. Show the cryptographically random temporary password once; never persist it in plaintext or logs; require the student to choose a strong new password before accessing the platform. Record the acting administrator and reset time.

An administrator-verified reset must work without email verification, while leaving the account's email-verification field unchanged. This keeps the no-email recovery promise separate from signup and legacy email-verification behavior.

**Why:** The user requires direct administrator recovery with no email and preservation of all existing account data.

**How to apply:** Keep reset authorization superuser-only, preserve the existing account and related records, and maintain the one-time temporary-password / mandatory-change flow.
