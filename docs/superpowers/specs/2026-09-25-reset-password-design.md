# Reset Password (My Services) — Design Spec

Date: 2026-09-25
Status: approved (requested directly)
Mirrors AloBot: `myservices:pwstart` / `myservices:pwdo` in
`~/AloBot/app/bot/handlers/users.py`, and `change_vpn_password` /
`password_change_remaining` in `~/AloBot/app/services/vpn_users.py`.

## 1. Behaviour (ported)

1. Account menu → 🔑 Change password (`myservices:pw:<id>`).
2. If the account's password was changed in the last 30 days: say how
   many days remain and stop (AloBot's once-a-month limit).
3. Otherwise a confirm screen: a new password will be generated, the
   username stays, once a month. [✅ Yes, generate] [🔙 Back].
4. `myservices:pwdo:<id>`: ownership and cooldown are re-checked, a new
   password is generated (the same generator as new accounts), it is set
   through `IBSngClient.change_user_password` (the single IBSng path),
   and `vpn_users.password_changed_at` is stamped. The new password is
   shown with the username, tap-to-copy, using the same bidi-safe lines
   as the account-info screen.

## 2. Homeland additions (safety, not UX)

- **Group guard.** The IBSng instance is shared with AloBot, and
  CLAUDE.md requires any path that modifies an account to check
  `is_homeland_group` first. The account's live group is read and the
  change is refused if it is not Homeland's.
- **No double change.** The row is locked (`SELECT … FOR UPDATE`) while
  the cooldown is checked, so two quick taps cannot rotate the password
  twice and leave the customer holding the losing one.
- **No raw errors.** AloBot shows the IBSng exception text to the
  customer. Homeland shows a bilingual "try again later" message and
  logs the detail.

## 3. Logging

AloBot does not log password changes, so per the request neither does
Homeland. The column `password_changed_at` already exists; there is no
migration.

## 4. Tests

Confirm step shown and nothing changed before it; confirm rotates the
IBSng password and shows it tap-to-copy with the username unchanged; a
second attempt within 30 days is refused with the days left; another
user's account cannot be changed; a non-Homeland group is refused; an
IBSng failure shows the friendly message and stamps nothing.
