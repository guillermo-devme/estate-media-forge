# wix-site — Velo project (independent of the FastAPI service)

This folder mirrors a **Wix Studio / Velo** site layout so you can copy files straight into the Wix
editor (Dev Mode on). It is fully independent of the FastAPI service in `../kiro-prompts/` — nothing
here imports or runs the Python API; it only calls it over HTTPS with signed requests.

```
wix-site/
├── backend/                 → Wix "Backend" section
│   ├── lib/
│   │   ├── falClient.js     internal: HMAC-signed fetch to FastAPI
│   │   ├── wallet.js        internal: balance + per-member lock + grant/spend/refund
│   │   └── roles.js         internal: role → service permission matrix
│   ├── quotation.web.js     web method: getQuote (no spend)
│   ├── media.web.js         web methods: submitUpscale/ImageToVideo/MediaKit + getJobStatus
│   ├── wallet.web.js        web methods: getWallet + adminAdjust
│   └── http-functions.js    inbound: post_stripeWebhook (add) + post_falRefund (refund)
├── pages/                   → page code panels (paste into the matching page)
│   └── Generator.example.js example frontend flow (quote → submit → poll)
└── public/                  → shared frontend code
    ├── aspectRatios.js
    └── credits.js
```

## How to install in Wix

1. Turn on **Dev Mode** in your Wix Studio site.
2. Under **Backend**, create the files exactly as named above. `lib/*.js` go in a `backend/lib`
   folder; `*.web.js` and `http-functions.js` go directly under `backend`.
3. Under **Public**, add `aspectRatios.js` and `credits.js`.
4. Open the page that hosts your generator UI, open its code panel, and paste the relevant parts of
   `pages/Generator.example.js` (rename element IDs to match your design).
5. Create the CMS collections, roles, and Secrets per `../wix-integration/SETUP.md`.

## Security notes (do not skip)

- All CMS access is via elevated backend modules; collections are **Admin-only** (see SETUP.md).
- Outbound calls to FastAPI are **HMAC-signed** (`backend/lib/falClient.js`).
- Secrets live only in **Wix Secrets Manager** — never hardcode keys in these files.
- `import` paths use Velo's `backend/...` and `public/...` resolution.
