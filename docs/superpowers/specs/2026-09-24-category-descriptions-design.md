# Category Descriptions — Design Spec

Date: 2026-09-24
Status: approved (requested directly, wording supplied by the owner)

## 1. Change

When a customer opens a category in Buy (`buy:category:<slug>`), the
plan list's header gains a one-line description of that category above
the existing "Pick a plan:" prompt. That handler is the only place a
single category is first presented; the price summary's Back button
returns to it, so the description reappears there too.

| slug | en | fa |
|---|---|---|
| `trip` | 📌 Ideal for short trips abroad, with full access to Iran's local network. | 📌 مناسب برای سفر کوتاه به خارج از کشور و دسترسی کامل به شبکه داخل ایران |
| `scroll` | Suited for domestic banks, apps, websites and government services. | مناسب برای استفاده از بانک‌ها، اپلیکیشن‌ها و سایت‌های داخلی و دولتی |
| `stream` | Suited for all online streaming platforms. | مناسب برای تمامی پلتفرم‌های پخش آنلاین می‌باشد |

Both languages are the owner's own wording and are used verbatim (only
Trip carries the 📌, as supplied).

## 2. Shape

Three new keys, `category_desc_<slug>`, in both language tables of
`app/i18n/texts.py`. The handler builds
`"{description}\n\n{buy_pick_plan}"`. No keyboard, callback or slug
changes; Trial is not a Buy category and gets no description.

## 3. Tests

A parametrised test over the three categories and both languages pins
each description verbatim at the start of the screen, and that the
"Pick a plan" prompt still ends it.
