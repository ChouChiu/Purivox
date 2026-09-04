/**
 * What a first visit costs, in compressed bytes over the wire: the Pyodide
 * runtime at 5.7 MB plus the numpy, scipy, soundfile and soxr wheels at
 * 16.9 MB.
 *
 * Pyodide's lock file carries no sizes, so this was measured against the
 * pinned CDN build with `curl --compressed`. It only tells the visitor what
 * they are waiting for - nothing computes a progress bar from it, because a
 * percentage derived from guesses is worse than none.
 */
export const FIRST_VISIT_MEGABYTES = 23;
