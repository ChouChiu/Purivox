/** The message contract between the page and the Pyodide worker.
 *
 * Everything the pipelines return crosses as a JSON string, because Pyodide
 * would otherwise hand the page a proxy it has to destroy by hand - and a
 * progress callback fires often enough that one leaked proxy per update
 * matters.  `src/web/bridge.py` is the other end of this contract.
 */

/** One progress update, still untranslated: the browser owns the catalogue. */
export interface ProgressPayload {
	value: number;
	key: string;
	values: Record<string, string>;
}

/** How far the runtime has got before it can accept a job. */
export interface BootPayload {
	stage: "runtime" | "packages" | "sources" | "ready";
}

/** `input` mirrors the CLI's exit-2 errors: something the user can correct. */
export type FailureKind = "input" | "cancelled" | "internal";

export type WorkerRequest =
	| { type: "boot"; id: number; pyodideUrl: string; archiveUrl: string }
	| {
			type: "write";
			id: number;
			path: string;
			bytes: ArrayBuffer;
			append: boolean;
	  }
	| { type: "read"; id: number; path: string; offset: number; length: number }
	| { type: "size"; id: number; path: string }
	| { type: "remove"; id: number; path: string }
	/** A bridge function that returns immediately. */
	| { type: "call"; id: number; name: string; request: string }
	/** A pipeline that reports progress while it runs. */
	| { type: "run"; id: number; name: string; request: string };

export type WorkerResponse =
	| { type: "booting"; payload: BootPayload }
	| { type: "progress"; id: number; payload: ProgressPayload }
	| { type: "done"; id: number; payload: string }
	| { type: "bytes"; id: number; bytes: ArrayBuffer }
	| { type: "number"; id: number; value: number }
	| {
			type: "failed";
			id: number;
			kind: FailureKind;
			message: string;
			key?: string;
	  };

/** Python exception names the CLI treats as the user's to fix, not a defect. */
export const INPUT_ERRORS = new Set([
	"ValueError",
	"KeyError",
	"FileNotFoundError",
]);
