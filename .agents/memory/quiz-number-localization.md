---
name: HTML number inputs and French locales
description: Prevent Django localization from clearing decimals in HTML number fields.
---

For French-localized pages, format decimal values without locale separators before putting them in `input type="number"`. A comma decimal separator can be rejected by browsers, clearing the field and preventing form submission.

**Why:** A persisted decimal appeared blank in the browser even though the database value was correct; native form validation then blocked editing and deletion.

**How to apply:** When rendering numeric fields in localized Django templates, verify the actual browser value as well as the database value, and emit an unlocalized dot-decimal string.
