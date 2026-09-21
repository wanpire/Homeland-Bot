"""One renderer for the three payability outcomes, shared by Buy and
Renew so the two flows can never drift apart. Handlers stay thin: they
compute the amount and the report, then hand both to render_payability."""

from __future__ import annotations

from decimal import Decimal

from aiogram.types import CallbackQuery

from app.bot.keyboards.payability import below_minimum_keyboard, pay_currency_keyboard
from app.bot.keyboards.trial import back_to_menu_keyboard
from app.i18n.texts import t
from app.services.catalog import format_price_usd
from app.services.payments.base import PAYABLE, UNAVAILABLE, PayabilityReport


async def render_payability(
    callback: CallbackQuery,
    report: PayabilityReport,
    amount: Decimal,
    lang: str,
    *,
    pay_prefix: str,
    back_to_summary_cb: str,
    back_to_plans_cb: str,
    notice: str | None = None,
) -> None:
    """Renders the coin chooser, the below-minimum message, or the
    provider-unavailable message. `notice` prefixes the chooser when the
    buyer is being sent back to it after their chosen coin stopped being
    payable."""
    if callback.message is None:
        return

    if report.status == PAYABLE:
        text = t("choose_pay_currency", lang, price=format_price_usd(amount))
        if notice:
            text = f"{notice}\n\n{text}"
        await callback.message.edit_text(
            text,
            reply_markup=pay_currency_keyboard(
                report.payable, pay_prefix=pay_prefix, back_cb=back_to_summary_cb, lang=lang
            ),
        )
        return

    if report.status == UNAVAILABLE:
        # We could not reach NOWPayments for at least one coin and none of
        # the coins we did reach can pay. That is an outage, not a pricing
        # problem - telling the buyer their plan is too cheap would be wrong.
        await callback.message.edit_text(t("payment_unavailable", lang), reply_markup=back_to_menu_keyboard(lang))
        return

    minimum = report.lowest_minimum
    await callback.message.edit_text(
        t("payment_below_minimum", lang, min=format_price_usd(minimum) if minimum is not None else "—"),
        reply_markup=below_minimum_keyboard(back_to_plans_cb=back_to_plans_cb, lang=lang),
    )
