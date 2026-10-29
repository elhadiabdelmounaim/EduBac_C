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

Evaluate speed by time to a complete, valid quiz, not just model throughput or the number of calls. Never reduce correctness or diversity checks to improve a timing result.

**Why:** The user approved performance work only without compromising question quality, relevance or diversity. Small output budgets can create partial responses and extra repairs; splitting large outputs can avoid truncation but add quota waits.

**How to apply:** Account for the combined quota pressure of generation, corrections and optional semantic review. Report local processing benchmarks separately from measured provider latency, and retain fresh source reads rather than caching quiz answers.

For the multi-stage teacher protocol, allow bounded recovery of short quota waits at the interrupted call, without restarting completed stages.

**Why:** Analysis, generation and review share the provider quota. A single wait allowance designed for the former generation-only request can be exhausted before later mandatory checks finish.

**How to apply:** Keep retry allowances shared across the entire request and subordinate to its overall deadline, rather than resetting them for every stage or question. Preserve completed batches and all quality checks; long or repeated limits must still stop explicitly.

Compare completed quizzes separately from early failures when evaluating performance.

**Why:** A live performance baseline included fast pedagogical refusals and quota failures. Completing those same requests after fixing recovery takes longer, but cannot honestly be described as a latency regression or a demonstrated speedup.

**How to apply:** Report outcome, question count, API attempts and quota waiting alongside elapsed time. HTTP response-header timing is not time to the first generated token; the non-streamed quiz response does not expose that measurement.
