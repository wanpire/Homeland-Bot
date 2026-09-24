# Unified Handover Sequence (Trial, Purchase, Renewal) — Design Spec

Date: 2026-09-25
Status: approved (requested directly)
Related: `2026-09-24-trial-os-first-delivery-design.md`,
`2026-09-23-shared-delivery-message-design.md`,
`2026-09-23-openvpn-setup-step-design.md`.

## 1. Summary

Every flow that hands a customer a working account (trial, purchase,
renewal) now runs one sequence, built once:

1. **Device** (iOS / Android / Windows / macOS).
2. **Protocol** (OpenVPN / L2TP), offering only the protocols that the
   device supports. If exactly one is left, as on Android (no L2TP),
   this step is skipped and that protocol is used without asking.
3. **Credentials**: the shared bilingual delivery message
   (`app/services/delivery.py`), with no buttons and no Tutorial-section
   paragraph.
4. **Setup for that device and protocol only**
   (`deliver_device_setup`): OpenVPN sends the config then that device's
   one app link; L2TP sends that device's guide then its link. It never
   asks for the device again and never lists every store URL.
5. **Tutorial / Back to Main Menu**: one pair, attached to whichever
   message came last.

Before this change the trial ran protocol → device, and purchase/renewal
sent credentials with Tutorial buttons, then the config, then a second
platform picker (`ovpn:link:*`) whose Tutorial button repeated the one on
the credentials.

## 2. Architecture

- `app/services/tutorials.py` gains `protocols_for_platform(platform,
  protocols)`, which filters through the existing
  `is_protocol_valid_for_platform`. This is the one compatibility rule.
  The protocol keyboard is built from its output, the skip happens when
  it returns exactly one protocol, and the final gate runs the same
  check, so a flow that reuses the sequence cannot ask an Android user
  to choose L2TP.
- `app/services/handover.py` (new) contains the sequence's logic:
  - `load_handover_account(session, source, ref, telegram_id)` resolves
    what to deliver: username, password, plan, data cap and headline.
    `source` is `t` (trial, `ref` = `vpn_users.id`) or `p` (paid order,
    `ref` = `payments.id`). Ownership is checked: the row must belong to
    the tapping user, and a payment must be `paid`. The password is
    never carried in callback data. A purchase reads it from its
    payment, while a renewal or a trial reads it back from IBSng, and an
    unreadable password degrades to the no-password text as before.
  - `deliver_handover(...)` covers steps 3-5: the compatibility gate,
    the credentials, `deliver_device_setup`, and the closing pair.
- `app/bot/handlers/handover.py` (new, thin) handles the `ho:*`
  callbacks for every source:
  - `ho:<src>:<ref>:os:<platform>`: step 2, or a direct step 3 when
    only one protocol is left.
  - `ho:<src>:<ref>:pr:<platform>:<protocol>`: step 3 onward.
  - `ho:<src>:<ref>:back`: from the protocol step back to the device
    step.
- `app/bot/keyboards/handover.py` (new) holds the two pickers.
- **Trial**: `trial:confirm` still creates the account, then shows the
  device picker (`ho:t:<vpn_user_id>:…`) in place, with Back to the main
  menu as before. Its credential and setup code moves into the shared
  service.
- **Purchase / renewal**: `confirmation.py` no longer sends credentials
  and `send_openvpn_setup`. It sends one message instead: "payment
  received, your service is active", followed by the device picker
  (`ho:p:<payment_id>:…`). The adminlog entry is unchanged and still
  fires at activation.
- `delivery.py` drops the Tutorial-section paragraph and the keyboard for
  every kind, because the pair now always ends the sequence. The
  `delivery_tutorial_note` key is deleted.

## 3. Decisions

- **Paid credentials timing:** superseded by §5. Paid credentials are
  sent at payment time, before the pickers.
- **No Back-to-menu button on the paid device picker.** It is a message
  the bot sends, not a screen the customer navigated to. The main-menu
  handler edits the message it was tapped on, so that tap would replace
  the only route to the credentials. The protocol step still has Back,
  which returns to the device step. The trial keeps its existing
  main-menu Back on the device step.
- **Double taps.** The protocol picker, or the device picker on
  Android's skip path, has its keyboard removed before anything is
  sent. A "not modified" refusal means another tap won, and this tap
  stops. This is the trial's existing guard, now shared.
- **Old buttons in chat history.** `trial:os:<p>:<d>` and
  `trial:platform:<d>` still deliver through the shared path.
  `trial:protocol:<p>` and `trial:back_to_protocol` open the new device
  picker. An old paid delivery message needs no alias, because its
  buttons were `menu:*` and `ovpn:link:*`, and both still work.
- **My Services "resend" is out of scope.** It is not an account handover
  (it sends no credentials) and keeps `send_openvpn_setup` and its
  `ovpn:link:*` picker.

## 4. Tests

- Trial: confirm shows the device picker first. A non-Android device
  shows only its valid protocols. Android skips straight to credentials
  over OpenVPN. The full sequence order is credentials → config → one
  link → pair. Android+L2TP from a forged or old callback is refused
  before credentials go out. The picker is disarmed. Legacy callbacks
  still work.
- Purchase and renewal via the real webhook: only the prompt is sent at
  payment time (no credentials, no `ovpn:link` picker, no store URLs).
  After that the same `ho:*` taps give the same sequence, with the
  purchase or renewal headline. Android skips protocol. Another user
  cannot claim someone else's payment, and an unpaid payment cannot be
  claimed.
- Shared path: trial and paid both go through
  `app.services.handover.deliver_handover`, asserted by patching it.
- `protocols_for_platform` unit cases.

## 5. Amendment (2026-09-25): paid credentials go out first

Review feedback: a paying customer must not depend on a tap to see their
username and password. Paid orders therefore send the credentials
message (the shared template) the moment the payment is activated, then
the device picker. The taps lead to the protocol step (or skip it on
Android) and then to the setup material and the closing pair only; the
credentials are never resent. When a device has no setup material, the
pair goes on the tapped picker. `HandoverAccount.credentials_sent_up_front`
is the one switch (true for the paid source). The trial keeps the order
in §1. The "payment received" prompt key is removed; the picker uses
the existing `platform_prompt`, because the credentials above it already
confirm the order.
