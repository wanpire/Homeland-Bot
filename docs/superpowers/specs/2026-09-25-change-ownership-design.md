# Change Ownership (My Services) — Design Spec

Date: 2026-09-25
Status: approved; the recipient-consent safeguard was chosen by the owner
Mirrors AloBot's `myservices:transfer:*` in `~/AloBot/app/bot/handlers/users.py`,
plus a safeguard AloBot lacks.

## 1. What "ownership" means

The same as in AloBot: the Telegram user whose `telegram_id` is on the
`vpn_users` row. That user sees the account in My Services and can
renew it, reset its password or transfer it. A transfer rewrites that
one column. The IBSng account itself (username, password, group) is
untouched.

## 2. AloBot's version and the gap

The owner types the recipient's Telegram @username, which must belong to
someone who has started the bot. A transfer to yourself is refused.
There is one "irreversible" confirmation, then the account moves at once
and the recipient is notified. Only the owner can start a transfer, and
ownership is re-checked at each step. **There is no recipient consent
and no audit trail**, and the @username comes from `bot_users`, captured
when that person was last seen, so it can be stale. As the request
asked, this was flagged. The owner chose to require the recipient's
acceptance.

## 3. Flow

1. Account menu → 🔄 Change ownership (`myservices:xfer:<id>`, owner-checked).
   The bot asks for the new owner's @username or numeric Telegram ID (FSM
   state, Redis). [🔙 Back] returns to the account menu and clears the state.
2. The recipient is resolved against `bot_users`: by ID, or by
   @username (case-insensitive). The bot re-prompts on: not found (they
   must have started the bot), the owner themselves, a blocked user, or
   an @username shared by several rows (then asks for the numeric ID).
3. Confirm screen: "Account X will be offered to @user (ID …). It
   stays yours until they accept." [✅ Send request]
   (`myservices:xferask:<id>:<recipient>`, re-validated on tap) [🔙 Back].
4. Sending creates an `ownership_transfers` row (`pending`), cancels any
   older pending request for the same account, and messages the recipient
   in their language: who is offering which account.
   [✅ Accept → `xfer:accept:<t>`] [❌ Decline → `xfer:decline:<t>`].
   The owner's screen says the request was sent and offers
   [❌ Cancel request → `xfer:cancel:<t>`]. If the recipient cannot be
   reached (they blocked the bot), the row is cancelled and the owner is
   told.
5. **Accept.** Only the named recipient can accept. The row must be
   pending and younger than 24 hours, and the account must still belong
   to the offering owner (both rows locked). Then `vpn_users.telegram_id`
   becomes the recipient, the row becomes `accepted`, the recipient sees
   a success message linking to My Services, and the owner is told. The
   transfer is posted to the admin log group (new `OWNERSHIP` event,
   "🔑 Accounts" topic).
6. **Decline / cancel / expiry.** The row becomes `declined`,
   `cancelled` or `expired`, and the other party is told. The account is
   never touched.

## 4. Decisions

- **The password is not rotated on transfer, matching AloBot.** The old
  owner still knows it. To let the new owner lock them out at once,
  acceptance clears `password_changed_at`, so the 30-day reset limit
  never blocks the new owner. The acceptance message says so.
- **Every transition is re-checked against the database on the tap.**
  Callback data (including the recipient id in `xferask`) is treated as
  untrusted.
- **New table `ownership_transfers`** (migration `0011`): id,
  vpn_user_id, from_telegram_id, to_telegram_id, status, created_at,
  resolved_at, offer_message_id (used to update the recipient's message
  on cancel). Each request also serves as an audit trail.

## 5. Tests

Recipient resolution: by ID and by @username; not found; self; blocked;
ambiguous username. The confirm step sends nothing. A request creates a
pending row and messages the recipient, and the account does not move.
Accept moves it, logs it, notifies both parties and clears the password
cooldown. Decline and cancel leave the account in place. Nobody but the
named recipient can accept. An expired request cannot be accepted. A
request made stale by an earlier transfer cannot be accepted. A newer
request supersedes the older one. An unreachable recipient cancels the
request.
