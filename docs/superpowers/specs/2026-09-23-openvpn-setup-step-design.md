# Post-Delivery OpenVPN Setup Step — Design Spec

Date: 2026-09-23
Status: approved (design reviewed in chat)
Related: `docs/superpowers/specs/2026-09-23-shared-delivery-message-design.md`
(the credentials message this step follows).

## 1. Summary

After an account is handed over, the bot sends the OpenVPN config and
then dumps every platform's download link in one message, followed by a
"this guide is not ready" placeholder. This replaces that with: the
config, then four platform buttons, then only the link for whichever
platform the customer taps.

Two findings from investigation changed the shape of the request:

**Only the trial sends this material today.** `deliver_setup` is called
from `app/bot/handlers/trial.py` and `app/bot/handlers/myservices.py`
only. A purchase or renewal sends the credentials message and nothing
else, so there was no all-links dump in the paid flows to fix. Confirmed
in review: the paid flows should gain the same step, so all three behave
alike.

**The placeholder is a real content gap, not a stray string.**
`send_guide` sends `guide_not_ready` when its lookup finds no row, and
no OpenVPN guide has ever been uploaded — verified against production on
2026-09-22, which reported `OpenVPN (shared): guide=False`. Deleting the
string would have hidden a legitimate "nothing to show" branch that the
Tutorials section still needs.

## 2. What the step sends

In order:

1. The `.ovpn` profile, through the existing `send_profile`. Generation
   and naming are untouched.
2. One message: `t("openvpn_pick_platform", lang)` with four buttons,
   one per active platform, callback `ovpn:link:<platform_id>`, plus a
   Tutorials button for anyone wanting the full guide.

On a tap, only that platform's link is sent, resolved through the
existing `resolve_download_link` (platform-specific, falling back to the
admin's "Generic (any platform)" entry). The keyboard stays in place, so
a customer with two devices can take both links.

No guide is looked up here, so `guide_not_ready` can no longer fire in a
delivery flow. It remains in the Tutorials section, where a customer has
explicitly asked for a guide and "not ready" is the honest answer.

## 3. Where it lives

One function, `app/services/openvpn_setup.py`:

```python
async def send_openvpn_setup(bot: Bot, telegram_id: int, session: AsyncSession, *, lang: str) -> None
```

and one router, `app/bot/handlers/openvpn_setup.py`, owning the
`ovpn:*` callback root. Every flow calls the same function; none of them
builds this material itself.

Callers:

| flow | where |
|---|---|
| purchase, renewal | `app/services/payments/confirmation.py`, right after the credentials message |
| trial | `app/bot/handlers/trial.py`'s OpenVPN branch, replacing its `deliver_setup(..., platform_id=None)` call |
| My Services resend | `app/bot/handlers/myservices.py`'s OpenVPN branch, same replacement |

The L2TP branches keep calling `deliver_setup` with a chosen platform:
that path already sends one platform's material and is not what the
report was about.

## 4. `deliver_setup` stops emitting the placeholder

`send_guide` gains `notify_if_missing: bool = True`. `deliver_setup`
passes `False`, so a missing guide in a delivery flow is silent rather
than apologetic; Tutorials keeps the default and still tells the
customer when a guide is genuinely absent.

`deliver_setup`'s no-platform branch — the one that listed every
platform's link — becomes unreachable from the delivery flows once they
call `send_openvpn_setup`. It stays in `send_download_links` because
Tutorials still uses it for a shared OpenVPN guide, and removing it
would be an unrelated change.

## 5. Copy (fa/en, via `t()`)

- `openvpn_pick_platform`: "📥 <b>Download OpenVPN Connect</b>\n\nPick
  your device and we'll send the download link." / "📥 <b>دانلود
  OpenVPN Connect</b>\n\nدستگاه خود را انتخاب کنید تا لینک دانلود
  برایتان ارسال شود."
- `openvpn_link_unavailable`: shown as an alert when a platform has no
  link configured.

Platform names are the catalog's own labels (iOS, Android, Windows,
macOS) and are not translated. The existing `download_link_prefix` and
`tutorial_button` keys are reused.

## 6. Tests

- Each of the four platforms sends exactly one link, and not the others.
- The profile is sent before the platform prompt.
- `guide_not_ready` never appears in any of the three delivery flows.
- Tutorials still says "not ready" when a guide is genuinely missing.
- A platform with no link answers with the alert rather than an empty
  message.
- All three flows reach the same prompt, asserted per flow.
