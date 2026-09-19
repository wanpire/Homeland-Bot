# Ad Campaign Broadcast — Design Spec

Date: 2026-09-19
Status: approved (design reviewed in chat)
Related: `docs/superpowers/specs/2026-09-15-admin-panel-design.md` (the
existing Broadcast flow this builds on).

## 1. Summary

Split the admin panel's "📢 Broadcast" entry into a two-option submenu:

- **📣 Announcement** — the existing broadcast flow, functionally
  unchanged (text / photo / document to every bot user, no button).
- **🎯 Ad Campaign** — new: a photo (optional caption) or plain-text
  message with an optional single inline button underneath, sent to the
  same recipient list through the same sending pipeline.

The campaign button can be:

1. the preset **🔑 Buy Subscription** button (lands on `menu:buy`, the
   same destination as the main menu's own button, in each recipient's
   language);
2. any other real main-menu section — Renew, Free Trial, My Services,
   Support — again rendered in the recipient's language and using the
   exact main-menu callback data;
3. a fully custom button: admin-supplied label (used verbatim for
   every recipient) plus a destination that is either one of the five
   bot sections above or an external URL;
4. no button at all.

Admin-facing copy is English-only, per CLAUDE.md. The two submenu
labels in the originating request were Persian (AloBot wording); the
user chose English for Homeland.

Tutorials and Language are deliberately not offered as destinations:
Tutorials is still a coming-soon placeholder alert and Language is not a
campaign target.

## 2. Shared sending pipeline (`app/services/broadcast.py`, new)

The recipient query, send loop, background-task bookkeeping and summary
DM move out of `app/bot/handlers/broadcast.py` into a service module so
both flows share one implementation:

```python
Content = dict[str, Any]   # {"kind": "text", "text": html} |
                           # {"kind": "photo", "file_id", "caption": html} |
                           # {"kind": "document", "file_id", "caption": html}
KeyboardFor = Callable[[str], InlineKeyboardMarkup | None]  # lang -> markup

async def list_recipients(session, *, exclude_telegram_id) -> list[tuple[int, str]]
    # (telegram_id, lang) for every unblocked BotUser except the admin;
    # lang = BotUser.language or DEFAULT_LANG ("en"), the same fallback
    # app/services/reminders.py uses.

async def run_broadcast(bot, admin_telegram_id, content, *,
                        keyboard_for: KeyboardFor | None = None,
                        summary_label: str = "Broadcast") -> None
    # Same loop as today: 0.05 s between sends, TelegramAPIError counted
    # as failed, then "✅ {summary_label} done — sent: X, failed: Y." to
    # the admin. reply_markup=keyboard_for(lang) when provided.

def start_broadcast_task(bot, admin_telegram_id, content, *, keyboard_for=None,
                         summary_label="Broadcast") -> asyncio.Task[None]
    # asyncio.create_task + the strong-reference set (moved here).
```

`list_recipients` keeps the existing docstring's two rules: the admin
running the send is excluded, blocked users are excluded.

## 3. Callback-data map (all under `adm:broadcast`, router gated `IsFullAdmin`)

| callback data | screen |
|---|---|
| `adm:broadcast` | submenu: 📣 Announcement / 🎯 Ad Campaign / ⬅️ Back to Admin Panel |
| `adm:broadcast:announce` | existing compose prompt (was `adm:broadcast`) |
| `adm:broadcast:confirm` | existing announcement confirm (unchanged) |
| `adm:broadcast:cancel` | existing cancel → admin root (unchanged, reused by campaign) |
| `adm:broadcast:campaign` | campaign content prompt |
| `adm:broadcast:campaign:btn` | button-choice screen (also the Back target from later steps) |
| `adm:broadcast:campaign:btn:preset` | choose 🔑 Buy Subscription → preview |
| `adm:broadcast:campaign:btn:menu` | list the other four sections |
| `adm:broadcast:campaign:btn:menu:<key>` | choose section `<key>` → preview |
| `adm:broadcast:campaign:btn:custom` | ask for the custom label |
| `adm:broadcast:campaign:btn:none` | no button → preview |
| `adm:broadcast:campaign:dest:<key>` | custom destination = section `<key>` → preview |
| `adm:broadcast:campaign:dest:url` | ask for the URL |
| `adm:broadcast:campaign:confirm` | send |

`<key>` ∈ `buy | renew | trial | myservices | support`, mapping to
callback `menu:<key>` and label `t("menu_<key>", lang)`. Defined once as
`CAMPAIGN_SECTIONS` in `app/bot/keyboards/campaign.py`.

## 4. Campaign FSM (`app/bot/states/campaign.py`)

