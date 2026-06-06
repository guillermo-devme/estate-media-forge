/**
 * quotation.web.js — pre-flight quote (NO spend, NO decrement).
 * Returns credits required + breakdown + whether the member can afford it.
 *
 *  frontend ─▶ getQuote(service, params)
 *               currentMember → role check → POST /v1/quotation (pricing only)
 *               read CMS balance → sufficient?  ─▶ {credits, breakdown, balance, sufficient}
 */
import { Permissions, webMethod } from 'wix-web-module';
import { currentMember } from 'wix-members-backend';
import { assertRole, ForbiddenError } from 'backend/lib/roles.js';
import { getBalance } from 'backend/lib/wallet.js';
import { callFastApi } from 'backend/lib/falClient.js';

async function memberContext() {
  const m = await currentMember.getMember();
  if (!m) { const e = new Error('Login required'); e.code = 401; throw e; }
  const roles = (await currentMember.getRoles()) || [];
  const names = roles.map((r) => (r.name || r.title || '').toLowerCase());
  // every logged-in member is at least "member"
  if (!names.includes('member')) names.push('member');
  return { memberId: m._id, roleNames: names, primaryRole: names.includes('admin') ? 'admin' : names.includes('pro') ? 'pro' : 'member' };
}

export const getQuote = webMethod(Permissions.SiteMember, async (service, params) => {
  const { memberId, roleNames, primaryRole } = await memberContext();
  assertRole(service, roleNames);

  const quote = await callFastApi('/v1/quotation', { service, ...params }, memberId, primaryRole);
  const balance = await getBalance(memberId);

  return {
    service,
    total_credits: quote.total_credits,
    breakdown: quote.breakdown,
    balance,
    sufficient: balance >= quote.total_credits,
    short_by: Math.max(0, quote.total_credits - balance),
  };
});
