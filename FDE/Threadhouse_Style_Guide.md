Threadhouse is a mid-market Indian fashion retailer. Customers browse and reserve online, then try on and collect at a nearby store. They pay at the store or online. The look is warm, clear and unfussy: an indigo line, one saffron accent, and plenty of room.

## Content fundamentals

- Speak plainly, in the second person ("your order is ready"). Sentence case everywhere. No exclamation marks, no emoji.
- Use these words: **bag** (not cart), **reserve** (not buy now), **pickup** and **Pay at store**, **store** (not outlet or branch), **Ready for pickup**, **Collected**, **Not collected**. Order statuses are exact (see StatusPill).
- Name the time frame: "Ready in 2 hours", "Held for 3 days".
- Money is ₹ with Indian grouping and no decimals: ₹1,499, ₹1,24,500. Dates read 22 Oct. Sizes are S, M, L, XL, XXL, or waist numbers for jeans.
- Errors say what is wrong and how to fix it: "Enter a 10-digit mobile number."
- Example copy: "Free pickup in 2 hours", "Check store availability", "Only 2 left here", "We text you when your order is ready."

## Visual foundations

- **Color.** Page is `surface`; cards, header and fields are `surface-raised`; quiet panels and image placeholders are `surface-tint`. Text is `ink`, secondary text `ink-muted`. `brand` (indigo) is the only action colour: primary buttons, links, active navigation, focus. `accent` (saffron) is a fill for the pickup banner and badges, never text on light surfaces. Status colours come only as `status-*-bg` with its matching `status-*-text`.
- **Themes.** Light and dark are both complete. Every colour is used through its token, never as a literal.
- **Type.** Headings in `display` styles (Outfit, weight 600). Everything else in `body` styles (Plus Jakarta Sans). Prices use `price` with tabular numbers. Inputs and body text are never below 16px. Indian-language text falls back to Noto Sans for the script.
- **Spacing.** Multiples of 4 from the `space-*` tokens. Page gutter `space-4` on phones. Sections `space-6` apart on phones and `space-7` on desktop.
- **Radius.** `radius-sm` fields, `radius-md` buttons and banners, `radius-lg` cards and sheets, `radius-pill` pills and chips.
- **Edges and shadow.** Cards at rest use a `line` hairline, no shadow. `shadow-card` appears on hover and on the sticky mobile bar. `shadow-sheet` is only for bottom sheets.
- **Imagery.** Product photos are 4:5 portrait on a plain light ground. With no photo, show the category name on `surface-tint`. No stock lifestyle photography, no gradients.
- **Motion.** Short and functional: 150 to 200 ms fades and slides for sheets and toasts. Respect reduced motion.
- **States.** Hover darkens to `brand-hover` or tints with `surface-tint`. Focus is a 2px `focus-ring` outline with a 2px offset on everything interactive. Disabled controls say why.

## Iconography

Use Lucide icons: 24px, stroke 1.75, rounded caps and joins, in `ink` or `brand`. They share the rounded single-line character of the logo. Do not use emoji or filled icon sets. Status is always a word, with a dot at most.

## Layout

- Design phone first at 390px wide, then widen. Content max width 1120px, centred.
- Product grid: 2 columns on phones, 3 on tablets, 4 on desktop.
- Header: lockup at left, search, bag. A saffron promo banner may sit above it.
- Product page on phones: image, name, price, size chips, store availability row, then a sticky bottom bar with the primary button.
- Checkout has three steps on one page: choose the pickup store, your details, payment (Pay at store or Pay online). Always show the order summary.
- Admin screens (store and ops) use the same tokens, with tables on `surface-raised` and the status pills for order state.

## Using this in code

Declare tokens as CSS variables and point the framework's colours at them. Light values below; dark values are in `tokens.json`.

```css
:root{
  --surface:#faf7f2; --surface-raised:#ffffff; --surface-tint:#ecedf9;
  --ink:#1b1d3a; --ink-muted:#565974; --line:#e2ddd2; --line-strong:#80839c;
  --brand:#2b2f77; --brand-hover:#20245c; --on-brand:#ffffff;
  --accent:#f2a541; --on-accent:#1b1d3a;
  --radius-sm:8px; --radius-md:12px; --radius-lg:20px;
}
.dark{
  --surface:#14152b; --surface-raised:#1d1f3d; --surface-tint:#262955;
  --ink:#f3f1ea; --ink-muted:#a9abc8; --line:#34376a; --line-strong:#7a7db0;
  --brand:#aeb2ff; --brand-hover:#c6c9ff; --on-brand:#14152b;
}
```

Load Outfit (600) and Plus Jakarta Sans (400, 500, 600, 700) from Google Fonts.
