/** The slice of the Pyodide API this worker uses.
 *
 * Pyodide is loaded from a CDN rather than bundled: the runtime with numpy and
 * scipy is tens of megabytes, which is not something a GitHub Pages repository
 * should carry.  These declarations stand in for the package's own types.
 */

export interface EmscriptenStream {
	readonly fd: number;
}

export interface EmscriptenFS {
	mkdirTree(path: string): void;
	open(path: string, flags: string): EmscriptenStream;
	close(stream: EmscriptenStream): void;
	read(
		stream: EmscriptenStream,
		buffer: Uint8Array,
		offset: number,
		length: number,
	): number;
	write(
		stream: EmscriptenStream,
		buffer: Uint8Array,
		offset: number,
		length: number,
	): number;
	llseek(stream: EmscriptenStream, offset: number, whence: number): void;
	stat(path: string): { size: number };
	unlink(path: string): void;
	analyzePath(path: string): { exists: boolean };
}

export interface PyProxy {
	(...args: unknown[]): unknown;
	destroy(): void;
}

export interface PyodideInterface {
	FS: EmscriptenFS;
	globals: { get(name: string): PyProxy };
	loadPackage(names: string[]): Promise<void>;
	runPython(code: string): unknown;
	unpackArchive(
		buffer: ArrayBuffer,
		format: string,
		options?: { extractDir?: string },
	): void;
}

interface PyodideModule {
	loadPyodide(options: { indexURL: string }): Promise<PyodideInterface>;
}

export async function loadPyodideFrom(url: string): Promise<PyodideInterface> {
	const module = (await import(/* @vite-ignore */ url)) as PyodideModule;
	// The loader resolves the wasm binary and the package index relative to this.
	return module.loadPyodide({
		indexURL: url.slice(0, url.lastIndexOf("/") + 1),
	});
}
