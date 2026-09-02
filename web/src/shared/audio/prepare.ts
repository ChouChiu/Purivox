import type { PurivoxClient } from "../runtime/PurivoxClient";
import type { PreparedFile, Probe } from "../runtime/types";
import { decodeToWav } from "./decode";

/** Strip anything that would make a name ambiguous inside the work directory. */
function safeName(name: string, index: number): string {
	const cleaned = name.replace(/[^\w.-]+/g, "_").slice(-96);
	return `${index}-${cleaned || "audio"}`;
}

/**
 * Put one picked file into the runtime and read back what its header says.
 *
 * A container libsndfile turns down is decoded by the browser and re-uploaded
 * as a WAV, which is the same two-decoder arrangement `read_audio` uses on the
 * desktop - libsndfile first, the platform decoder for what is left.
 */
export async function prepare(
	client: PurivoxClient,
	file: File,
	index: number,
	onProgress?: (fraction: number) => void,
): Promise<PreparedFile> {
	let uploaded = file;
	let path = await client.upload(
		uploaded,
		safeName(uploaded.name, index),
		onProgress,
	);
	let probe = await client.call<Probe>("probe_audio", { path });

	if (!probe.supported) {
		await client.remove(path);
		uploaded = await decodeToWav(file);
		path = await client.upload(
			uploaded,
			safeName(uploaded.name, index),
			onProgress,
		);
		probe = await client.call<Probe>("probe_audio", { path });
		if (!probe.supported) {
			throw new Error(probe.reason ?? `no decoder could read ${file.name}`);
		}
	}

	return { label: file.name, path, probe, bytes: uploaded.size };
}

export function totalBytes(files: PreparedFile[]): number {
	return files.reduce((sum, file) => sum + file.bytes, 0);
}

export function seconds(file: PreparedFile): number {
	return file.probe.seconds ?? 0;
}

/** The rate a job allocates at, which is the one its primary input arrived at. */
export function sampleRate(file: PreparedFile): number {
	return file.probe.sample_rate ?? 44_100;
}

/** `1.4 GB`, for a message about memory rather than a byte count. */
export function formatBytes(bytes: number): string {
	const units = ["B", "KB", "MB", "GB"];
	let value = bytes;
	let unit = 0;
	while (value >= 1024 && unit < units.length - 1) {
		value /= 1024;
		unit += 1;
	}
	return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}
