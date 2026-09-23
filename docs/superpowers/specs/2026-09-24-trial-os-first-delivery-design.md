# Trial Delivery: Device First, Then Credentials — Design Spec

Date: 2026-09-24
Status: approved (requested directly)
Related: `2026-09-23-shared-delivery-message-design.md`,
`2026-09-23-openvpn-setup-step-design.md`.

## 1. Summary

The trial currently asks for a protocol, then (L2TP only) a device, and
sends credentials with a Tutorial button and a "see the Tutorial
section" paragraph, followed by setup material; OpenVPN never asks for a
device up front and ends on a platform picker. The new sequence is strict
and the same for both protocols:

1. Confirm trial (unchanged; the account is created here).
2. Pick protocol (unchanged screen).
3. **Pick device** (iOS / Android / Windows / macOS), for every protocol.
   The picker edits the protocol message in place, as the protocol step
   already edits the confirm message; Back returns to the protocol.
4. Credentials message: tap-to-copy username/password, **without** the
   Tutorial-section paragraph and **without** any buttons.
5. The chosen device's setup material only, never asking for the device
   again: OpenVPN sends the profile then that device's app link; L2TP
   sends that device's guide then its link (what `deliver_setup` sends
   for L2TP today).
6. The Tutorial / Back to Main Menu pair, attached to the last message
   of the sequence.

Each of steps 4-5 is its own message; nothing is merged.

## 2. Decisions

- **Scope of the paragraph and button removal: trial only.** The shared
  body keys lose the paragraph, which moves to its own key
  `delivery_tutorial_note`; `build_delivery_text` appends it for
  purchase and renewal, not trial. Purchase and renewal text renders
  byte-identically to today. `send_account_delivery` omits the keyboard
  for the trial only, and returns the sent message id.
- **Where the final pair goes.** The last message varies (no link for a
  device with a built-in L2TP client, no profile uploaded, and so on), so
  the trial attaches the pair to whichever message was sent last by
  editing its reply markup. If no setup material was sent, it attaches
  to the credentials message, so the pair is never missing.
  `send_profile` and `send_download_links` return the sent message id
  instead of `True` (still falsy when nothing was sent, so every existing
  caller is unaffected).
- **One composition, same senders.** `deliver_device_setup` in
  `tutorial_delivery.py` composes the existing `send_profile`,
  `send_guide` and `send_download_links`: the same functions the OpenVPN
  setup step's picker and `deliver_setup` use, now called once the device
  is already known. No OpenVPN guide is looked up, matching the setup
  step's rule.
- **Android + L2TP** is refused before credentials go out, with the
  existing `android_l2tp_unsupported` message; the device picker stays
  so the customer can go Back and choose OpenVPN.
- **Double taps.** The device picker's keyboard is removed once a device
  is accepted, so the sequence cannot be sent twice from one picker.
- **Old buttons.** `trial:platform:<id>` (L2TP-only, from the previous
  flow) still works from a message in chat history, routed into the same
  path with L2TP.
- Purchase, renewal and My Services keep `send_openvpn_setup` and its
  picker unchanged.

## 3. Tests

Device picker for both protocols; nothing sent before a device is
chosen; credentials without the paragraph or a keyboard; OpenVPN sends
the profile and only the chosen device's link, with no platform picker;
the pair lands on the final message; the Android+L2TP refusal sends no
credentials; the picker keyboard is removed; the legacy callback still
delivers; purchase/renewal keep the paragraph and buttons.
