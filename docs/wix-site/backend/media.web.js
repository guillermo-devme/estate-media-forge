/**
 * media.web.js — the spend path. Quote → role check → decrement (hold) → call FastAPI → 202.
 *
 *  submit*(params)
 *    ├─ currentMember + roles            (auth)
 *    ├─ assertRole(service, roles)       (403 if plan lacks it)
 *    ├─ getQuote → credits               (pricing from FastAPI)
 *    ├─ spend(memberId, credits, jobId?) ── but jobId comes FROM FastAPI...
 *    │   → so: reserve first by pre-generating a clientRef, decrement, then submit;
 *    │     on FastAPI error → refund(clientRef).
 *    └─ record Jobs ownership → return {job_id, credits, balance}
 *
 *  Ordering note: we decrement BEFORE calling FastAPI using a client-generated reference
 *  (clientRef) as the idempotency key, then map it to the returned job_id. If FastAPI
 *  fails, we immediately refund clientRef. The worker later refunds partial failures
 *  against the job_id via the post_falRefund http-function.
 */
import { Permissions, webMethod } from 'wix-web-module';
import { currentMember } from 'wix-members-backend';
import wixData from 'wix-data';
import crypto from 'crypto';
import { assertRole } from 'backend/lib/roles.js';
import { spend, refund, getBalance, InsufficientCredits } from 'backend/lib/wallet.js';
import { callFastApi, getFastApi } from 'backend/lib/falClient.js';

const OPTS = { suppressAuth: true, suppressHooks: true };

async function memberContext() {
  const m = await currentMember.getMember();
  if (!m) { const e = new Error('Login required'); e.code = 401; throw e; }
  const roles = (await currentMember.getRoles()) || [];
  const names = roles.map((r) => (r.name || r.title || '').toLowerCase());
  if (!names.includes('member')) names.push('member');
  const primaryRole = names.includes('admin') ? 'admin' : names.includes('pro') ? 'pro' : 'member';
  return { memberId: m._id, roleNames: names, primaryRole };
}

async function quoteCredits(service, params, memberId, role) {
  const quote = await callFastApi('/v1/quotation', { service, ...params }, memberId, role);
  return { credits: quote.total_credits, breakdown: quote.breakdown };
}

/**
 * Generic submit used by all three services.
 * @param {"upscale"|"image_to_video"|"media_kit"} service
 * @param {string} endpoint FastAPI submit path
 */
async function submit(service, endpoint, params) {
  const { memberId, roleNames, primaryRole } = await memberContext();
  assertRole(service, roleNames);

  const { credits } = await quoteCredits(service, params, memberId, primaryRole);
  const clientRef = crypto.randomUUID(); // idempotency key: ties the decrement to the FastAPI job

  // 1) decrement (the hold) — throws InsufficientCredits (code 402) if short.
  //    Idempotent on spend_{clientRef}, so re-running this submit with the same clientRef is safe.
  await spend(memberId, credits, clientRef);

  // 2) submit to FastAPI. FastAPI is idempotent on (member_id, client_ref): a retry returns the
  //    SAME job_id and never creates a second fal-spending job (see kiro-prompts/13). So we must
  //    distinguish a DEFINITIVE non-acceptance (safe to refund) from an AMBIGUOUS outcome
  //    (timeout / 5xx / no response — the job MAY exist, so we must NOT blindly refund).
  const DEFINITIVE_REJECT = new Set([400, 401, 403, 404, 422]); // job was NOT accepted

  async function trySubmit() {
    return callFastApi(endpoint, { ...params, client_ref: clientRef, quoted_credits: credits }, memberId, primaryRole);
  }

  let res;
  try {
    res = await trySubmit();
  } catch (err) {
    if (DEFINITIVE_REJECT.has(err.code)) {
      // FastAPI explicitly refused — no job was created. Safe to undo the hold.
      await refund(memberId, credits, clientRef, 'submit_rejected');
      throw err;
    }
    // Ambiguous (timeout/5xx/network). Retry ONCE — idempotent on clientRef, so no double job.
    try {
      res = await trySubmit();
    } catch (err2) {
      if (DEFINITIVE_REJECT.has(err2.code)) {
        await refund(memberId, credits, clientRef, 'submit_rejected');
        throw err2;
      }
      // Still ambiguous: the job may or may not exist. Do NOT refund here (refunding now while the
      // job actually runs would mint free credits + waste fal cost). Park a reconcile intent; a
      // sweep (or the next getJobStatus) resolves it via GET /v1/jobs/by-client-ref/{clientRef}.
      await wixData.save('PendingSubmits', {
        _id: clientRef, memberId, service, quotedCredits: credits,
        params, status: 'pending_reconcile', createdDate: new Date(),
      }, OPTS).catch(() => {});
      const e = new Error('Submission pending confirmation — do not resubmit; it will reconcile.');
      e.code = 202; e.clientRef = clientRef; e.pending = true;
      throw e;
    }
  }

  // 3) record ownership so getJobStatus can verify the caller, and link job_id ↔ clientRef
  await wixData.save('Jobs', {
    _id: res.job_id, memberId, service, quotedCredits: credits,
    clientRef, status: res.status || 'queued', createdDate: new Date(),
  }, OPTS);
  await wixData.remove('PendingSubmits', clientRef, OPTS).catch(() => {}); // clear any prior intent

  return { job_id: res.job_id, credits, balance: await getBalance(memberId), poll_url: res.poll_url };
}

