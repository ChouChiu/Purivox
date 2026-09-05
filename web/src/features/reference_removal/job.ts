import { sampleRate, seconds, totalBytes } from "../../shared/audio/prepare";
import type { OutputTracks } from "../../shared/jobs";
import { SHELL_SIGMA } from "../../shared/jobs";
import type { PurivoxClient } from "../../shared/runtime/PurivoxClient";
import { WORK_DIR } from "../../shared/runtime/PurivoxClient";
import type { Estimate, PreparedFile } from "../../shared/runtime/types";

/** Ask the runtime whether one single-song job fits in the browser's budget. */
export function estimate(
	client: PurivoxClient,
	song: PreparedFile,
	accompaniment: PreparedFile,
	tracks: OutputTracks,
): Promise<Estimate> {
	return client.call<Estimate>("estimate_reference", {
		// Both are resampled onto the song's timeline before anything is allocated.
		sample_rate: sampleRate(song),
		song_seconds: seconds(song),
		accompaniment_seconds: seconds(accompaniment),
		file_bytes: totalBytes([song, accompaniment]),
		both_tracks: tracks === "both",
	});
}

/** The request `run_reference` takes, built from what the page collected. */
export function request(
	song: PreparedFile,
	accompaniment: PreparedFile,
	outputName: string,
	strength: number,
	tracks: OutputTracks,
) {
	return {
		song: song.path,
		accompaniment: accompaniment.path,
		output: `${WORK_DIR}/result-${outputName}`,
		strength,
		sigma: SHELL_SIGMA,
		auto_align: true,
		tracks,
	};
}
