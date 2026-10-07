---
name: Groq model availability
description: Live provider availability differs from the imported model defaults.
---

Verify Groq model availability with a real request rather than trusting the imported model list.

**Why:** During tutor verification, both imported Llama defaults were unavailable; the existing fallback to `openai/gpt-oss-20b` succeeded. The project model setting was adjusted to the working model to avoid repeated failed requests.

**How to apply:** When changing or diagnosing the provider, test the configured model and report connection results separately from answer accuracy. Recheck availability rather than assuming this observation remains current.

Account for requested output tokens as well as input size when checking Groq request budgets. Its JSON mode can also reject a request before returning any text.

**Why:** Live quiz verification encountered a token-limit rejection with an oversized output allowance and intermittent `json_validate_failed` errors.

**How to apply:** Size structured requests proportionally to their output, bound history comparisons, and keep strict server-side JSON validation if retrying without provider-enforced JSON mode.
