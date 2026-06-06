/**
 * http-functions.js — the ONLY inbound endpoints.
 *
 *  POST /_functions/stripeWebhook  ← Stripe. The ONLY path that ADDS tokens.
 *  POST /_functions/falRefund      ← FastAPI worker. Proportional refund on job failure.
 *
 *  STRIPE IDEMPOTENCY
 *  ┌──────────────┐ verify sig ┌───────────────────────────┐ insert tx _id=stripe_{event.id}
 *  │ Stripe event ├───────────▶│ valid?  no → 400           ├──┬─ duplicate → 200 (no-op)
 *  └──────────────┘            └───────────────────────────┘  └─ new → grant(member,credits)
 *
 *  Secrets: STRIPE_WEBHOOK_SECRET, SERVICE_HMAC_SECRET, FASTAPI_SERVICE_KEY
 */
import { ok, badRequest, serverError, forbidden } from 'wix-http-functions';
import { getSecret } from 'wix-secrets-backend';
import crypto from 'crypto';
import { grant, refund } from 'backend/lib/wallet.js';

function timingSafeEqualHex(a, b) {
  const ba = Buffer.from(a, 'utf8');
  const bb = Buffer.from(b, 'utf8');
  if (ba.length !== bb.length) return false;
  return crypto.timingSafeEqual(ba, bb);
}
const sha256Hex = (s) => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
const hmacHex = (secret, msg) => crypto.createHmac('sha256', secret).update(msg, 'utf8').digest('hex');

// ───────────────────────── Stripe webhook (add tokens) ─────────────────────────
export async function post_stripeWebhook(request) {
  const raw = await request.body.text();
  const sigHeader = request.headers['stripe-signature'] || '';
  const secret = await getSecret('STRIPE_WEBHOOK_SECRET');

  // Parse "t=...,v1=..." and verify HMAC over `${t}.${raw}`
  const parts = Object.fromEntries(sigHeader.split(',').map((kv) => kv.split('=')));
  const t = parts.t;
  const v1 = parts.v1;
  if (!t || !v1) return badRequest({ body: { error: 'bad signature header' } });
  if (Math.abs(Date.now() / 1000 - Number(t)) > 300) return badRequest({ body: { error: 'stale' } });
  const expected = hmacHex(secret, `${t}.${raw}`);
  if (!timingSafeEqualHex(expected, v1)) return badRequest({ body: { error: 'signature mismatch' } });

  const event = JSON.parse(raw);

  // Only purchase-completing events grant credits.
  const GRANTING = ['checkout.session.completed', 'payment_intent.succeeded'];
  if (!GRANTING.includes(event.type)) return ok({ body: { received: true, ignored: event.type } });

  const obj = event.data.object;
  const memberId = obj.metadata?.member_id;
  const credits = parseInt(obj.metadata?.credits, 10);
  if (!memberId || !Number.isFinite(credits) || credits <= 0) {
    return badRequest({ body: { error: 'missing member_id/credits in metadata' } });
  }

  try {
    const result = await grant(memberId, credits, `stripe_${event.id}`, event.id, 'stripe');
    return ok({ body: { received: true, granted: result.granted, balance: result.balance } });
  } catch (e) {
    return serverError({ body: { error: String(e.message || e) } });
  }
}

// ───────────────────────── FastAPI refund callback ─────────────────────────
//  body: { member_id, job_id, refund_credits, reason }
//  HMAC over `${ts}.${nonce}.${member_id}.${sha256(rawBody)}`
export async function post_falRefund(request) {
  const raw = await request.body.text();
  const h = request.headers;
  const [serviceKey, hmacSecret] = await Promise.all([
    getSecret('FASTAPI_SERVICE_KEY'),
    getSecret('SERVICE_HMAC_SECRET'),
  ]);

  if (!timingSafeEqualHex(h['x-service-key'] || '', serviceKey)) return forbidden({ body: { error: 'bad key' } });
  const ts = h['x-timestamp']; const nonce = h['x-nonce']; const sig = h['x-signature'];
  if (!ts || !nonce || !sig) return badRequest({ body: { error: 'missing sig headers' } });
  if (Math.abs(Date.now() / 1000 - Number(ts)) > 300) return badRequest({ body: { error: 'stale' } });

  let body;
  try { body = JSON.parse(raw); } catch { return badRequest({ body: { error: 'bad json' } }); }
  const memberId = body.member_id;
  const expected = hmacHex(hmacSecret, `${ts}.${nonce}.${memberId}.${sha256Hex(raw)}`);
  if (!timingSafeEqualHex(expected, sig)) return forbidden({ body: { error: 'signature mismatch' } });

  try {
    const result = await refund(memberId, Number(body.refund_credits), body.job_id, body.reason || 'job_failed');
    return ok({ body: { ok: true, refunded: result.refunded, balance: result.balance } });
  } catch (e) {
    return serverError({ body: { error: String(e.message || e) } });
  }
}
