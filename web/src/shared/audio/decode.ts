/**
 * The browser's decoder, for the containers libsndfile turns down.
 *
 * libsndfile handles WAV, FLAC, Ogg/Vorbis, Opus and MP3, so this is reached
 * almost only for AAC in an MP4 container. It plays the part the Qt Multimedia
 * fallback plays on the desktop: decode with the platform, hand the pipeline a
 * WAV. Unlike that one it has to hold the decoded audio in memory, so it is
 * used only after the header probe says libsndfile cannot.
 */

/** 32-bit float WAV, which is what `decodeAudioData` already gives us. */
const FORMAT_IEEE_FLOAT = 3;
const BYTES_PER_SAMPLE = 4;

function writeAscii(view: DataView, offset: number, text: string): void {
	for (let index = 0; index < text.length; index += 1) {
		view.setUint8(offset + index, text.charCodeAt(index));
	}
}

/** Wrap decoded planar channels as an interleaved float WAV. */
export function encodeWav(channels: Float32Array[], sampleRate: number): Blob {
	const count = channels.length;
	const frames = count > 0 ? channels[0].length : 0;
	const dataBytes = frames * count * BYTES_PER_SAMPLE;
	const header = new ArrayBuffer(44);
	const view = new DataView(header);

	writeAscii(view, 0, "RIFF");
	view.setUint32(4, 36 + dataBytes, true);
	writeAscii(view, 8, "WAVE");
	writeAscii(view, 12, "fmt ");
	view.setUint32(16, 16, true);
	view.setUint16(20, FORMAT_IEEE_FLOAT, true);
	view.setUint16(22, count, true);
	view.setUint32(24, sampleRate, true);
	view.setUint32(28, sampleRate * count * BYTES_PER_SAMPLE, true);
	view.setUint16(32, count * BYTES_PER_SAMPLE, true);
	view.setUint16(34, 8 * BYTES_PER_SAMPLE, true);
	writeAscii(view, 36, "data");
	view.setUint32(40, dataBytes, true);

	const interleaved = new Float32Array(frames * count);
	for (let channel = 0; channel < count; channel += 1) {
		const samples = channels[channel];
		for (let frame = 0; frame < frames; frame += 1) {
			interleaved[frame * count + channel] = samples[frame];
		}
	}
	return new Blob([header, interleaved.buffer], { type: "audio/wav" });
}

/** Decode one file with the browser and re-encode it as a WAV the pipeline reads. */
export async function decodeToWav(file: File): Promise<File> {
	const context = new OfflineAudioContext({ length: 1, sampleRate: 44_100 });
	let buffer: AudioBuffer;
	try {
		buffer = await context.decodeAudioData(await file.arrayBuffer());
	} catch (error) {
		throw new Error(
			`the browser could not decode ${file.name}: ${String(error)}`,
		);
	}
	const channels: Float32Array[] = [];
	for (let channel = 0; channel < buffer.numberOfChannels; channel += 1) {
		channels.push(buffer.getChannelData(channel));
	}
	const wav = encodeWav(channels, buffer.sampleRate);
	const name = `${file.name.replace(/\.[^.]+$/, "")}.decoded.wav`;
	return new File([wav], name, { type: "audio/wav" });
}
