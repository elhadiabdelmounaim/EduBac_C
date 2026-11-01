---
name: Private uploaded media
description: Keep classroom uploads and results behind Django authorization.
---
Do not map the entire media directory to a public static-file server. It contains classroom chat attachments and result files, alongside educational materials.

**Why:** A blanket media mapping bypasses membership and teacher permission checks, potentially exposing user uploads and class results.

**How to apply:** Map only collected static assets publicly. Serve each uploaded or result file through a Django view that repeats the same access checks as the page or API exposing it. Audit direct `FileField.url` uses before any production deployment.
