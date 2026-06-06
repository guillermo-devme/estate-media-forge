/**
 * mediaUpload.js — persist fal.ai outputs to Wix Media Manager.
 *
 * When a job completes, the temporary fal CDN URLs are imported into the site's
 * Media Manager via `wix-media-backend`. This gives the member permanent
 * wixstatic.com URLs and integrates the media with Wix galleries, downloads, etc.
 *
 * The FastAPI service stays a pure compute backend — it never touches Wix Media.
 *
 *  Flow:
 *    getJobStatus → completed → persistJobAssets(memberId, jobId, assets)
 *      for each asset with a URL:
 *        mediaManager.importFile(folder, url, options) → fileDescriptor
 *      save permanent URLs to CMS "MemberMedia" collection
 *      return array of { aspect_ratio, type, wixMediaUrl }
 *
 *  CMS Collection: MemberMedia
 *    _id: auto
 *    memberId: string (indexed)
 *    jobId: string (indexed)
 *    aspectRatio: string
 *    mediaType: "image" | "video"
 *    stage: "upscaled" | "expanded" | "video"
 *    sourceUrl: string (original fal URL, for debug)
 *    wixMediaUrl: string (permanent wixstatic.com URL)
 *    fileId: string (Wix Media Manager file ID)
 *    createdDate: Date
 */
import { mediaManager } from 'wix-media-backend';
import wixData from 'wix-data';

const OPTS = { suppressAuth: true, suppressHooks: true };
const COLLECTION = 'MemberMedia';

/**
 * Import a single URL into Wix Media Manager.
 * @param {string} url  The temporary fal CDN URL.
 * @param {string} folder  Target folder path in Media Manager (e.g. "/media-kit/mem123").
 * @param {string} fileName  Descriptive filename (e.g. "job_abc_16x9_video.mp4").
 * @param {"image"|"video"} mediaType
 * @returns {Promise<{fileUrl: string, fileId: string}>}
 */
async function importToMediaManager(url, folder, fileName, mediaType) {
  if (!url) return null;

  const mimeType = mediaType === 'video' ? 'video/mp4' : 'image/png';
  const descriptor = await mediaManager.importFile(folder, url, {
    mediaOptions: { mimeType, mediaType },
    metadataOptions: {
      isPrivate: false,
      isVisitorUpload: false,
      fileName,
    },
  });

  return {
    fileUrl: descriptor.fileUrl, // permanent wixstatic.com URL
    fileId: descriptor._id || descriptor.hash || null,
  };
}

/**
 * Persist all completed assets of a job to Wix Media Manager + CMS.
 * Idempotent: checks if this jobId already has media rows, skips if so.
 *
 * @param {string} memberId  The owning member.
 * @param {string} jobId     The FastAPI job ID.
 * @param {Array}  assets    Array of AssetSet from JobStatusResponse.
 * @returns {Promise<Array<{aspectRatio, stage, wixMediaUrl}>>}
 */
export async function persistJobAssets(memberId, jobId, assets) {
  // Idempotency: if we already persisted this job's media, return existing.
  const existing = await wixData.query(COLLECTION)
    .eq('jobId', jobId)
    .eq('memberId', memberId)
    .find(OPTS);
  if (existing.items.length > 0) {
    return existing.items.map((item) => ({
      aspectRatio: item.aspectRatio,
      stage: item.stage,
      wixMediaUrl: item.wixMediaUrl,
    }));
  }

  const folder = `/media-kit/${memberId}`;
  const results = [];

  for (const asset of assets) {
    if (asset.status !== 'completed') continue;
    const ratio = asset.aspect_ratio || asset.aspectRatio;
    const safeRatio = (ratio || '').replace(':', 'x');

    // Upload each non-null URL (upscaled, expanded, video).
    const uploads = [
      { key: 'upscaled_url', stage: 'upscaled', type: 'image' },
      { key: 'expanded_url', stage: 'expanded', type: 'image' },
      { key: 'video_url', stage: 'video', type: 'video' },
    ];

    for (const { key, stage, type } of uploads) {
      const sourceUrl = asset[key];
      if (!sourceUrl) continue;

      const ext = type === 'video' ? 'mp4' : 'png';
      const fileName = `${jobId}_${safeRatio}_${stage}.${ext}`;

      try {
        const result = await importToMediaManager(sourceUrl, folder, fileName, type);
        if (!result) continue;

        const row = {
          memberId,
          jobId,
          aspectRatio: ratio,
          mediaType: type,
          stage,
          sourceUrl,
          wixMediaUrl: result.fileUrl,
          fileId: result.fileId,
          createdDate: new Date(),
        };
        await wixData.insert(COLLECTION, row, OPTS);
        results.push({ aspectRatio: ratio, stage, wixMediaUrl: result.fileUrl });
      } catch (err) {
        // Log but don't fail the whole batch — partial upload is still useful.
        console.error(`[mediaUpload] Failed to import ${stage} for ${ratio}:`, err.message);
      }
    }
  }

  return results;
}

/**
 * Retrieve all persisted media for a job (for re-rendering without re-uploading).
 */
export async function getJobMedia(memberId, jobId) {
  const result = await wixData.query(COLLECTION)
    .eq('jobId', jobId)
    .eq('memberId', memberId)
    .find(OPTS);
  return result.items.map((item) => ({
    aspectRatio: item.aspectRatio,
    stage: item.stage,
    wixMediaUrl: item.wixMediaUrl,
    mediaType: item.mediaType,
  }));
}
