---
name: Browser regression testing
description: Real session coverage and Playwright/Django lifecycle constraints
---
Use real login-form submissions for navbar browser coverage, not authenticated
template fixtures.

**Why:** Template fixtures cannot verify session middleware or authenticated
notification requests; the requested regression gate explicitly requires both.

**How to apply:** Use isolated Django live-server test data and confirm protected
HTTP responses after login.

Stop the synchronous Playwright runtime before Django's database teardown, and
seed ORM data before starting it.

**Why:** Playwright's sync runtime keeps an event loop active on the calling
thread; Django then rejects synchronous ORM operations and test database flushes.

**How to apply:** Scope browser/runtime cleanup to each test, not the entire test
class. Do not globally disable Django's async safety checks.

For the bottom of long KaTeX lessons, verify with a browser scroll after rendering settles rather than relying on a screenshot URL fragment.

**Why:** Anchor-based captures of the functions lesson showed blank space despite the footer being visible and functional after a settled browser scroll.

**How to apply:** Wait for page resources and mathematical rendering, scroll the actual footer into view, then inspect its screenshot at desktop and phone widths.