```python
class CampaignStates(StatesGroup):
    content = State()        # waiting for photo/text
    button_choice = State()  # button-choice screen showing
    custom_label = State()   # waiting for label text
    custom_dest = State()    # destination chooser showing
    custom_url = State()     # waiting for URL text
    confirm = State()        # preview sent, awaiting Send/Cancel
```

FSM data: `content` (same shape as announcement, `document` rejected
with "⚠️ Send a photo or text." and the prompt re-shown) and `button`:

```python
None                                                   # no button
{"kind": "menu", "key": "buy"}                         # preset / reused section
{"kind": "custom", "label": str, "dest": {"kind": "menu", "key": str}}
{"kind": "custom", "label": str, "dest": {"kind": "url", "url": str}}
```

Validation:
- custom label: stripped, 1–64 characters, else "⚠️ Label must be 1–64 characters." and stay in state.
- URL: stripped, must start with `http://`, `https://` or `tg://`, no
  whitespace, ≤ 1024 characters; else "⚠️ Send a valid http(s):// or tg:// URL." and stay in state.

Every screen has a Back (to the previous step) or Cancel (to admin
root) button; every Back/Cancel handler calls `state.clear()` or resets
to the previous state as appropriate.

## 5. Preview + confirm

On reaching `confirm`, the handler:
1. sends the admin the real campaign message (photo or text) with the
   real keyboard rendered for the admin's own `lang` — so the admin can
   tap the button and verify navigation before sending;
2. sends "🎯 Campaign preview above. Send it to N user(s)?" with
   ✅ Send / ⬅️ Back (to button choice) / ❌ Cancel.

Confirm calls `start_broadcast_task(..., keyboard_for=lambda lang:
campaign_keyboard(button, lang), summary_label="Campaign")`, clears
state, and edits the prompt to "📤 Campaign started — you'll get a
summary when it's done."

`campaign_keyboard(button, lang)` in `app/bot/keyboards/campaign.py`
returns `None` for no button, otherwise a one-button markup: menu kind
→ `text=t(f"menu_{key}", lang), callback_data=f"menu:{key}"`; custom
kind → `text=label` with either `callback_data=f"menu:{key}"` or
`url=url`.

## 6. Navigation from a photo message (customer side)

Main-menu section entry handlers (`menu:buy`, `menu:renew`,
`menu:trial`, `menu:myservices`, `menu:support`) all do
`callback.message.edit_text(...)`. Telegram rejects that on a photo
message ("there is no text in the message to edit"), so a campaign
photo's button would spin and fail.

Fix: a helper in `app/bot/keyboards/menus.py`:

```python
async def show_screen(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None) -> None:
    """Edit the tapped message in place when it is a text message;
    send a fresh message when it isn't (a campaign photo, whose caption
    is not editable into a menu screen)."""
    if message.text is None:
        await message.answer(text, reply_markup=reply_markup)
    else:
        await message.edit_text(text, reply_markup=reply_markup)
```

Only those five entry handlers switch from `edit_text` to
`show_screen`. Deeper screens keep `edit_text` because they always run
on the fresh text message. A text campaign edits in place, exactly like
the renewal reminder's Renew Now button already does.

## 7. Tests

`tests/functional/test_broadcast.py` — update existing tests for the
new `adm:broadcast:announce` start callback; add a submenu test (both
options + Back present, hidden from non-full admins).

`tests/functional/test_campaign.py` (new), through the real dispatcher
and `fake_session.calls`:
- non-full admin cannot open `adm:broadcast:campaign`;
- document content is rejected, photo and text accepted;
- preset button: recipients get `sendPhoto`/`sendMessage` with a
  keyboard whose single button has `callback_data == "menu:buy"` and
  text in each recipient's language (seed one `fa`, one `en` user);
- reused section (e.g. `renew`): same, `menu:renew`;
- custom button with section destination: label verbatim for every
  recipient, callback `menu:<key>`;
- custom button with URL destination: `url` set, no callback;
- invalid label and invalid URL re-prompt and stay in state;
- no button: `reply_markup` absent;
- preview is sent to the admin before the confirm prompt;
- summary DM says "Campaign done";
- a customer tapping `menu:buy` on a photo message gets a fresh
  `sendMessage` with the buy category heading rather than an
  `editMessageText`;
- every campaign screen offers a Back or Cancel button.

## 8. Rollout

Server (bot.alonet.co) is confirmed test-stage (2 bot users, no
finished payments) — deploy after the suite passes, then send one real
campaign per button mode to the current bot users and tap each button
on both a text and a photo campaign.
