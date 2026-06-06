/**
 * wallet.js — token balance owned by Wix CMS. The ONLY module that mutates balance.
 *
 * Wix Data has no atomic increment and no locking, so we serialize per-member
 * mutations with a unique-_id lock document (the one operation Wix guarantees
 * atomically: a second insert of the same _id fails).
 *
 *  LOCK STATE MACHINE (per memberId)
 *  ┌────────┐  insert TokenLocks{_id:member}  ┌──────────┐  delete lock  ┌──────────┐
 *  │ (free) ├────────────────────────────────▶│ ACQUIRED ├──────────────▶│  (free)  │
 *  └────────┘   dup? → retry w/ backoff        └──────────┘   (finally)   └──────────┘
 *        ▲          │ stale (createdDate>30s)?                                 │
 *        └──────────┴── delete stale lock, retry ◀───────────────────────────┘
 *
 *  BALANCE MUTATION (inside lock)
 *    grant : tx claim (insert idempotency _id) → balance += credits
 *    spend : balance ≥ credits ? balance -= credits + tx : throw InsufficientCredits
 *    refund: tx claim (insert idempotency _id) → balance += credits
 *  invariant: balance == Σ TokenTransactions.credits (per memberId)
 */
import wixData from 'wix-data';

const OPTS = { suppressAuth: true, suppressHooks: true }; // elevated backend access
const LOCK = 'TokenLocks';
const WALLET = 'TokenWallets';
const TX = 'TokenTransactions';
const STALE_LOCK_MS = 30000;

export class InsufficientCredits extends Error {
  constructor(required, available) {
    super(`Insufficient credits: need ${required}, have ${available}`);
    this.name = 'InsufficientCredits';
    this.code = 402;
    this.required = required;
    this.available = available;
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function acquireLock(memberId, attempts = 8) {
  for (let i = 0; i < attempts; i++) {
    try {
      await wixData.insert(LOCK, { _id: memberId, createdDate: new Date() }, OPTS);
      return;
    } catch (e) {
      // lock held — clear if stale, then back off and retry
      const existing = await wixData.get(LOCK, memberId, OPTS).catch(() => null);
      if (existing && Date.now() - new Date(existing.createdDate).getTime() > STALE_LOCK_MS) {
        await wixData.remove(LOCK, memberId, OPTS).catch(() => {});
      }
      await sleep(60 * (i + 1));
    }
  }
  throw new Error(`Could not acquire wallet lock for ${memberId}`);
}

async function releaseLock(memberId) {
  await wixData.remove(LOCK, memberId, OPTS).catch(() => {});
}

async function readBalance(memberId) {
  const w = await wixData.get(WALLET, memberId, OPTS).catch(() => null);
  return w ? Number(w.balance || 0) : 0;
}

async function writeBalance(memberId, balance) {
  await wixData.save(WALLET, { _id: memberId, balance, updatedDate: new Date() }, OPTS);
}

/** Public read (no mutation) — used by getWallet web method. */
export async function getBalance(memberId) {
  return readBalance(memberId);
}

/**
 * Grant credits. Idempotent on txId (e.g. `stripe_{eventId}`). Returns {granted, balance}.
 * The tx insert is the idempotency claim — if it already exists, we skip the balance change.
 */
export async function grant(memberId, credits, txId, ref, source = 'stripe') {
  await acquireLock(memberId);
  try {
    try {
      await wixData.insert(TX, {
        _id: txId, memberId, type: 'purchase', credits, ref, source, createdDate: new Date(),
      }, OPTS);
    } catch (dup) {
      return { granted: false, balance: await readBalance(memberId) }; // already applied
    }
    const balance = (await readBalance(memberId)) + credits;
    await writeBalance(memberId, balance);
    await wixData.update(TX, { _id: txId, memberId, type: 'purchase', credits, balanceAfter: balance, ref, source, createdDate: new Date() }, OPTS);
    return { granted: true, balance };
  } finally {
    await releaseLock(memberId);
  }
}

/**
 * Spend credits (the "hold"/decrement). Throws InsufficientCredits if short.
 * Idempotent on `spend_{jobId}`. Returns {balance}.
 */
export async function spend(memberId, credits, jobId) {
  const txId = `spend_${jobId}`;
  await acquireLock(memberId);
  try {
    const existing = await wixData.get(TX, txId, OPTS).catch(() => null);
    if (existing) return { balance: await readBalance(memberId) }; // idempotent
    const available = await readBalance(memberId);
    if (available < credits) throw new InsufficientCredits(credits, available);
    const balance = available - credits;
    await writeBalance(memberId, balance);
    await wixData.insert(TX, {
      _id: txId, memberId, type: 'spend', credits: -credits, balanceAfter: balance,
      ref: jobId, source: 'service', createdDate: new Date(),
    }, OPTS);
    return { balance };
  } finally {
    await releaseLock(memberId);
  }
}

/**
 * Refund credits (full or proportional). Idempotent on `refund_{jobId}`.
 * Called by the FastAPI worker via the post_falRefund http-function.
 */
export async function refund(memberId, credits, jobId, reason = 'job_failed') {
  if (!credits || credits <= 0) return { refunded: false, balance: await readBalance(memberId) };
  const txId = `refund_${jobId}`;
  await acquireLock(memberId);
  try {
    try {
      await wixData.insert(TX, {
        _id: txId, memberId, type: 'refund', credits, ref: jobId, source: 'service',
        reason, createdDate: new Date(),
      }, OPTS);
    } catch (dup) {
      return { refunded: false, balance: await readBalance(memberId) };
    }
    const balance = (await readBalance(memberId)) + credits;
    await writeBalance(memberId, balance);
    await wixData.update(TX, { _id: txId, memberId, type: 'refund', credits, balanceAfter: balance, ref: jobId, source: 'service', reason, createdDate: new Date() }, OPTS);
    return { refunded: true, balance };
  } finally {
    await releaseLock(memberId);
  }
}
