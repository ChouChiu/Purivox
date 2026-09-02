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
