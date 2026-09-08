import { useCallback, useEffect, useRef, useState } from "react";
import { type PurivoxClient, PurivoxError } from "./PurivoxClient";
import type { ProgressPayload } from "./protocol";

export interface JobState {
	running: boolean;
	progress: number;
	/**
	 * Milliseconds the job has taken: live while it runs, the total once it
	 * settles.  The pipeline's own progress events can be a minute apart and
	 * carry no timing, so this is measured rather than derived from them.
	 */
	elapsedMs: number;
	/** The untranslated progress key and its values, for the page to render. */
	message: ProgressPayload | null;
	failure: { message: string; kind: PurivoxError["kind"] } | null;
}

const IDLE: JobState = {
	running: false,
	progress: 0,
	elapsedMs: 0,
	message: null,
	failure: null,
};

/**
 * Run one pipeline at a time, reporting progress and surviving cancellation.
 *
 * Cancelling tears the worker down, so the promise a run is waiting on rejects
 * with a `cancelled` error rather than resolving - the same shape the desktop's
 * `ProcessingCancelled` takes through `JobRunner`.
 */
export function useJob(client: PurivoxClient) {
	const [state, setState] = useState<JobState>(IDLE);
	const running = useRef(false);
	const startedAt = useRef(0);

	useEffect(() => {
		if (!state.running) return;
		const timer = setInterval(() => {
			setState((previous) =>
				previous.running
					? { ...previous, elapsedMs: Date.now() - startedAt.current }
					: previous,
			);
		}, 100);
		return () => clearInterval(timer);
	}, [state.running]);

	const start = useCallback(
		async <T>(name: string, request: unknown): Promise<T | null> => {
			if (running.current) return null;
			running.current = true;
			startedAt.current = Date.now();
			setState({
				running: true,
				progress: 0,
				elapsedMs: 0,
				message: null,
				failure: null,
			});
			try {
				const result = await client.run<T>(name, request, (payload) => {
					setState((previous) => ({
						...previous,
						progress: payload.value,
						message: payload,
					}));
				});
				setState((previous) => ({
					...previous,
					running: false,
					progress: 100,
					elapsedMs: Date.now() - startedAt.current,
				}));
				return result;
			} catch (error) {
				const kind = error instanceof PurivoxError ? error.kind : "internal";
				const message = error instanceof Error ? error.message : String(error);
				setState({
					running: false,
					progress: 0,
					elapsedMs: Date.now() - startedAt.current,
					message: null,
					failure: { message, kind },
				});
				return null;
			} finally {
				running.current = false;
			}
		},
		[client],
	);

	const cancel = useCallback(async () => {
		if (!running.current) return;
		await client.cancel();
	}, [client]);

	const reset = useCallback(() => setState(IDLE), []);

	return { state, start, cancel, reset };
}
