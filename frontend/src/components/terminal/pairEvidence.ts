import type { GroupSignalPair } from '../../services/api';

/**
 * The floor under any per-pair star-gap claim.
 *
 * `average_rating_gap` is measured over the films BOTH profiles rated —
 * `rating_overlap_count` — which is routinely a tiny fraction of
 * `shared_titles`. Sorted raw, "closest pair" was won by a pair whose 0.00
 * agreement rested on three shared ratings (the runner-up had one), while the
 * copy attributed the agreement to their 89 shared films. A coincidence over
 * three data points must not outrank a measured 0.31 over three hundred.
 *
 * The backend's alignment_score already discounts thin overlaps with a prior;
 * this is the same judgement for the panels that rank by the raw gap. Five
 * matches the evidence floors used elsewhere (decade lean, silence gaps).
 */
export const MIN_RATED_OVERLAP = 5;

/** Pairs whose star gap rests on enough shared ratings to mean something. */
export function withRatedEvidence(pairs: GroupSignalPair[]): GroupSignalPair[] {
  return pairs.filter(
    (pair) =>
      pair.average_rating_gap !== null && pair.rating_overlap_count >= MIN_RATED_OVERLAP,
  );
}
