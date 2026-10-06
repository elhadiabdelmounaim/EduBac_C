---
name: GitHub upload authentication
description: Shell Git credentials and the GitHub connector have separate authentication.
---

Use the authenticated GitHub connector when shell Git rejects credentials despite a healthy connection.

**Why:** Connecting GitHub granted repository write access but did not repair the shell credential helper. Uploading through the Git Data API succeeded.

**How to apply:** Check the remote head first, build changes against that tree, verify the resulting tree matches the intended local tree, and update the ref with `force: false`. API uploads can produce a different commit lineage from local checkpoints even when file trees match; compare contents and preserve remote changes rather than force-pushing.
