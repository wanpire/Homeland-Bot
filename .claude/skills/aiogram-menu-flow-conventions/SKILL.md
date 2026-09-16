---
name: aiogram-menu-flow-conventions
description: Homeland's aiogram menu/flow UX conventions - English-only copy, mandatory Back/Cancel buttons, colon-segmented callback-data namespacing, one-router-per-domain wiring, and FSM state hygiene on navigation. Use when adding or modifying any bot handler, keyboard, or FSM flow under app/bot/.
---

# aiogram Menu/Flow Conventions (Homeland)

Standing UX and architecture rules for every interactive Telegram flow in
this codebase, grounded in the actual keyboards/handlers already built
(`app/bot/keyboards/menus.py`, `trial.py`, `tutorial_admin.py`, `admin.py`;
`app/bot/handlers/*`). Follow these without being re-asked every session.

## English-only copy

Every user-facing AND admin-facing string is English, full stop - no
Persian/Farsi text anywhere in this bot (Homeland sells to Iranian
customers living *abroad*, unlike its sibling project AloBot which is
Persian-language for customers inside Iran - don't port AloBot's Farsi
strings by habit).

## Every interactive flow/menu has a Back or Cancel button

No screen is a dead end. The concrete pattern, taken straight from the
existing keyboards:

```python
# A menu you can freely leave (main_menu, admin_root_menu, etc.)
builder.button(text="⬅️ Back to Menu", callback_data="menu:root")

# A leaf screen one level into a flow
builder.button(text="⬅️ Back", callback_data="<flow>:back_to_<previous_step>")

# An FSM text-input step (nothing to tap otherwise)
builder.button(text="❌ Cancel", callback_data="<flow>:cancel")
```

`tests/functional/test_tutorial_admin_flow.py`'s
`test_every_admin_screen_offers_a_back_button` is the kind of test every
new flow should have: walk every screen the flow can reach and assert a
"back"/"cancel"-labeled button is present. Write one for any new flow you
add.

## Callback-data namespace: colon-segmented, one root per domain

```
menu:*        - main user menu (menu:root, menu:buy, menu:trial, ...)
trial:*       - the free-trial flow (trial:confirm, trial:protocol:<id>, ...)
tutadm:*      - the standalone /admintutorials content-upload flow
adm:*         - the admin panel (adm:root, adm:users:renew, adm:discounts:new, ...)
```

Each root maps to exactly one router, registered once in
`app/main.py`'s `build_dispatcher(storage)` - the single source of truth
for router wiring. Both production (`main()`, `RedisStorage`) and the
test suite (`tests/conftest.py`'s `dispatcher` fixture, `MemoryStorage`)
build the dispatcher through this one function, so they can never drift
apart. **Never wire a router anywhere else.**

New feature = new router + new service method it calls - not a growing
god-file. A router's handlers stay thin: parse the update, call a
service function, render/reply. Business logic belongs in `app/services/`,
never inline in a handler.

## FSM state must be cleared on any navigation-away action

Every Back/Cancel button, and every handler that can be reached mid-flow
from somewhere else, must call `await state.clear()` before rendering the
destination screen. Without this, a stale FSM state can swallow a later
plain-text message the user sends for an unrelated reason - the next
handler that pattern-matches on that leftover state intercepts it instead
of the intended one (e.g. `app/bot/handlers/fallback.py`'s catch-all
explicitly checks `if await state.get_state() is not None: return` -
meaning a stuck state doesn't just misroute one message, it silences the
whole fallback-to-main-menu safety net too).

Concrete pattern from `app/bot/handlers/tutorial_admin.py`'s
`admin_back_to_root_cb` and `app/bot/handlers/admin.py`'s `admin_root_cb`:

```python
@router.callback_query(F.data == "adm:root")
async def admin_root_cb(callback: CallbackQuery, state: FSMContext) -> None:
    # ...permission check first...
    await state.clear()
    if callback.message is not None:
        await callback.message.edit_text(TEXT, reply_markup=KEYBOARD)
    await callback.answer()
```

## Permission gating pattern

- Support-level and below: inline check at the top of the handler,
  `has_level(session, telegram_id, "support")`, matching
  `tutorial_admin.py`'s `_is_admin` helper - return early (after
  `callback.answer()`) on failure, don't render anything.
- Sales/Full-tier-only routers: an `aiogram.filters.BaseFilter` subclass
  (`IsSalesAdmin`, `IsFullAdmin` in `app/bot/filters/admin.py`) applied at
  the **router level** (`router.callback_query.filter(IsFullAdmin())`),
  when an entire router's handlers require that tier.
- A button that a lower tier shouldn't even see is **hidden from the
  keyboard**, not just filter-gated - a visible-but-nonfunctional button
  gives a user zero feedback when its filter silently doesn't match.

## Test conventions for new flows

- Build updates with `tests/factories.py`'s `make_message_update` /
  `make_callback_update` / `make_photo_message_update`, feed them through
  the real `dispatcher` fixture (`app/main.py`'s actual `build_dispatcher`)
  - never hand-construct a partial Update or call a handler function
    directly.
- Assert against `fake_session.calls` (the in-process fake Telegram
  session) for what was actually sent/edited - real behavior, not mocks.
- Every new interactive flow needs: a permission-denied test, a happy-path
  test, and a Back-button-present test for each screen it adds.
