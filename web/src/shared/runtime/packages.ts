/**
 * What a first visit downloads, and what it costs.
 *
 * Pyodide's lock file carries no sizes, so these were measured against the
 * pinned CDN build with `curl --compressed`. They are only used to tell the
 * visitor what they are waiting for - nothing computes a progress bar from
 * them, because a percentage derived from guesses is worse than none.
 */
export const RUNTIME_PACKAGES = [
	"numpy",
	"scipy",
	"soundfile",
	"soxr",
] as const;

/** Compressed bytes over the wire: runtime 5.7 MB + wheels 16.9 MB. */
export const FIRST_VISIT_MEGABYTES = 23;
