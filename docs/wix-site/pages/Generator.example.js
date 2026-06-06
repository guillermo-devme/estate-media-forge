/**
 * pages/Generator.example.js — example page code for the media-kit generator UI.
 *
 * Paste into the code panel of your generator page and rename the $w('#id') selectors to match
 * your design's elements. Demonstrates the full flow:
 *
 *   load → getWallet (show allowance)
 *   click Quote   → getQuote → show credits + sufficiency
 *   click Generate→ submitMediaKit → poll getJobStatus → render asset URLs
 */
import { getWallet } from 'backend/wallet.web.js';
import { getQuote } from 'backend/quotation.web.js';
import { submitMediaKit, getJobStatus } from 'backend/media.web.js';
import { formatAllowance, shortByMessage } from 'public/credits.js';

let currentJobId = null;
let pollTimer = null;

$w.onReady(async () => {
  await refreshWallet();

  $w('#quoteButton').onClick(onQuote);
  $w('#generateButton').onClick(onGenerate);
  $w('#generateButton').disable(); // enabled only after a sufficient quote
});

async function refreshWallet() {
  try {
    const { balance, allowance } = await getWallet();
    $w('#balanceText').text = `${balance} credits`;
    $w('#allowanceText').text = formatAllowance(allowance);
  } catch (e) {
    $w('#allowanceText').text = 'Sign in to see your credits.';
  }
}

function params() {
  return { image_url: $w('#imageUrlInput').value, room_name: $w('#roomNameInput').value };
}

async function onQuote() {
  $w('#statusText').text = 'Estimating…';
  try {
    const q = await getQuote('media_kit', params());
    if (q.sufficient) {
      $w('#statusText').text = `This media kit costs ${q.total_credits} credits.`;
      $w('#generateButton').enable();
    } else {
      $w('#statusText').text = shortByMessage(q.short_by);
      $w('#generateButton').disable();
    }
  } catch (e) {
    $w('#statusText').text = e.message || 'Could not get a quote.';
  }
}

async function onGenerate() {
  $w('#generateButton').disable();
  $w('#statusText').text = 'Submitting…';
  try {
    const job = await submitMediaKit(params()); // server-side: role check + decrement + submit
    currentJobId = job.job_id;
    await refreshWallet(); // balance now reflects the decrement
    startPolling();
  } catch (e) {
    // InsufficientCredits / role errors surface here
    $w('#statusText').text = e.message || 'Submission failed.';
    $w('#generateButton').enable();
  }
}

function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    try {
      const s = await getJobStatus(currentJobId);
      $w('#statusText').text = `Status: ${s.status}`;
      if (['completed', 'partial', 'failed'].includes(s.status)) {
        clearInterval(pollTimer);
        renderAssets(s.assets || []);
        if (s.status === 'failed') await refreshWallet(); // refund landed
      }
    } catch (e) {
      clearInterval(pollTimer);
      $w('#statusText').text = 'Lost track of the job. Please refresh.';
    }
  }, 3000);
}

function renderAssets(assets) {
  // Map your repeater/gallery here. Example for a repeater #assetsRepeater:
  $w('#assetsRepeater').data = assets.map((a) => ({
    _id: a.aspect_ratio,
    ratio: a.aspect_ratio,
    videoUrl: a.video_url,
    imageUrl: a.expanded_url || a.upscaled_url,
    status: a.status,
  }));
}
