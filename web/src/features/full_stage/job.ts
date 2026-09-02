import { sampleRate, seconds, totalBytes } from "../../shared/audio/prepare";
import { SHELL_SIGMA } from "../../shared/jobs";
import type { PurivoxClient } from "../../shared/runtime/PurivoxClient";
import { WORK_DIR } from "../../shared/runtime/PurivoxClient";
import type { Estimate, PreparedFile } from "../../shared/runtime/types";

/** Ask the runtime whether one full-stage render fits in the browser's budget. */
export function estimate(
	client: PurivoxClient,
	stage: PreparedFile,
	sources: PreparedFile[],
): Promise<Estimate> {
	return client.call<Estimate>("estimate_full_stage", {
		sample_rate: sampleRate(stage),
		stage_seconds: seconds(stage),
		longest_source_seconds: Math.max(0, ...sources.map(seconds)),
		file_bytes: totalBytes([stage, ...sources]),
	});
}

/** The request both `analyze_stage` and `render_stage` are built from. */
export function request(
	stage: PreparedFile | null,
	sources: PreparedFile[],
	outputName: string,
	strength: number,
	includeFragments: boolean,
) {
	return {
		stage: stage?.path ?? "",
		sources: sources.map((source) => source.path),
		output: `${WORK_DIR}/result-${outputName}`,
		strength,
		sigma: SHELL_SIGMA,
		include_fragments: includeFragments,
		auto_align: true,
	};
}
