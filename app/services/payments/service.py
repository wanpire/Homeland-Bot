from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.discount_code import DiscountCode
from app.db.models.payment import Payment
from app.db.models.plan import Plan
from app.db.models.vpn_user import VPNUser
from app.services.discounts import discount_price, find_best_auto_discount, increment_discount_usage
from app.services.ibsng.client import IBSngClient
from app.services.payments.base import PaymentProvider
from app.services.payments.crypto_provider import CryptoProvider
from app.services.vpn_users import create_vpn_user, generate_vpn_credentials, renew_and_change_group

_provider: PaymentProvider = CryptoProvider()


async def quote_amount(session: AsyncSession, plan: Plan) -> tuple[Decimal, DiscountCode | None]:
    """The exact USD amount a buyer would pay for this plan right now,
    auto-discounts included. The price summary the buyer sees and the
    invoice they are sent to must both come from this one function, so
    the quoted price and the charged price can never disagree."""
    discount: DiscountCode | None = await find_best_auto_discount(session, plan.id)
    amount = discount_price(plan.price_usd, discount.percent) if discount is not None else plan.price_usd
    return amount, discount


async def create_crypto_payment(
    session: AsyncSession,
    *,
    telegram_id: int,
    purpose: str,  # "purchase" | "renew"
    plan: Plan,
    vpn_user: VPNUser | None,  # required for purpose="renew", None for "purchase"
) -> Payment:
    amount, discount = await quote_amount(session, plan)

    payment = Payment(
        telegram_id=telegram_id,
        purpose=purpose,
        vpn_user_id=vpn_user.id if vpn_user is not None else None,
        plan_id=plan.id,
        discount_code_id=discount.id if discount is not None else None,
        group_name=plan.group_name,
        data_cap_mb=plan.data_cap_mb,
        amount_usd=amount,
        original_amount_usd=plan.price_usd if discount is not None else None,
    )
    if purpose == "purchase":
        payment.ibsng_username, payment.ibsng_password = generate_vpn_credentials()

    # Committed BEFORE calling the provider, deliberately - Plisio's
    # order_number must be a real, permanent local id, which only exists
    # once this row is committed. If create_invoice then fails, this row
    # is left behind as an orphaned "pending, no invoice_url" Payment -
    # accepted as a harmless stale row, same as any other abandoned
    # checkout, rather than risk order_id pointing at a row that later
    # vanished.
    session.add(payment)
    await session.commit()
    await session.refresh(payment)

    invoice_url, provider_payment_id = await _provider.create_invoice(
        order_id=str(payment.id), amount_usd=amount, description=f"Homeland: {plan.name}"
    )
    payment.invoice_url = invoice_url
    payment.provider_payment_id = provider_payment_id
    await session.commit()
    await session.refresh(payment)
    return payment


async def activate_finished_payment(session: AsyncSession, client: IBSngClient, payment: Payment) -> str:
    """Only called once, guarded by the webhook route's idempotency check
    (payment.status == "pending") before this runs. Returns the
    username to show the buyer - either newly created or the existing
    renewed one."""
    if payment.purpose == "purchase":
        vpn_user = await create_vpn_user(
            session, client,
            telegram_id=payment.telegram_id,
            username=payment.ibsng_username,
            password=payment.ibsng_password,
            group_name=payment.group_name,
            data_cap_mb=payment.data_cap_mb,
            plan_id=payment.plan_id,
        )
        payment.vpn_user_id = vpn_user.id
        username = vpn_user.ibsng_username
    else:
        vpn_user = await session.get(VPNUser, payment.vpn_user_id)
        await renew_and_change_group(
            session, client,
            username=vpn_user.ibsng_username,
            new_group_name=payment.group_name,
            new_plan_id=payment.plan_id,
            new_data_cap_mb=payment.data_cap_mb,
        )
        username = vpn_user.ibsng_username

    if payment.discount_code_id is not None:
        await increment_discount_usage(session, payment.discount_code_id)

    return username
