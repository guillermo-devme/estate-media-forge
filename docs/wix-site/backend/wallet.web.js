/**
 * wallet.web.js — member reads own balance + "what your credits buy" allowance.
 * Admin may read any member and apply manual adjustments (the only non-Stripe write,
 * gated to admin; Stripe purchases still flow exclusively through the http-function).
 */
import { Permissions, webMethod } from 'wix-web-module';
import { currentMember } from 'wix-members-backend';
import { assertRole } from 'backend/lib/roles.js';
import { getBalance, grant } from 'backend/lib/wallet.js';
import { getFastApi, callFastApi } from 'backend/lib/falClient.js';
import crypto from 'crypto';

async function memberContext() {
  const m = await currentMember.getMember();
  if (!m) { const e = new Error('Login required'); e.code = 401; throw e; }
  const roles = (await currentMember.getRoles()) || [];
  const names = roles.map((r) => (r.name || r.title || '').toLowerCase());
  if (!names.includes('member')) names.push('member');
  const primaryRole = names.includes('admin') ? 'admin' : names.includes('pro') ? 'pro' : 'member';
  return { memberId: m._id, roleNames: names, primaryRole };
}

/** Returns balance + allowance counts (allowance math lives in FastAPI pricing, single source). */
export const getWallet = webMethod(Permissions.SiteMember, async () => {
  const { memberId, primaryRole } = await memberContext();
  const balance = await getBalance(memberId);
  // FastAPI computes how many upscales / videos / media-kits this balance buys.
  const allowance = await callFastApi('/v1/pricing/allowance', { balance }, memberId, primaryRole);
  return { balance, allowance: allowance.allowance };
});

/**
 * Admin-only manual adjustment (corrections / comps). NOT a purchase path.
 * Stripe remains the only automated way to add tokens.
 */
export const adminAdjust = webMethod(Permissions.SiteMember, async (targetMemberId, credits, reason) => {
  const { roleNames } = await memberContext();
  assertRole('adjust', roleNames); // admin only
  const txId = `adjust_${crypto.randomUUID()}`;
  const { balance } = await grant(targetMemberId, credits, txId, reason || 'admin_adjust', 'admin');
  return { memberId: targetMemberId, balance };
});
