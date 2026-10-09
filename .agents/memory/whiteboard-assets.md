---
name: Whiteboard asset cache compatibility
description: Avoid mismatched cached JavaScript and updated Whiteboard controls.
---
Version the Whiteboard script, object helper and stylesheet URLs together whenever their DOM or shared interface changes.

**Why:** Replacing a toolbar control while keeping unversioned script URLs allowed an older cached script to reference a removed element, throwing before board initialization and disabling all tools. The stale-script/new-template combination reproduced this failure even though fresh-browser tests passed.

**How to apply:** Bump the shared asset revision when changing these files, or use content-hashed assets. Treat optional toolbar controls as nullable. Test initialization and real drawing, not only toolbar appearance.
