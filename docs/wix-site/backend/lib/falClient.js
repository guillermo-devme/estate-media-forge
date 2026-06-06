/**
 * falClient.js — signed server-to-server client for the FastAPI media service.
 *
 * Every outbound call is HMAC-signed so a leaked service key alone cannot forge a
 * spend, and replays are rejected (timestamp + nonce).
 *
 *   sig = HMAC_SHA256(SERVICE_HMAC_SECRET,
 *                     `${ts}.${nonce}.${memberId}.${sha256(rawBody)}`)
 *   headers: X-Service-Key, X-Member-Id, X-Timestamp, X-Nonce, X-Signature, X-Member-Role
 *
 * Secrets (Wix Secrets Manager): FASTAPI_BASE_URL, FASTAPI_SERVICE_KEY, SERVICE_HMAC_SECRET
 */
import { fetch } from 'wix-fetch';
import { getSecret } from 'wix-secrets-backend';
import crypto from 'crypto';

function sha256Hex(s) {
  return crypto.createHash('sha256').update(s, 'utf8').digest('hex');
}

function hmacHex(secret, msg) {
  return crypto.createHmac('sha256', secret).update(msg, 'utf8').digest('hex');
}

/**
 * Call a FastAPI endpoint with a signed body.
 * @param {string} path e.g. "/v1/media-kit"
 * @param {object} payload request body (must include member_id)
 * @param {string} memberId authenticated member _id
 * @param {string} role member's effective role (for logging/defense-in-depth)
 * @param {string} method default POST
 */
export async function callFastApi(path, payload, memberId, role, method = 'POST') {
  const [baseUrl, serviceKey, hmacSecret] = await Promise.all([
    getSecret('FASTAPI_BASE_URL'),
    getSecret('FASTAPI_SERVICE_KEY'),
    getSecret('SERVICE_HMAC_SECRET'),
  ]);

  const body = JSON.stringify({ ...payload, member_id: memberId });
  const ts = Math.floor(Date.now() / 1000).toString();
  const nonce = crypto.randomUUID();
  const sig = hmacHex(hmacSecret, `${ts}.${nonce}.${memberId}.${sha256Hex(body)}`);

  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Service-Key': serviceKey,
      'X-Member-Id': memberId,
      'X-Member-Role': role || 'member',
      'X-Timestamp': ts,
      'X-Nonce': nonce,
      'X-Signature': sig,
    },
    body: method === 'GET' ? undefined : body,
  });

  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) {
    const err = new Error(data.detail || data.message || `FastAPI ${res.status}`);
    err.code = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

/** GET helper (no body to sign beyond empty) */
export async function getFastApi(path, memberId, role) {
  return callFastApi(path, {}, memberId, role, 'GET');
}
