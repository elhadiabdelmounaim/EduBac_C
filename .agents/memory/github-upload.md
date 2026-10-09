---
name: GitHub upload authentication
description: Shell Git credentials and the GitHub connector have separate authentication.
---

Use the authenticated GitHub connector when shell Git rejects credentials despite a healthy connection.

**Why:** Connecting GitHub granted repository write access but did not repair the shell credential helper. Uploading through the Git Data API succeeded.

**How to apply:** Check the remote head first, build changes against that tree, verify the resulting tree matches the intended local tree, and update the ref with `force: false`. API uploads can produce a different commit lineage from local checkpoints even when file trees match; compare contents and preserve remote changes rather than force-pushing.

Prefer uploading the exact local commits through the Git Data API, preserving their parents, message, author/committer identities and timezone-aware timestamps. Verify every returned tree and commit SHA before updating the branch.

**Why:** Creating replacement commits with new metadata left identical content on divergent histories and caused the user's next normal push to be rejected. Exact commit uploads avoid that; an existing divergence can be resolved with a non-destructive merge first.
