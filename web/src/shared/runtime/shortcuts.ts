import { useEffect } from "react";

/**
 * The window shortcuts, which live here rather than on a page.
 *
 * The desktop keeps them on `MainWindow` for the same reason: three page-local
 * `Ctrl+O` bindings would be an ambiguous overload, and a window shortcut works
 * before a page has taken focus.
 */
export interface Shortcuts {
	/** Ctrl+O - open the primary file picker. */
	choose?(): void;
	/** Ctrl+Enter - start the page's main job. */
	start?(): void;
	/** Escape - cancel a running job. */
	cancel?(): void;
	/** F5 - find songs, on the full-stage page only. */
	analyze?(): void;
	/** Ctrl+P - play or pause the result preview. */
	togglePreview?(): void;
}

function isTyping(target: EventTarget | null): boolean {
	if (!(target instanceof HTMLElement)) return false;
	// A time range being edited in the timeline owns Escape and Enter itself.
	return (
		target.isContentEditable ||
		["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)
	);
}

export function useShortcuts(shortcuts: Shortcuts): void {
	useEffect(() => {
		function onKeyDown(event: KeyboardEvent) {
			const typing = isTyping(event.target);
			const control = event.ctrlKey || event.metaKey;
			let action: (() => void) | undefined;
			if (control && event.key === "o") action = shortcuts.choose;
			else if (control && event.key === "Enter") action = shortcuts.start;
			else if (event.key === "Escape" && !typing) action = shortcuts.cancel;
			else if (event.key === "F5" && !control) action = shortcuts.analyze;
			else if (control && event.key === "p") action = shortcuts.togglePreview;
			if (action === undefined) return;
			event.preventDefault();
			action();
		}
		window.addEventListener("keydown", onKeyDown);
		return () => window.removeEventListener("keydown", onKeyDown);
	}, [shortcuts]);
}
