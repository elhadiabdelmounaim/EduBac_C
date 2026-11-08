---
name: Static CSS cache versions
description: Keep versioned stylesheet URLs aligned with changed responsive styles.
---
When editing static CSS linked with a version query string, bump that value in the linking template, including page-specific stylesheets.

**Why:** The browser preview retained old CSS while the URL stayed unchanged, so a tablet screenshot continued showing the old layout after the stylesheet source was updated.

**How to apply:** After CSS changes, locate the stylesheet links and revise their version tokens before visual verification.
