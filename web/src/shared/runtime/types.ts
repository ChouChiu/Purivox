/** Mirrors of what `src/web/bridge.py` returns, one per JSON payload. */

export interface Probe {
	supported: boolean;
	sample_rate?: number;
	channels?: number;
	frames?: number;
	seconds?: number;
	format?: string;
	subtype?: string;
	reason?: string;
}

export interface Estimate {
	peak_bytes: number;
	budget_bytes: number;
	fits: boolean;
	tight: boolean;
	fraction: number;
}

export interface AudioStats {
	duration_seconds: number;
	sample_rate: number;
	channels: number;
	bit_depth: number;
	peak_dbfs: number | null;
	rms_dbfs: number | null;
	file_size: number;
}

export type ClipKind = "song" | "fragment" | "unmatched";

export interface TimelineClip {
	kind: ClipKind;
	stage_start: number;
	stage_end: number;
	source: string | null;
	source_index: number | null;
	source_start: number;
	source_end: number;
	confidence: number;
	enabled: boolean;
	manual: boolean;
}

export interface Analysis {
	duration_seconds: number;
	clips: TimelineClip[];
	missing_sources: string[];
}

export interface ReferenceResult {
	outputs: string[];
	audio_stats: AudioStats[];
}

export interface AnalysisResult {
	analysis: Analysis;
}

export interface RenderResult extends ReferenceResult {
	analysis: Analysis;
}

/** One file the page has put into the runtime, with what its header said. */
export interface PreparedFile {
	/** The original picked file's name, for labels. */
	label: string;
	/** Where it lives inside the Pyodide filesystem. */
	path: string;
	probe: Probe;
	/** How many bytes it occupies in the runtime, which is memory, not disk. */
	bytes: number;
}
