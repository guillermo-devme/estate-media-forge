/**
 * public/aspectRatios.js — shared frontend constants for the media-kit ratios.
 * Public modules are importable from both page code and backend.
 */
export const ASPECT_RATIOS = ['1:1', '9:16', '16:9'];

export const RATIO_LABELS = {
  '1:1': 'Square (feed / grid)',
  '9:16': 'Vertical (stories / reels)',
  '16:9': 'Widescreen (web / YouTube)',
};

export function isValidRatio(r) {
  return ASPECT_RATIOS.includes(r);
}
