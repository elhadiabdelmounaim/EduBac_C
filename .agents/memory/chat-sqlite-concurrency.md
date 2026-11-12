---
name: SQLite chat write pressure
description: Concurrency limits affecting chat read-state updates
---

Keep message polling endpoints read-only. Mark messages as read through explicit POST requests when the chat opens or new incoming messages arrive; repeated GET polling should not update read-state rows.

**Why:** SQLite serializes writes. Concurrent message polling, read-state updates, and presence writes caused a `database is locked` error in classroom chat.

**How to apply:** Keep state mutations out of chat GET handlers and avoid repeating read updates when no incoming messages arrived. A longer SQLite timeout is a fallback, not a substitute for reducing write contention.
