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
        "support_heading": "☎️ <b>Support</b>\n\nTap the button below to contact support.",
        "support_not_configured": "☎️ Support contact isn't configured yet. Please check back soon.",
        "contact_support_button": "☎️ Contact Support",
        "back_to_menu": "⬅️ Back to Menu",
        "language_updated": "✅ Language updated.",

        # --- buy.py / buy keyboard ---
        "buy_category_heading": "🔑 <b>Buy Subscription</b>\n\nPick a category:",
        "buy_pick_plan": "Pick a plan:",
        # Shown above a category's plan list. Owner-supplied wording in both
        # languages - edit the copy with them, not around them.
        "category_desc_trip": "📌 Ideal for short trips abroad, with full access to Iran's local network.",
        "category_desc_scroll": "Suited for domestic banks, apps, websites and government services.",
        "category_desc_stream": "Suited for all online streaming platforms.",
        "category_scroll": "📜 Scroll",
        "category_stream": "🌊 Stream",
        "category_trial": "Trial",
        "category_trip": "🧳 Trip",
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
        "username_label": "Username",
        "password_label": "Password",
        "password_unavailable": "Password: unavailable — contact support",
        "tutorials_heading": (
            "📚 <b>Tutorials</b>\n\n"
            "Pick the protocol you want to set up — we'll send the guide, the app "
            "download link, and the connection profile where one applies."
        ),
        "tutorials_empty": "📚 Setup guides aren't available yet — please contact support.",
        "tutorials_done": "📚 That's everything for this setup. Need another one?",
        "tutorials_extras_prompt": (
            "📚 Guide sent. Need the app download link or the connection profile too?"
        ),
        "tutorials_item_unavailable": "⚠️ That isn't available yet — please contact support.",
        "download_link_button": "📥 Download Link",
        "openvpn_profile_button": "📄 OpenVPN Profile",
        "tutorials_another_button": "📚 Another guide",
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
        "confirm_button": "✅ Confirm",

        # --- tutorial_delivery.py ---
        "android_l2tp_unsupported": (
            "⚠️ L2TP isn't supported on Android 12 and newer (Google removed the "
            "built-in L2TP/IPsec client). Please use OpenVPN instead, or contact "
            "support for help."
        ),
        "guide_not_ready": "📚 This guide is not ready yet — please contact support.",
        "connection_profile_prefix": "📡 Connection profile ({name})",
        "openvpn_pick_platform": (
            "📥 <b>Download OpenVPN Connect</b>\n\n"
            "Pick your device and we'll send you the download link."
        ),
        "openvpn_link_unavailable": (
            "⚠️ No download link is configured for that device yet — please contact support."
        ),
        "download_link_prefix": "📥 App download link:",
        "download_openvpn_links_heading": "📥 Download OpenVPN Connect:",
        "any_platform_label": "Any platform:",

        # --- webhook.py ---
        "delivery_headline_purchase": "🎉 Your order has been placed successfully.",
        "delivery_headline_renewal": "🎉 Your renewal was successful.",
        "delivery_headline_trial": "🎉 Your trial service is ready.",
        "day_singular": "day",
        "day_plural": "days",
        "delivery_body": (
            "<b>Plan:</b> {plan}\n"
            "<b>Duration:</b> {days} {day_word} from first connection\n"
            "<b>Volume:</b> {volume}\n\n"
            "<b>Username:</b> <code>{username}</code>\n"
            "<b>Password:</b> <code>{password}</code>"
        ),
        "delivery_body_no_password": (
            "<b>Plan:</b> {plan}\n"
            "<b>Duration:</b> {days} {day_word} from first connection\n"
            "<b>Volume:</b> {volume}\n\n"
            "<b>Username:</b> <code>{username}</code>\n"
            "<b>Password:</b> unavailable — please contact support"
        ),
        "tutorial_button": "📘 Tutorial",
        "back_to_main_menu_button": "🔙 Back to Main Menu",
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

        # --- data cap display (catalog.py) ---
        "data_cap_unlimited": "Unlimited",
        # --- My Services: root, account menu, account info ---
        "myservices_root": "🛍️ <b>My Services</b>\n\nChoose an option:",
        "myservices_list_button": "📋 My Accounts",
        "myservices_add_button": "➕ Add New Account",
        "back_to_menu_short": "🔙 Back to Menu",
        "back_plain": "🔙 Back",
        "account_menu_heading": "🛍 <b>{username}</b>{trial}\n\nChoose an option:",
        "account_trial_suffix": " (Trial)",
        "account_info_button": "🗓 View Account Info",
        "account_renew_button": "♻️ Renew or Upgrade",
        "account_password_button": "🔑 Change Password",
        "account_ownership_button": "🔄 Change Ownership",
        "info_status_label": "Status",
        "info_volume_label": "Volume",
        "info_expiry_label": "Expires",
        "info_expiry_value": "{date} UTC",
        "info_expiry_pending": "starts at first connection",
        "info_expiry_unknown": "—",
        "info_password_unavailable": "unavailable — contact support",

        # --- My Services: change password ---
        "pw_confirm": (
            "🔑 A new password will be generated for <code>{username}</code> "
            "(the username stays the same).\nYou can do this once a month. Continue?"
        ),
        "pw_confirm_button": "✅ Yes, generate a new password",
        "pw_cooldown": "⚠️ This account's password was changed recently. You can change it again in {days} day(s).",
        "pw_done": "✅ Your new password is ready.",
        "pw_failed": "⚠️ Couldn't change the password right now. Please try again shortly.",
        "pw_refused_group": "⚠️ This account can't be changed here — please contact support.",

        # --- My Services: change ownership ---
        "xfer_prompt": (
            "🔄 <b>Change Ownership</b>\n\nSend the Telegram @username or numeric ID of the person "
            "who should own <code>{username}</code>.\nThey must have started this bot, and the account "
            "moves only after they accept."
        ),
        "xfer_not_found": (
            "❌ No bot user found with that username or ID — they must have started this bot at least once. "
            "Try again:"
        ),
        "xfer_self": "❌ That's you. Send someone else's username or ID:",
        "xfer_ambiguous": "⚠️ More than one user has had that username. Please send their numeric Telegram ID instead:",
        "xfer_confirm": "⚠️ <code>{username}</code> will be offered to {recipient}.\nIt stays yours until they accept. Send the request?",
        "xfer_send_button": "✅ Send request",
        "xfer_sent": (
            "📨 Request sent to {recipient}. <code>{username}</code> stays yours until they accept; "
            "the request expires in 24 hours."
        ),
        "xfer_cancel_button": "❌ Cancel request",
        "xfer_unreachable": "⚠️ Couldn't reach {recipient} — they may have blocked the bot. The request was cancelled.",
        "xfer_offer": "🔄 {owner} wants to transfer the VPN account <code>{username}</code> ({plan}) to you.\nDo you accept?",
        "xfer_accept_button": "✅ Accept",
        "xfer_decline_button": "❌ Decline",
        "xfer_accepted_recipient": (
            "✅ <code>{username}</code> is now yours — you'll find it in My Services.\n"
            "The previous owner may still know its password; you can change it right away from the account's menu."
        ),
        "xfer_accepted_owner": "✅ {recipient} accepted — <code>{username}</code> has been transferred.",
        "xfer_declined_recipient": "Declined — nothing was transferred.",
        "xfer_declined_owner": "❌ {recipient} declined the transfer of <code>{username}</code>. The account is still yours.",
        "xfer_cancelled_owner": "Request cancelled — <code>{username}</code> stays yours.",
        "xfer_cancelled_recipient": "This transfer request was cancelled by the owner.",
        "xfer_expired": "⌛ This transfer request has expired.",
        "xfer_invalid": "⚠️ This request is no longer valid.",
        "xfer_user_id": "user {telegram_id}",
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
        "support_heading": "☎️ <b>پشتیبانی</b>\n\nبرای تماس با پشتیبانی روی دکمه زیر بزنید.",
        "support_not_configured": "☎️ اطلاعات تماس پشتیبانی هنوز تنظیم نشده. لطفاً بعداً دوباره سر بزنید.",
        "contact_support_button": "☎️ تماس با پشتیبانی",
        "back_to_menu": "⬅️ بازگشت به منو",
        "language_updated": "✅ زبان با موفقیت تغییر کرد.",

        "buy_category_heading": "🔑 <b>خرید اشتراک</b>\n\nیک دسته را انتخاب کنید:",
        "buy_pick_plan": "یک پلن را انتخاب کنید:",
        "category_desc_trip": "📌 مناسب برای سفر کوتاه به خارج از کشور و دسترسی کامل به شبکه داخل ایران",
        "category_desc_scroll": "مناسب برای استفاده از بانک‌ها، اپلیکیشن‌ها و سایت‌های داخلی و دولتی",
        "category_desc_stream": "مناسب برای تمامی پلتفرم‌های پخش آنلاین می‌باشد",
        "category_scroll": "📜 اسکرول",
        "category_stream": "🌊 استریم",
        "category_trial": "تست رایگان",
        "category_trip": "🧳 تریپ",
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
        "username_label": "نام کاربری",
        "password_label": "رمز عبور",
        "password_unavailable": "رمز عبور: در دسترس نیست — با پشتیبانی تماس بگیرید",
        "tutorials_heading": (
            "📚 <b>آموزش‌ها</b>\n\n"
            "پروتکلی که می‌خواهید تنظیم کنید را انتخاب کنید — راهنما، لینک دانلود "
            "اپلیکیشن و در صورت وجود فایل اتصال برایتان ارسال می‌شود."
        ),
        "tutorials_empty": "📚 هنوز راهنمای تنظیمات در دسترس نیست — لطفاً با پشتیبانی تماس بگیرید.",
        "tutorials_done": "📚 این تنظیمات کامل شد. راهنمای دیگری لازم دارید؟",
        "tutorials_extras_prompt": (
            "📚 راهنما ارسال شد. لینک دانلود اپلیکیشن یا فایل اتصال هم لازم دارید؟"
        ),
        "tutorials_item_unavailable": "⚠️ این مورد هنوز در دسترس نیست — لطفاً با پشتیبانی تماس بگیرید.",
        "download_link_button": "📥 لینک دانلود",
        "openvpn_profile_button": "📄 فایل اتصال OpenVPN",
        "tutorials_another_button": "📚 راهنمای دیگر",
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
        "confirm_button": "✅ تأیید",

        "android_l2tp_unsupported": (
            "⚠️ پروتکل L2TP روی اندروید ۱۲ به بعد پشتیبانی نمی‌شود (گوگل کلاینت داخلی "
            "L2TP/IPsec را حذف کرده است). لطفاً از OpenVPN استفاده کنید یا برای راهنمایی "
            "با پشتیبانی تماس بگیرید."
        ),
        "guide_not_ready": "📚 این راهنما هنوز آماده نیست — لطفاً با پشتیبانی تماس بگیرید.",
        "connection_profile_prefix": "📡 پروفایل اتصال ({name})",
        "openvpn_pick_platform": (
            "📥 <b>دانلود OpenVPN Connect</b>\n\n"
            "دستگاه خود را انتخاب کنید تا لینک دانلود برایتان ارسال شود."
        ),
        "openvpn_link_unavailable": (
            "⚠️ برای این دستگاه هنوز لینک دانلودی تنظیم نشده — لطفاً با پشتیبانی تماس بگیرید."
        ),
        "download_link_prefix": "📥 لینک دانلود اپلیکیشن:",
        "download_openvpn_links_heading": "📥 دانلود OpenVPN Connect:",
        "any_platform_label": "همه دستگاه‌ها:",

        "delivery_headline_purchase": "🎉 سفارش شما با موفقیت ثبت شد.",
        "delivery_headline_renewal": "🎉 تمدید شما با موفقیت انجام شد.",
        "delivery_headline_trial": "🎉 سرویس تست شما آماده است.",
        "day_singular": "روز",
        "day_plural": "روز",
        "delivery_body": (
            "<b>پلن خریداری‌شده:</b> {plan}\n"
            "<b>مدت زمان استفاده:</b> {days} {day_word} از زمان اولین اتصال\n"
            "<b>حجم:</b> {volume}\n\n"
            "<b>یوزرنیم:</b> <code>{username}</code>\n"
            "<b>پسورد:</b> <code>{password}</code>"
        ),
        "delivery_body_no_password": (
            "<b>پلن خریداری‌شده:</b> {plan}\n"
            "<b>مدت زمان استفاده:</b> {days} {day_word} از زمان اولین اتصال\n"
            "<b>حجم:</b> {volume}\n\n"
            "<b>یوزرنیم:</b> <code>{username}</code>\n"
            "<b>پسورد:</b> در دسترس نیست — لطفاً با پشتیبانی تماس بگیرید"
        ),
        "tutorial_button": "📘 آموزش",
        "back_to_main_menu_button": "🔙 بازگشت به منوی اصلی",
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
        "data_cap_unlimited": "نامحدود",
        # --- My Services: root, account menu, account info ---
        "myservices_root": "🛍️ <b>سرویس‌های من</b>\n\nیک گزینه را انتخاب کنید:",
        "myservices_list_button": "📋 لیست اکانت‌های من",
        "myservices_add_button": "➕ افزودن اکانت جدید",
        "back_to_menu_short": "🔙 بازگشت به منو",
        "back_plain": "🔙 بازگشت",
        "account_menu_heading": "🛍 <b>{username}</b>{trial}\n\nیک گزینه را انتخاب کنید:",
        "account_trial_suffix": " (سرویس تست)",
        "account_info_button": "🗓 مشاهده اطلاعات اکانت",
        "account_renew_button": "♻️ تمدید یا ارتقا اشتراک",
        "account_password_button": "🔑 تغییر پسورد",
        "account_ownership_button": "🔄 تغییر مالکیت",
        "info_status_label": "وضعیت",
        "info_volume_label": "حجم",
        "info_expiry_label": "تاریخ انقضا",
        "info_expiry_value": "{date} UTC",
        "info_expiry_pending": "از اولین اتصال شروع می‌شود",
        "info_expiry_unknown": "—",
        "info_password_unavailable": "در دسترس نیست — با پشتیبانی تماس بگیرید",

        # --- My Services: change password ---
        "pw_confirm": (
            "🔑 با این کار یک رمز عبور جدید برای <code>{username}</code> ساخته می‌شود "
            "(نام کاربری تغییر نمی‌کند).\nاین کار را فقط یک‌بار در ماه می‌توانید انجام دهید. ادامه می‌دهید؟"
        ),
        "pw_confirm_button": "✅ بله، رمز جدید ساخته شود",
        "pw_cooldown": "⚠️ رمز عبور این سرویس به‌تازگی تغییر کرده. تا {days} روز دیگر می‌توانید دوباره رمز را عوض کنید.",
        "pw_done": "✅ رمز عبور جدید شما آماده است.",
        "pw_failed": "⚠️ در حال حاضر امکان تغییر رمز عبور نیست. لطفاً کمی بعد دوباره تلاش کنید.",
        "pw_refused_group": "⚠️ این اکانت از اینجا قابل تغییر نیست — لطفاً با پشتیبانی تماس بگیرید.",

        # --- My Services: change ownership ---
        "xfer_prompt": (
            "🔄 <b>تغییر مالکیت</b>\n\nیوزرنیم تلگرام (با @) یا آیدی عددی کسی را که باید مالک "
            "<code>{username}</code> شود بفرستید.\nاو باید حداقل یک‌بار ربات را استارت کرده باشد و اکانت "
            "فقط پس از تأیید او منتقل می‌شود."
        ),
        "xfer_not_found": (
            "❌ کاربری با این یوزرنیم یا آیدی یافت نشد — کاربر مقصد باید حداقل یک‌بار ربات را استارت کرده باشد. "
            "دوباره وارد کنید:"
        ),
        "xfer_self": "❌ این خودتان هستید. یوزرنیم یا آیدی شخص دیگری را بفرستید:",
        "xfer_ambiguous": "⚠️ بیش از یک کاربر این یوزرنیم را داشته‌اند. لطفاً آیدی عددی تلگرام او را بفرستید:",
        "xfer_confirm": "⚠️ اکانت <code>{username}</code> به {recipient} پیشنهاد می‌شود.\nتا زمانی که او تأیید نکند، اکانت متعلق به شما می‌ماند. درخواست ارسال شود؟",
        "xfer_send_button": "✅ ارسال درخواست",
        "xfer_sent": (
            "📨 درخواست برای {recipient} ارسال شد. اکانت <code>{username}</code> تا زمان تأیید او متعلق به شما "
            "می‌ماند؛ این درخواست پس از ۲۴ ساعت منقضی می‌شود."
        ),
        "xfer_cancel_button": "❌ لغو درخواست",
        "xfer_unreachable": "⚠️ امکان ارسال پیام به {recipient} نبود — ممکن است ربات را مسدود کرده باشد. درخواست لغو شد.",
        "xfer_offer": "🔄 {owner} می‌خواهد اکانت VPN <code>{username}</code> ({plan}) را به شما منتقل کند.\nقبول می‌کنید؟",
        "xfer_accept_button": "✅ قبول",
        "xfer_decline_button": "❌ رد",
        "xfer_accepted_recipient": (
            "✅ اکانت <code>{username}</code> اکنون متعلق به شماست — آن را در «سرویس‌های من» پیدا می‌کنید.\n"
            "ممکن است مالک قبلی هنوز رمز عبور را بداند؛ می‌توانید همین حالا از منوی اکانت آن را تغییر دهید."
        ),
        "xfer_accepted_owner": "✅ {recipient} تأیید کرد — اکانت <code>{username}</code> منتقل شد.",
        "xfer_declined_recipient": "رد شد — چیزی منتقل نشد.",
        "xfer_declined_owner": "❌ {recipient} انتقال اکانت <code>{username}</code> را رد کرد. اکانت همچنان متعلق به شماست.",
        "xfer_cancelled_owner": "درخواست لغو شد — اکانت <code>{username}</code> متعلق به شما می‌ماند.",
        "xfer_cancelled_recipient": "این درخواست انتقال توسط مالک لغو شد.",
        "xfer_expired": "⌛ این درخواست انتقال منقضی شده است.",
        "xfer_invalid": "⚠️ این درخواست دیگر معتبر نیست.",
        "xfer_user_id": "کاربر {telegram_id}",
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
    except (KeyError, IndexError, ValueError):
        logger.warning("i18n key %r formatting failed with kwargs=%r", key, kwargs)
        return template
