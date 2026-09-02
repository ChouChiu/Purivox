export const LANGUAGES = ["zh_cn", "en_us", "ja_jp", "ko_kr"] as const;
export type Language = (typeof LANGUAGES)[number];
export const DEFAULT_LANGUAGE: Language = "zh_cn";

export const LANGUAGE_NAMES: Record<Language, string> = {
	zh_cn: "简体中文",
	en_us: "English",
	ja_jp: "日本語",
	ko_kr: "한국어",
};

export type Catalogue = Record<string, string>;
export type Translate = (
	key: string,
	values?: Record<string, unknown>,
) => string;

const loaded = new Map<Language, Promise<Catalogue>>();

/** Read one catalogue, built from the same `.ts` sources the desktop compiles. */
export function loadCatalogue(language: Language): Promise<Catalogue> {
	const cached = loaded.get(language);
	if (cached !== undefined) return cached;
	const request = fetch(
		`${import.meta.env.BASE_URL}i18n/${language}.json`,
	).then((response) => {
		if (!response.ok)
			throw new Error(`could not load the ${language} catalogue`);
		return response.json() as Promise<Catalogue>;
	});
	loaded.set(language, request);
	return request;
}

/**
 * Resolve one key, filling its placeholders.
 *
 * This matches `shared.i18n.tr`, including the part that matters most here: an
 * unknown key resolves to itself, which keeps a missing string visible rather
 * than blank. Pipeline progress arrives as a key because the browser build has
 * no Qt catalogue to translate it against.
 */
export function translateWith(
	catalogue: Catalogue,
	key: string,
	values: Record<string, unknown> = {},
): string {
	let text = catalogue[key] ?? key;
	for (const [name, value] of Object.entries(values)) {
		text = text.replaceAll(`{${name}}`, String(value));
	}
	return text;
}

/** The language to start in, from a previous visit or the browser's own. */
export function preferredLanguage(stored: string | null): Language {
	if (stored !== null && (LANGUAGES as readonly string[]).includes(stored)) {
		return stored as Language;
	}
	const tags = navigator.languages ?? [navigator.language];
	for (const tag of tags) {
		const lower = tag.toLowerCase();
		if (lower.startsWith("zh")) return "zh_cn";
		if (lower.startsWith("ja")) return "ja_jp";
		if (lower.startsWith("ko")) return "ko_kr";
		if (lower.startsWith("en")) return "en_us";
	}
	return DEFAULT_LANGUAGE;
}
