import type {
	BootPayload,
	ProgressPayload,
	WorkerRequest,
	WorkerResponse,
} from "./protocol";

/** Pinned so a Pyodide release never changes the pipeline under a visitor. */
export const PYODIDE_URL =
	"https://cdn.jsdelivr.net/pyodide/v314.0.6/full/pyodide.mjs";
/**
 * Uploads are streamed in slices this size, so no whole file is ever copied.
 *
 * Four megabytes keeps the peak small and still gives an ordinary song half a
 * dozen progress steps rather than one.
 */
export const CHUNK_BYTES = 4 * 1024 * 1024;
export const WORK_DIR = "/work";

export class PurivoxError extends Error {
	constructor(
		message: string,
		readonly kind: "input" | "cancelled" | "internal",
	) {
		super(message);
		this.name = "PurivoxError";
	}
}

interface Pending {
	resolve(value: WorkerResponse): void;
	reject(error: PurivoxError): void;
	onProgress?: (payload: ProgressPayload) => void;
}

/**
 * Owns the worker that runs the pipelines, and its cancellation.
 *
 * Cancelling means terminating the worker and booting a fresh one. Pyodide runs
 * the pipeline synchronously on the worker's only thread, so a busy run cannot
 * read a message; the cooperative `CancellationToken` the desktop uses would
 * need a `SharedArrayBuffer`, and GitHub Pages cannot send the COOP/COEP
 * headers that unlocks. Rebooting costs a few seconds and always works.
 */
export class PurivoxClient {
	private worker: Worker | null = null;
	private booted: Promise<void> | null = null;
	private pending = new Map<number, Pending>();
	private nextId = 1;
	/**
	 * What the runtime's filesystem holds, so a reboot can put it back.
	 *
	 * Terminating the worker takes Emscripten's filesystem with it, but the page
	 * still holds the paths it was given. A `File` is a reference to something
	 * the browser already has on disk, so keeping one costs nothing and saves the
	 * user from picking the same audio again after every cancellation.
	 */
	private uploaded = new Map<string, File>();

	constructor(
		private readonly archiveUrl: string,
		private readonly onBoot: (payload: BootPayload) => void = () => {},
	) {}

	/** Boot the runtime, reusing the one already running. */
	async ready(): Promise<void> {
		if (this.booted === null) {
			this.booted = this.start();
		}
		await this.booted;
	}

	private async start(): Promise<void> {
		const worker = new Worker(
			new URL("../worker/purivox.worker.ts", import.meta.url),
			{
				type: "module",
			},
		);
		worker.onmessage = (event: MessageEvent<WorkerResponse>) =>
			this.receive(event.data);
		worker.onerror = (event) =>
			this.failAll(new PurivoxError(event.message, "internal"));
		this.worker = worker;
		await this.send({
			type: "boot",
			id: 0,
			pyodideUrl: PYODIDE_URL,
			archiveUrl: this.archiveUrl,
		});
	}

	private receive(message: WorkerResponse): void {
		if (message.type === "booting") {
			this.onBoot(message.payload);
			return;
		}
		const pending = this.pending.get(message.id);
		if (pending === undefined) return;
		if (message.type === "progress") {
			pending.onProgress?.(message.payload);
			return;
		}
		this.pending.delete(message.id);
		if (message.type === "failed") {
			pending.reject(new PurivoxError(message.message, message.kind));
		} else {
			pending.resolve(message);
		}
	}

	private failAll(error: PurivoxError): void {
		for (const pending of this.pending.values()) {
			pending.reject(error);
		}
		this.pending.clear();
	}

	private send(
		request: WorkerRequest,
		onProgress?: (payload: ProgressPayload) => void,
		transfer: Transferable[] = [],
	): Promise<WorkerResponse> {
		const worker = this.worker;
		if (worker === null) {
			return Promise.reject(
				new PurivoxError("the runtime is not running", "internal"),
			);
		}
		return new Promise<WorkerResponse>((resolve, reject) => {
			this.pending.set(request.id, { resolve, reject, onProgress });
			worker.postMessage(request, transfer);
		});
	}

	/** Throw the runtime away without booting another; `ready()` starts a new one. */
	reset(): void {
		this.worker?.terminate();
		this.worker = null;
		this.booted = null;
		this.failAll(new PurivoxError("cancelled", "cancelled"));
	}

	/** Stop whatever is running, bring a fresh runtime up and refill it. */
	async cancel(): Promise<void> {
		this.reset();
		await this.ready();
		for (const [path, file] of this.uploaded) {
			await this.writeInto(path, file);
		}
	}

	private async writeInto(
		path: string,
		file: File,
		onProgress?: (fraction: number) => void,
	): Promise<void> {
		await this.send({ type: "remove", id: this.nextId++, path });
		for (let offset = 0; offset < file.size; offset += CHUNK_BYTES) {
			const slice = await file
				.slice(offset, offset + CHUNK_BYTES)
				.arrayBuffer();
			await this.send(
				{
					type: "write",
					id: this.nextId++,
					path,
					bytes: slice,
					append: offset > 0,
				},
				undefined,
				[slice],
			);
			onProgress?.(Math.min(1, (offset + CHUNK_BYTES) / file.size));
		}
	}

	/** Copy one picked file into the runtime without ever holding all of it. */
	async upload(
		file: File,
		name: string,
		onProgress?: (fraction: number) => void,
	): Promise<string> {
		await this.ready();
		const path = `${WORK_DIR}/${name}`;
		await this.writeInto(path, file, onProgress);
		this.uploaded.set(path, file);
		return path;
	}

	/** Read a result back as a Blob, one slice at a time for the same reason. */
	async download(path: string, type = "audio/wav"): Promise<Blob> {
		await this.ready();
		const sized = await this.send({ type: "size", id: this.nextId++, path });
		const size = sized.type === "number" ? sized.value : 0;
		const parts: ArrayBuffer[] = [];
		for (let offset = 0; offset < size; offset += CHUNK_BYTES) {
			const length = Math.min(CHUNK_BYTES, size - offset);
			const chunk = await this.send({
				type: "read",
				id: this.nextId++,
				path,
				offset,
				length,
			});
			if (chunk.type === "bytes") parts.push(chunk.bytes);
		}
		return new Blob(parts, { type });
	}

	async remove(path: string): Promise<void> {
		await this.ready();
		this.uploaded.delete(path);
		await this.send({ type: "remove", id: this.nextId++, path });
	}

	/** Call a bridge function that returns straight away. */
	async call<T>(name: string, request: unknown): Promise<T> {
		await this.ready();
		const done = await this.send({
			type: "call",
			id: this.nextId++,
			name,
			request: JSON.stringify(request),
		});
		return JSON.parse(done.type === "done" ? done.payload : "{}") as T;
	}

	/** Run a pipeline, reporting progress until it finishes. */
	async run<T>(
		name: string,
		request: unknown,
		onProgress?: (payload: ProgressPayload) => void,
	): Promise<T> {
		await this.ready();
		const done = await this.send(
			{
				type: "run",
				id: this.nextId++,
				name,
				request: JSON.stringify(request),
			},
			onProgress,
		);
		return JSON.parse(done.type === "done" ? done.payload : "{}") as T;
	}
}
