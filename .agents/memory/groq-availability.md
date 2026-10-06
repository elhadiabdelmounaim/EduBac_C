---
name: Groq model availability
description: Live provider availability differs from the imported model defaults.
---

Verify Groq model availability with a real request rather than trusting the imported model list.

**Why:** During tutor verification, both imported Llama defaults were unavailable; the existing fallback to `openai/gpt-oss-20b` succeeded. The project model setting was adjusted to the working model to avoid repeated failed requests.

**How to apply:** When changing or diagnosing the provider, test the configured model and report connection results separately from answer accuracy. Recheck availability rather than assuming this observation remains current.
