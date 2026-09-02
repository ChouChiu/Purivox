/**
 * A played length, as `MM:SS` or `H:MM:SS`.
 *
 * This is the preview and statistics clock, which the desktop spells privately
 * as `MrPage._clock`. The full-stage timeline keeps its own clock instead: an
 * editable time range needs milliseconds, and a duration label does not.
 */
export function duration(seconds: number): string {
	const whole = Math.max(0, Math.round(seconds));
	const secs = whole % 60;
	const minutes = Math.floor(whole / 60) % 60;
	const hours = Math.floor(whole / 3600);
	const tail = `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
	return hours > 0 ? `${hours}:${tail}` : tail;
}