/**
 * Reconcile an ambiguous submit (the FastAPI call timed out). Asks FastAPI whether a job exists for
 * this clientRef. If yes → records ownership and clears the intent. If no (and the intent is old
 * enough that FastAPI would have created it by now) → refunds the held credits. Idempotent.
 * Call from a scheduled job and/or lazily when a member returns. The decrement is keyed
 * spend_{clientRef} and the refund refund_{clientRef}, so this can run repeatedly without harm.
 */
async function reconcileSubmit(memberId, primaryRole, clientRef) {
  const intent = await wixData.get('PendingSubmits', clientRef, OPTS).catch(() => null);
  const status = await getFastApi(`/v1/jobs/by-client-ref/${clientRef}`, memberId, primaryRole).catch((e) => {
    if (e.code === 404) return null;        // FastAPI has no such job
    throw e;                                // still ambiguous (network) — leave intent, try later
  });
  if (status && status.job_id) {
    await wixData.save('Jobs', {
      _id: status.job_id, memberId, service: status.service, quotedCredits: status.quoted_credits,
      clientRef, status: status.status || 'queued', createdDate: new Date(),
    }, OPTS);
    await wixData.remove('PendingSubmits', clientRef, OPTS).catch(() => {});
    return { resolved: 'job_found', job_id: status.job_id };
  }
  // Definitive 404 → the submit never landed. Refund the held credits from the saved intent
  // (idempotent on refund_{clientRef}); skip if we have no intent to size the refund.
  if (intent && intent.quotedCredits > 0) {
    await refund(memberId, intent.quotedCredits, clientRef, 'submit_never_landed').catch(() => {});
  }
  await wixData.remove('PendingSubmits', clientRef, OPTS).catch(() => {});
  return { resolved: 'refunded' };
}
export { reconcileSubmit };

export const submitUpscale = webMethod(Permissions.SiteMember, (params) =>
  submit('upscale', '/v1/upscale', params));

export const submitImageToVideo = webMethod(Permissions.SiteMember, (params) =>
  submit('image_to_video', '/v1/image-to-video', params));

export const submitMediaKit = webMethod(Permissions.SiteMember, (params) =>
  submit('media_kit', '/v1/media-kit', params));

/** Poll job status — verifies the job belongs to the calling member. */
export const getJobStatus = webMethod(Permissions.SiteMember, async (jobId) => {
  const { memberId, primaryRole } = await memberContext();
  const owned = await wixData.get('Jobs', jobId, OPTS).catch(() => null);
  if (!owned || owned.memberId !== memberId) { const e = new Error('Not found'); e.code = 404; throw e; }
  const status = await getFastApi(`/v1/jobs/${jobId}`, memberId, primaryRole);
  // keep the ownership row roughly in sync
  if (status.status && status.status !== owned.status) {
    await wixData.update('Jobs', { ...owned, status: status.status }, OPTS).catch(() => {});
  }
  return status;
});
