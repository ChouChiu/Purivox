/**
 * Stage and source times, in the format the timeline is edited in.
 *
 * The desktop spells these in `features/full_stage/timeline_model.py`, which
 * imports Qt and so cannot be shared with the browser. They are presentation,
 * not the algorithm - the analysis itself crosses as seconds.
 */

const RANGE_SEPARATOR = /\s+-\s+/;

/** `2:03:04.500`, dropping the hour when the time is under one. */
export function clock(seconds: number): string {
	const milliseconds = Math.max(0, Math.round(seconds * 1000));
	const whole = Math.floor(milliseconds / 1000);
	const millis = milliseconds % 1000;
	const secs = whole % 60;
	const minutes = Math.floor(whole / 60) % 60;
	const hours = Math.floor(whole / 3600);
	const prefix =
		hours > 0
			? `${hours}:${String(minutes).padStart(2, "0")}`
			: String(minutes).padStart(2, "0");
	return `${prefix}:${String(secs).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

export function parseClock(text: string): number {
	const parts = text.trim().split(":");
	if (parts.length < 1 || parts.length > 3) throw new Error("invalid time");
	const values = parts.map((part) => {
		const value = Number(part.trim());
		if (!Number.isFinite(value) || value < 0) throw new Error("invalid time");
		return value;
	});
	if (values.length === 1) return values[0];
	if (values.length === 2) return values[0] * 60 + values[1];
	return values[0] * 3600 + values[1] * 60 + values[2];
}

export function parseRange(text: string): [number, number] {
	const parts = text.trim().split(RANGE_SEPARATOR);
	if (parts.length !== 2)
		throw new Error("time range must contain a separated dash");
	const start = parseClock(parts[0]);
	const end = parseClock(parts[1]);
	if (end <= start) throw new Error("time range must be positive");
	return [start, end];
}

export function formatRange(start: number, end: number): string {
	return `${clock(start)} - ${clock(end)}`;
}
