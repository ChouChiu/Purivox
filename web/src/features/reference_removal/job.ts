import { sampleRate, seconds, totalBytes } from "../../shared/audio/prepare";
import type { OutputTracks } from "../../shared/jobs";
import { SHELL_SIGMA } from "../../shared/jobs";
import type { PurivoxClient } from "../../shared/runtime/PurivoxClient";
import { WORK_DIR } from "../../shared/runtime/protocol";
import type { Estimate, PreparedFile } from "../../shared/runtime/types";

/** Ask the runtime whether one single-song job fits in the browser's budget. */
export function estimate(
	client: PurivoxClient,
	stage: PreparedFile,
	source: PreparedFile,
	tracks: OutputTracks,
): Promise<Estimate> {
	return client.call<Estimate>("estimate_reference", {
		// Both are resampled onto the stage recording's timeline before anything
		// is allocated.
		sample_rate: sampleRate(stage),
		stage_seconds: seconds(stage),
		source_seconds: seconds(source),
		file_bytes: totalBytes([stage, source]),
		both_tracks: tracks === "both",
	});
}

/** The request `run_reference` takes, built from what the page collected. */
export function request(
	stage: PreparedFile,
	source: PreparedFile,
	outputName: string,
	strength: number,
	tracks: OutputTracks,
) {
	return {
		stage: stage.path,
		source: source.path,
		output: `${WORK_DIR}/result-${outputName}`,
		strength,
		sigma: SHELL_SIGMA,
		auto_align: true,
		tracks,
	};
}
