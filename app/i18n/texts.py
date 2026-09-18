from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_LANG = "en"

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        # --- main menu / users.py ---
        "welcome": "👋 Welcome to Homeland VPN.\n\nChoose an option below:",
        "menu_buy": "🔑 Buy Subscription",
        "menu_renew": "♻️ Renew Service",
        "menu_trial": "🎁 Free Trial",
        "menu_myservices": "🛍 My Services",
        "menu_tutorials": "📚 Tutorials",
        "menu_support": "☎️ Support",
        "menu_language": "🌐 Language",
        "placeholder_coming_soon": "🚧 This feature is coming soon.",
        "support_heading": "☎️ <b>Support</b>\n\nTap the button below to contact support.",
        "support_not_configured": "☎️ Support contact isn't configured yet. Please check back soon.",
        "contact_support_button": "☎️ Contact Support",
        "back_to_menu": "⬅️ Back to Menu",
        "language_updated": "✅ Language updated.",

        # --- buy.py / buy keyboard ---
        "buy_category_heading": "🔑 <b>Buy Subscription</b>\n\nPick a category:",
        "buy_pick_plan": "Pick a plan:",
        "category_scroll": "📜 Scroll",
        "category_stream": "🌊 Stream",
        "category_trial": "Trial",
        "plan_gone": "⚠️ That plan no longer exists. Please pick another.",
        "payment_coming_soon": (
            "🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know "
            "the moment they're live. No charge has been made and no account was created."
        ),
        "payment_link_heading": (
            "💳 <b>Complete your payment</b>\n\n"
            "Tap below to open the payment page — you'll be able to choose your "
            "coin and network there. We'll confirm automatically once payment is "
            "received; no need to come back and check."
        ),
        "payment_unavailable": (
            "⚠️ We couldn't reach the payment provider right now. Please try again "
            "in a few minutes, or contact support if this keeps happening."
        ),
        "pay_with_crypto_button": "₿ Pay with Crypto",
        "open_payment_page_button": "🔗 Open Payment Page",
        "back_button": "⬅️ Back",
        "price_duration": "Duration: {days} days",
        "price_data": "Data: {cap}",
        "price_line": "Price: {price}",
        "price_line_discounted": "Price: <s>{original}</s> {discounted} (-{percent}%)",

        # --- renew.py / renew keyboard ---
        "renew_list_heading": "♻️ <b>Renew Service</b>\n\nWhich service do you want to renew?",
        "renew_empty": "♻️ <b>Renew Service</b>\n\nYou don't have any services to renew yet.",
        "renew_not_found": "⚠️ Service not found.",
        "renew_pick_category": "♻️ <b>Renew {name}</b>\n\nPick a category:",
        "renew_pick_plan": "♻️ <b>Renew {name}</b>\n\nPick a plan:",
        "renew_summary_heading": "♻️ <b>Renew {current} → {new} ({category})</b>",
        "payment_coming_soon_renew": (
            "🚧 Payment methods (Stripe, crypto) are coming soon — we'll let you know "
            "the moment they're live. No charge has been made and your service has not "
            "been changed."
        ),

        # --- myservices.py / myservices keyboard ---
        "myservices_heading": "🛍 <b>My Services</b>",
        "myservices_empty": "🛍 <b>My Services</b>\n\nYou don't have any services yet.",
        "myservices_not_found": "⚠️ Service not found.",
        "status_active": "✅ Active",
        "status_expired": "⛔ Expired",
        "status_pending": "⏳ Pending",
        "status_unknown": "⚠️ Unknown",
        "status_line_active": "Status: ✅ Active until {date} UTC",
        "status_line_expired": "Status: ⛔ Expired on {date} UTC",
        "status_line_pending": "Status: ⏳ Not yet activated — validity starts on first connection.",
        "status_line_unknown": "Status: ⚠️ Couldn't check status right now.",
        "password_unavailable": "Password: unavailable — contact support",
        "protocol_prompt": "🔌 Which protocol do you want to use?",
        "platform_prompt": "📱 Which device do you want to set it up on?",
        "resent_confirmation": "✅ Sent — check the message above.",
        "resend_blocked": "⚠️ See the message above for details.",
        "resend_setup_button": "🔄 Resend Setup",
        "back_to_list_button": "⬅️ Back to List",
        "back_to_service_button": "⬅️ Back to Service",

        # --- trial.py / trial keyboard ---
        "trial_already_used": "🎁 You've already used your free trial.",
        "trial_confirm_prompt": "🎁 <b>Free Trial</b> — 24 hours, 1GB of data.\n\nStart your trial?",
        "trial_create_failed": "⚠️ Couldn't create your trial right now. Please try again shortly.",
        "trial_credentials_unavailable": (
            "⚠️ Your trial account was created, but we couldn't retrieve your "
            "credentials right now. Please contact support and they'll send them to you."
        ),
        "trial_ready": (
            "🎁 <b>Your trial is ready.</b>\n\n"
            "Username: <code>{username}</code>\n"
            "Password: <code>{password}</code>\n\n"
            "⏱ Valid for 24 hours from first connection."
        ),
        "confirm_button": "✅ Confirm",

        # --- tutorial_delivery.py ---
        "android_l2tp_unsupported": (
            "⚠️ L2TP isn't supported on Android 12 and newer (Google removed the "
            "built-in L2TP/IPsec client). Please use OpenVPN instead, or contact "
            "support for help."
        ),
        "guide_not_ready": "📚 This guide is not ready yet — please contact support.",
        "connection_profile_prefix": "📡 Connection profile ({name})",
        "download_link_prefix": "📥 App download link:",
        "download_openvpn_links_heading": "📥 Download OpenVPN Connect:",
        "any_platform_label": "Any platform:",

        # --- webhook.py ---
        "payment_confirmed": "🎉 Payment confirmed! Your service (<code>{username}</code>) has been {action}.",
        "action_activated": "activated",
        "action_renewed": "renewed",
        "partial_payment": (
            "⚠️ We received a partial payment — it wasn't quite enough to complete your order, "
            "so your service hasn't been activated yet. Tap below to finish paying the remaining "
            "balance; the page will show exactly how much is left."
        ),
        "payment_failed": (
            "❌ This payment did not complete. You can start over any time from "
            "Buy Subscription or Renew Service."
        ),
        "activation_technical_issue": (
            "⚠️ Your payment was received, but we hit a technical issue activating your "
            "service. Please contact support with your payment date and amount."
        ),
        "finish_payment_button": "💰 Finish Payment",

        # --- error_handlers.py ---
        "pool_busy": "⏳ The server is temporarily busy. Please try again shortly.",

        # --- reminders.py ---
        "reminder_message": (
            "⏰ Your VPN service (<code>{username}</code>) expires in less than "
            "{days} day(s). Renew now to avoid interruption."
        ),
        "renew_now_button": "♻️ Renew Now",

        # --- plan display names (catalog.py) ---
        "plan_name_trial": "Trial",
        "plan_name_2weeks": "2 Weeks",
        "plan_name_1month": "1 Month",
        "plan_name_2months": "2 Months",
        "plan_name_3months": "3 Months",
    },
    "fa": {
        "welcome": "👋 به Homeland VPN خوش آمدید.\n\nیکی از گزینه‌های زیر را انتخاب کنید:",
        "menu_buy": "🔑 خرید اشتراک",
        "menu_renew": "♻️ تمدید سرویس",
        "menu_trial": "🎁 تست رایگان",
        "menu_myservices": "🛍 سرویس‌های من",
        "menu_tutorials": "📚 آموزش‌ها",
        "menu_support": "☎️ پشتیبانی",
        "menu_language": "🌐 زبان",
        "placeholder_coming_soon": "🚧 این قابلیت به‌زودی اضافه می‌شود.",
        "support_heading": "☎️ <b>پشتیبانی</b>\n\nبرای تماس با پشتیبانی روی دکمه زیر بزنید.",
        "support_not_configured": "☎️ اطلاعات تماس پشتیبانی هنوز تنظیم نشده. لطفاً بعداً دوباره سر بزنید.",
        "contact_support_button": "☎️ تماس با پشتیبانی",
        "back_to_menu": "⬅️ بازگشت به منو",
        "language_updated": "✅ زبان با موفقیت تغییر کرد.",

        "buy_category_heading": "🔑 <b>خرید اشتراک</b>\n\nیک دسته را انتخاب کنید:",
        "buy_pick_plan": "یک پلن را انتخاب کنید:",
        "category_scroll": "📜 اسکرول",
        "category_stream": "🌊 استریم",
        "category_trial": "تست رایگان",
        "plan_gone": "⚠️ این پلن دیگر وجود ندارد. لطفاً پلن دیگری انتخاب کنید.",
        "payment_coming_soon": (
            "🚧 روش‌های پرداخت (استرایپ، ارز دیجیتال) به‌زودی فعال می‌شوند — به محض "
            "فعال شدن به شما اطلاع می‌دهیم. هیچ مبلغی کسر نشده و حسابی ساخته نشده است."
        ),
        "payment_link_heading": (
            "💳 <b>تکمیل پرداخت</b>\n\n"
            "برای باز کردن صفحه پرداخت روی دکمه زیر بزنید — می‌توانید ارز و شبکه دلخواه "
            "خود را همان‌جا انتخاب کنید. پس از دریافت پرداخت به‌صورت خودکار تأیید می‌شود؛ "
            "نیازی به بازگشت و بررسی دستی نیست."
        ),
        "payment_unavailable": (
            "⚠️ در حال حاضر امکان اتصال به درگاه پرداخت وجود ندارد. لطفاً چند دقیقه دیگر "
            "دوباره امتحان کنید یا در صورت تکرار با پشتیبانی تماس بگیرید."
        ),
        "pay_with_crypto_button": "₿ پرداخت با ارز دیجیتال",
        "open_payment_page_button": "🔗 باز کردن صفحه پرداخت",
        "back_button": "⬅️ بازگشت",
        "price_duration": "مدت: {days} روز",
        "price_data": "حجم: {cap}",
        "price_line": "قیمت: {price}",
        "price_line_discounted": "قیمت: <s>{original}</s> {discounted} (-{percent}٪)",

        "renew_list_heading": "♻️ <b>تمدید سرویس</b>\n\nکدام سرویس را می‌خواهید تمدید کنید؟",
        "renew_empty": "♻️ <b>تمدید سرویس</b>\n\nهنوز سرویسی برای تمدید ندارید.",
        "renew_not_found": "⚠️ سرویس یافت نشد.",
        "renew_pick_category": "♻️ <b>تمدید {name}</b>\n\nیک دسته را انتخاب کنید:",
        "renew_pick_plan": "♻️ <b>تمدید {name}</b>\n\nیک پلن را انتخاب کنید:",
        "renew_summary_heading": "♻️ <b>تمدید {current} → {new} ({category})</b>",
        "payment_coming_soon_renew": (
            "🚧 روش‌های پرداخت (استرایپ، ارز دیجیتال) به‌زودی فعال می‌شوند — به محض فعال "
            "شدن به شما اطلاع می‌دهیم. هیچ مبلغی کسر نشده و سرویس شما تغییری نکرده است."
        ),

        "myservices_heading": "🛍 <b>سرویس‌های من</b>",
        "myservices_empty": "🛍 <b>سرویس‌های من</b>\n\nهنوز سرویسی ندارید.",
        "myservices_not_found": "⚠️ سرویس یافت نشد.",
        "status_active": "✅ فعال",
        "status_expired": "⛔ منقضی‌شده",
        "status_pending": "⏳ در انتظار",
        "status_unknown": "⚠️ نامشخص",
        "status_line_active": "وضعیت: ✅ فعال تا {date} UTC",
        "status_line_expired": "وضعیت: ⛔ منقضی‌شده در {date} UTC",
        "status_line_pending": "وضعیت: ⏳ هنوز فعال نشده — اعتبار از اولین اتصال شروع می‌شود.",
        "status_line_unknown": "وضعیت: ⚠️ در حال حاضر امکان بررسی وضعیت وجود ندارد.",
        "password_unavailable": "رمز عبور: در دسترس نیست — با پشتیبانی تماس بگیرید",
        "protocol_prompt": "🔌 کدام پروتکل را می‌خواهید استفاده کنید؟",
        "platform_prompt": "📱 روی کدام دستگاه می‌خواهید تنظیم کنید؟",
        "resent_confirmation": "✅ ارسال شد — پیام بالا را بررسی کنید.",
        "resend_blocked": "⚠️ برای جزئیات پیام بالا را بررسی کنید.",
        "resend_setup_button": "🔄 ارسال مجدد تنظیمات",
        "back_to_list_button": "⬅️ بازگشت به لیست",
        "back_to_service_button": "⬅️ بازگشت به سرویس",

        "trial_already_used": "🎁 شما قبلاً از تست رایگان خود استفاده کرده‌اید.",
        "trial_confirm_prompt": "🎁 <b>تست رایگان</b> — ۲۴ ساعت، ۱ گیگابایت حجم.\n\nتست رایگان را شروع می‌کنید؟",
        "trial_create_failed": "⚠️ در حال حاضر امکان ایجاد تست رایگان وجود ندارد. لطفاً کمی بعد دوباره امتحان کنید.",
        "trial_credentials_unavailable": (
            "⚠️ حساب تست رایگان شما ساخته شد، اما در حال حاضر امکان دریافت اطلاعات ورود "
            "وجود ندارد. با پشتیبانی تماس بگیرید تا برایتان ارسال شود."
        ),
        "trial_ready": (
            "🎁 <b>تست رایگان شما آماده است.</b>\n\n"
            "نام کاربری: <code>{username}</code>\n"
            "رمز عبور: <code>{password}</code>\n\n"
            "⏱ به مدت ۲۴ ساعت از اولین اتصال معتبر است."
        ),
        "confirm_button": "✅ تأیید",

        "android_l2tp_unsupported": (
            "⚠️ پروتکل L2TP روی اندروید ۱۲ به بعد پشتیبانی نمی‌شود (گوگل کلاینت داخلی "
            "L2TP/IPsec را حذف کرده است). لطفاً از OpenVPN استفاده کنید یا برای راهنمایی "
            "با پشتیبانی تماس بگیرید."
        ),
        "guide_not_ready": "📚 این راهنما هنوز آماده نیست — لطفاً با پشتیبانی تماس بگیرید.",
        "connection_profile_prefix": "📡 پروفایل اتصال ({name})",
        "download_link_prefix": "📥 لینک دانلود اپلیکیشن:",
        "download_openvpn_links_heading": "📥 دانلود OpenVPN Connect:",
        "any_platform_label": "همه دستگاه‌ها:",

        "payment_confirmed": "🎉 پرداخت تأیید شد! سرویس شما (<code>{username}</code>) {action} شد.",
        "action_activated": "فعال",
        "action_renewed": "تمدید",
        "partial_payment": (
            "⚠️ پرداخت جزئی دریافت شد — مبلغ کافی برای تکمیل سفارش نبود، بنابراین سرویس "
            "شما هنوز فعال نشده است. برای تکمیل باقی‌مانده مبلغ روی دکمه زیر بزنید؛ صفحه "
            "پرداخت مبلغ دقیق باقی‌مانده را نشان می‌دهد."
        ),
        "payment_failed": (
            "❌ این پرداخت تکمیل نشد. می‌توانید هر زمان از «خرید اشتراک» یا «تمدید سرویس» "
            "دوباره شروع کنید."
        ),
        "activation_technical_issue": (
            "⚠️ پرداخت شما دریافت شد، اما در فعال‌سازی سرویس با یک مشکل فنی مواجه شدیم. "
            "لطفاً همراه با تاریخ و مبلغ پرداخت با پشتیبانی تماس بگیرید."
        ),
        "finish_payment_button": "💰 تکمیل پرداخت",

        "pool_busy": "⏳ سرور موقتاً شلوغ است. لطفاً کمی بعد دوباره امتحان کنید.",

        "reminder_message": (
            "⏰ اعتبار سرویس شما (<code>{username}</code>) کمتر از {days} روز دیگر تمام "
            "می‌شود. برای جلوگیری از قطعی همین حالا تمدید کنید."
        ),
        "renew_now_button": "♻️ تمدید کنید",

        "plan_name_trial": "تست رایگان",
        "plan_name_2weeks": "۲ هفته",
        "plan_name_1month": "۱ ماه",
        "plan_name_2months": "۲ ماه",
        "plan_name_3months": "۳ ماه",
    },
}

CHOOSE_LANGUAGE_TEXT = (
    "🇮🇷 فارسی / 🇬🇧 English\n\n"
    "لطفاً زبان خود را انتخاب کنید:\n"
    "Please choose your language:"
)


def t(key: str, lang: str, **kwargs: object) -> str:
    """Never raises - a missing key or a missing language falls back to
    English (logged as a warning), and a key missing from English too
    returns the bare key itself so a broken lookup is visible in the
    chat rather than crashing the handler."""
    lang_is_recognized = lang in TEXTS
    lang_dict = TEXTS.get(lang, TEXTS[DEFAULT_LANG])
    template = lang_dict.get(key)
    if template is None:
        if lang != DEFAULT_LANG:
            logger.warning("Missing i18n key %r for lang=%r, falling back to %r", key, lang, DEFAULT_LANG)
        template = TEXTS[DEFAULT_LANG].get(key)
    elif not lang_is_recognized:
        # Language not recognized but key exists in fallback English - still log the missing language
        logger.warning("Missing i18n language %r, falling back to %r", lang, DEFAULT_LANG)
    if template is None:
        logger.warning("Missing i18n key %r in every language", key)
        return key
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        logger.warning("i18n key %r formatting failed with kwargs=%r", key, kwargs)
        return template
