/**
 * public/credits.js — friendly formatting for the credits/allowance UI.
 * Credits only — USD is never exposed by the backend.
 */
export function formatAllowance(allowance) {
  if (!allowance) return '';
  const parts = [];
  if (allowance.upscale_images) parts.push(`${allowance.upscale_images} upscales`);
  if (allowance.videos_8s) parts.push(`${allowance.videos_8s} videos (8s)`);
  if (allowance.media_kits) parts.push(`${allowance.media_kits} media kits`);
  return parts.length ? `Your credits ≈ ${parts.join(', or ')}.` : 'No credits yet.';
}

export function shortByMessage(shortBy) {
  return shortBy > 0
    ? `You need ${shortBy} more credits for this. Top up to continue.`
    : '';
}
