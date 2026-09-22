# Persian Category Labels — Design Spec

Date: 2026-09-24
Status: approved (requested directly)
Deliberately separate from the reporting epic: this is a display-string
change with no shared surface.

## 1. Change

Three Persian catalog category labels, via the existing `t()` system:

| slug | Persian before | Persian after | English |
|---|---|---|---|
| `stream` | 🌊 استریم | 🌊 تماشا | 🌊 Stream (unchanged) |
| `scroll` | 📜 اسکرول | 📜 وب‌گردی | 📜 Scroll (unchanged) |
| `trip` | 🧳 سفر کوتاه | 🧳 سفر | 🧳 Trip (unchanged) |

Note `trip`'s current Persian is "سفر کوتاه", not "تریپ" as the request
assumed; the change to "سفر" is a shortening rather than a
transliteration swap. The emoji prefixes are kept, matching every other
category label.

## 2. What is NOT touched

- **Internal slugs** `scroll`, `stream`, `trip` stay exactly as they
  are. They key the `Plan.category` column, `CATEGORIES`,
  `_BUY_CATEGORY_ORDER`, discount scoping and the campaign section map;
  renaming one would be a data migration, not a copy change.
- **English labels** are unchanged.
- **Admin screens** are unaffected: they are English-only by convention
  and never route category names through `t()`.

## 3. Tests

The existing i18n parity and count checks already cover key presence. A
test asserts the three new Persian strings and that the English ones did
not move, so a future edit cannot silently change one language only.
