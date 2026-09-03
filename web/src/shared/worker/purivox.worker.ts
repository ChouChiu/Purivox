/// <reference lib="webworker" />
import {
	type FailureKind,
	INPUT_ERRORS,
	type WorkerRequest,
	type WorkerResponse,
} from "../runtime/protocol";
import {
	type EmscriptenStream,
	loadPyodideFrom,
	type PyodideInterface,
	type PyProxy,
} from "./pyodide";

/** Where uploads land and where results are written, inside Pyodide's filesystem. */
const WORK_DIR = "/work";
/** Where the packed Python tree is unpacked, and what goes on `sys.path`. */
const SOURCE_DIR = "/purivox";

// The pipelines reach the page through one dispatcher rather than through a
// proxy per function, so the worker holds exactly two proxies for its lifetime.
const DISPATCHER = `
import sys

if ${JSON.stringify(SOURCE_DIR)} not in sys.path:
    sys.path.insert(0, ${JSON.stringify(SOURCE_DIR)})

import logging

from web import bridge

logging.getLogger().setLevel(logging.WARNING)


def _call(name, request):
    return getattr(bridge, name)(request)


def _run(name, request, on_progress):
    return getattr(bridge, name)(request, on_progress)
`;

let pyodide: PyodideInterface | null = null;
let call: PyProxy | null = null;
let run: PyProxy | null = null;
/** Uploads in flight, kept open so a chunked file is allocated exactly once. */
const writing = new Map<string, EmscriptenStream>();

function post(message: WorkerResponse, transfer: Transferable[] = []): void {
	self.postMessage(message, transfer);
}

function runtime(): PyodideInterface {
	if (pyodide === null) {
		throw new Error("the runtime has not booted yet");
	}
	return pyodide;
}

async function boot(pyodideUrl: string, archiveUrl: string): Promise<void> {
	// Nothing about the archive depends on Pyodide being up, so it travels
	// alongside the runtime download rather than waiting its turn behind it.
	const archive = fetch(archiveUrl);
	// The await further down is what consumes a failure; this only keeps the
	// runtime from reporting it as unhandled while the interpreter still loads.
	archive.catch(() => {});

	post({ type: "booting", payload: { stage: "runtime" } });
	pyodide = await loadPyodideFrom(pyodideUrl);

	post({ type: "booting", payload: { stage: "packages" } });
	// soundfile brings libsndfile with the FLAC, Ogg/Vorbis, Opus and MP3 codecs
	// compiled in, so the browser decodes everything the desktop does except the
	// containers libsndfile itself turns down.
	await pyodide.loadPackage(["numpy", "scipy", "soundfile", "soxr"]);

	post({ type: "booting", payload: { stage: "sources" } });
	const response = await archive;
	if (!response.ok) {
		throw new Error(`could not fetch the Python sources: ${response.status}`);
	}
	pyodide.unpackArchive(await response.arrayBuffer(), "zip", {
		extractDir: SOURCE_DIR,
	});
	pyodide.FS.mkdirTree(WORK_DIR);
	pyodide.runPython(DISPATCHER);
	call = pyodide.globals.get("_call");
	run = pyodide.globals.get("_run");

	post({ type: "booting", payload: { stage: "ready" } });
}

function close(path: string): void {
	const stream = writing.get(path);
	if (stream === undefined) return;
	runtime().FS.close(stream);
	writing.delete(path);
}

function write(
	path: string,
	bytes: ArrayBuffer,
	offset: number,
	total: number,
): void {
	const fs = runtime().FS;
	let stream = writing.get(path);
	if (stream === undefined) {
		stream = fs.open(path, "w");
		// Appending to an Emscripten file reallocates it and copies back
		// everything written so far, and it grows by an eighth at a time: a long
		// recording arriving in slices would be copied through dozens of times.
		// One allocation up front, then every slice straight into its offset.
		fs.truncate(path, total);
		writing.set(path, stream);
	}
	const view = new Uint8Array(bytes);
	fs.write(stream, view, 0, view.length, offset);
	if (offset + view.length >= total) close(path);
}

function read(path: string, offset: number, length: number): ArrayBuffer {
	const fs = runtime().FS;
	const stream = fs.open(path, "r");
	try {
		const buffer = new Uint8Array(length);
		const read = fs.read(stream, buffer, 0, length, offset);
		// A full slice is handed over as it stands; only a short one at the end
		// of a file has to be trimmed, and trimming copies.
		return read === length ? buffer.buffer : buffer.buffer.slice(0, read);
	} finally {
		fs.close(stream);
	}
}

function describe(error: unknown): { kind: FailureKind; message: string } {
	// Pyodide raises a PythonError carrying the exception's class name, which is
	// how the CLI decides between an exit code of 2 and 1 for the same pipelines.
	const type = (error as { type?: string } | null)?.type;
	const message = error instanceof Error ? error.message : String(error);
	return {
		kind: type !== undefined && INPUT_ERRORS.has(type) ? "input" : "internal",
		message,
	};
}

async function handle(request: WorkerRequest): Promise<void> {
	switch (request.type) {
		case "boot":
			await boot(request.pyodideUrl, request.archiveUrl);
			post({ type: "done", id: request.id, payload: "{}" });
			return;
		case "write":
			write(request.path, request.bytes, request.offset, request.total);
			post({ type: "done", id: request.id, payload: "{}" });
			return;
		case "read": {
			const bytes = read(request.path, request.offset, request.length);
			post({ type: "bytes", id: request.id, bytes }, [bytes]);
			return;
		}
		case "size":
			post({
				type: "number",
				id: request.id,
				value: runtime().FS.stat(request.path).size,
			});
			return;
		case "remove": {
			const fs = runtime().FS;
			close(request.path);
			if (fs.analyzePath(request.path).exists) {
				fs.unlink(request.path);
			}
			post({ type: "done", id: request.id, payload: "{}" });
			return;
		}
		case "call": {
			if (call === null) throw new Error("the runtime has not booted yet");
			post({
				type: "done",
				id: request.id,
				payload: call(request.name, request.request) as string,
			});
			return;
		}
		case "run": {
			if (run === null) throw new Error("the runtime has not booted yet");
			const report = (payload: string) => {
				post({
					type: "progress",
					id: request.id,
					payload: JSON.parse(payload),
				});
			};
			post({
				type: "done",
				id: request.id,
				payload: run(request.name, request.request, report) as string,
			});
			return;
		}
	}
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
	const request = event.data;
	try {
		await handle(request);
	} catch (error) {
		const { kind, message } = describe(error);
		post({ type: "failed", id: request.id, kind, message });
	}
};
