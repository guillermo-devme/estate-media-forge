/**
 * roles.js — role → service permission matrix (internal backend module)
 *
 *  role     upscale  image_to_video  media_kit  adjust
 *  member     ✓          ✗              ✗          ✗
 *  pro        ✓          ✓              ✓          ✗
 *  admin      ✓          ✓              ✓          ✓
 *
 * Edit SERVICE_ROLES to change gating. Role names must match the Wix member
 * role/badge names exactly (see SETUP.md).
 */

export const SERVICE_ROLES = {
  upscale: ['member', 'pro', 'admin'],
  image_to_video: ['pro', 'admin'],
  media_kit: ['pro', 'admin'],
  adjust: ['admin'],
};

export class ForbiddenError extends Error {
  constructor(msg) { super(msg); this.name = 'ForbiddenError'; this.code = 403; }
}

/**
 * @param {string} service one of SERVICE_ROLES keys
 * @param {string[]} memberRoleNames lowercased role names from currentMember.getRoles()
 */
export function assertRole(service, memberRoleNames) {
  const allowed = SERVICE_ROLES[service];
  if (!allowed) throw new ForbiddenError(`Unknown service: ${service}`);
  const ok = memberRoleNames.some((r) => allowed.includes(r));
  if (!ok) {
    throw new ForbiddenError(
      `Your plan does not include "${service}". Required role: ${allowed.join(' or ')}.`
    );
  }
}
