import { sampleRate, seconds, totalBytes } from "../../shared/audio/prepare";
import type { OutputTracks } from "../../shared/jobs";
import { SHELL_SIGMA } from "../../shared/jobs";
import type { PurivoxClient } from "../../shared/runtime/PurivoxClient";
import { WORK_DIR } from "../../shared/runtime/protocol";
import type {
	AnalysisResult,
	Estimate,
	PreparedFile,
} from "../../shared/runtime/types";

/** The `useJob().start` shape, so Find songs runs through the shared panel. */
type StartJob = <T>(name: string, request: unknown) => Promise<T | null>;

/** Ask the runtime whether one isolation job fits in the browser's budget. */
export function estimate(
	client: PurivoxClient,
	stage: PreparedFile,
	sources: PreparedFile[],
	tracks: OutputTracks,
): Promise<Estimate> {
	return client.call<Estimate>("estimate_isolation", {
		sample_rate: sampleRate(stage),
		stage_seconds: seconds(stage),
		longest_source_seconds: Math.max(0, ...sources.map(seconds)),
		file_bytes: totalBytes([stage, ...sources]),
		tracks,
	});
}

/**
 * The request `analyze_stage` and `run_isolation` are both built from.
 *
 * `analysis` is deliberately absent: the page adds it only when it holds one,
 * which is the same choice `MrPage.analysis` makes for the desktop.
 */
export function request(
	stage: PreparedFile | null,
	sources: PreparedFile[],
	outputName: string,
	strength: number,
	tracks: OutputTracks,
) {
	return {
		stage: stage?.path ?? "",
		sources: sources.map((source) => source.path),
		output: `${WORK_DIR}/result-${outputName}`,
		strength,
		sigma: SHELL_SIGMA,
		auto_align: true,
		tracks,
	};
}

/** Match the sources against the recording without cancelling anything. */
export function analyze(
	start: StartJob,
	payload: unknown,
): Promise<AnalysisResult | null> {
	return start<AnalysisResult>("analyze_stage", payload);
}
