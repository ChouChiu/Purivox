import {
	type Theme,
	webDarkTheme,
	webLightTheme,
} from "@fluentui/react-components";

export type ThemeChoice = "auto" | "light" | "dark";

const STORAGE_KEY = "purivox.theme";

export function readTheme(): ThemeChoice {
	try {
		const stored = localStorage.getItem(STORAGE_KEY);
		if (stored === "light" || stored === "dark" || stored === "auto")
			return stored;
	} catch {
		// A private window can refuse storage; following the system is a fine default.
	}
	return "auto";
}

export function storeTheme(choice: ThemeChoice): void {
	try {
		localStorage.setItem(STORAGE_KEY, choice);
	} catch {
		// Remembering the choice is a convenience, not a requirement.
	}
}

export function resolveTheme(choice: ThemeChoice, prefersDark: boolean): Theme {
	if (choice === "auto") return prefersDark ? webDarkTheme : webLightTheme;
	return choice === "dark" ? webDarkTheme : webLightTheme;
}
