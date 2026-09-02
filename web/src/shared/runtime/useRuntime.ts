import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PurivoxClient } from "./PurivoxClient";
import type { BootPayload } from "./protocol";

export type BootStage = BootPayload["stage"] | "idle";

export const BOOT_KEYS: Record<BootStage, string> = {
	idle: "web_boot_runtime",
	runtime: "web_boot_runtime",
	packages: "web_boot_packages",
	sources: "web_boot_sources",
	ready: "ready",
};

/** Roughly how far through startup each stage is, for a four-step bar. */
const BOOT_FRACTION: Record<BootStage, number> = {
	idle: 0,
	runtime: 0.1,
	packages: 0.35,
	sources: 0.9,
	ready: 1,
};

export interface Runtime {
	client: PurivoxClient;
	stage: BootStage;
	fraction: number;
	ready: boolean;
	failure: string | null;
	retry(): void;
}

/**
 * One runtime for the whole page.
 *
 * Booting it downloads the interpreter, numpy and scipy, so both pages share
 * it, and cancelling replaces it in place rather than making another.
 */
export function useRuntime(): Runtime {
	const [stage, setStage] = useState<BootStage>("idle");
	const [failure, setFailure] = useState<string | null>(null);
	const report = useRef(setStage);
	report.current = setStage;

	const client = useMemo(
		() =>
			new PurivoxClient(
				`${import.meta.env.BASE_URL}purivox-src.zip`,
				(payload) => report.current(payload.stage),
			),
		[],
	);

	const boot = useCallback(() => {
		setFailure(null);
		client.ready().catch((error: unknown) => {
			setFailure(error instanceof Error ? error.message : String(error));
		});
	}, [client]);

	useEffect(boot, [boot]);

	const retry = useCallback(() => {
		setStage("idle");
		// A failed boot may have left a half-started worker; drop it first.
		client.reset();
		boot();
	}, [boot, client]);

	return {
		client,
		stage,
		fraction: BOOT_FRACTION[stage],
		ready: stage === "ready",
		failure,
		retry,
	};
}
