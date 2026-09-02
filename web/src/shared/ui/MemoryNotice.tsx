import { MessageBar, MessageBarBody } from "@fluentui/react-components";
import { formatBytes } from "../audio/prepare";
import { useLanguage } from "../i18n/context";
import type { Estimate } from "../runtime/types";

/**
 * Say when a job will not fit in a browser tab.
 *
 * wasm32 caps the heap at 4 GB and Emscripten's temporary filesystem lives
 * inside it, so the memory-mapped buffers the pipelines rely on stay resident
 * here. `src/web/limits.py` owns the arithmetic; this only renders the verdict.
 */
export function MemoryNotice({ estimate }: { estimate: Estimate | null }) {
	const { t } = useLanguage();
	if (estimate === null || (estimate.fits && !estimate.tight)) return null;
	const values = {
		peak: formatBytes(estimate.peak_bytes),
		budget: formatBytes(estimate.budget_bytes),
	};
	return (
		<MessageBar intent={estimate.fits ? "warning" : "error"}>
			<MessageBarBody>
				{t(estimate.fits ? "web_memory_tight" : "web_memory_refuse", values)}
			</MessageBarBody>
		</MessageBar>
	);
}
