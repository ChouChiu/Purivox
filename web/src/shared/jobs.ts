/**
 * The job settings every reference-cancellation shell shares.
 *
 * `src/shared/jobs.py` plays the same part for the desktop: the two features
 * cannot import one another, so the values they both offer are defined once.
 */

export const STRENGTH_MINIMUM = 0;
export const STRENGTH_MAXIMUM = 100;
export const DEFAULT_STRENGTH = 75;

/**
 * The statistical window this shell fixes, matching the desktop's
 * `_GUI_REFERENCE_SIGMA_SECONDS`. Like the GUI, the browser exposes only the
 * strength and never asks the user to choose a sigma.
 */
export const SHELL_SIGMA = 3;

/** Which stems one cancellation writes. Mirrors `OutputTracks` in the Python. */
export type OutputTracks = "vocal" | "backing" | "both";
export const OUTPUT_TRACKS: readonly OutputTracks[] = [
	"vocal",
	"backing",
	"both",
];
export const VOCAL_MARKER = "_vocals";
export const BACKING_MARKER = "_backing";

/**
 * Name the backing download beside the vocal one, as `backing_path()` does on
 * the desktop. The runtime path is not reused: it carries the work directory
 * and a `result-` prefix the user should never see.
 */
export function backingName(name: string): string {
	const dot = name.lastIndexOf(".");
	const stem = dot > 0 ? name.slice(0, dot) : name;
	const suffix = dot > 0 ? name.slice(dot) : "";
	const base = stem.endsWith(VOCAL_MARKER)
		? stem.slice(0, -VOCAL_MARKER.length)
		: stem;
	return `${base}${BACKING_MARKER}${suffix}`;
}
