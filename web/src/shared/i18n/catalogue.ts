import enUs from "../../../generated/i18n/en_us.json";
import jaJp from "../../../generated/i18n/ja_jp.json";
import koKr from "../../../generated/i18n/ko_kr.json";
import zhCn from "../../../generated/i18n/zh_cn.json";
import zhTw from "../../../generated/i18n/zh_tw.json";

export const LANGUAGES = ["zh_cn", "zh_tw", "en_us", "ja_jp", "ko_kr"] as const;
export type Language = (typeof LANGUAGES)[number];
export const DEFAULT_LANGUAGE: Language = "zh_cn";

export const LANGUAGE_NAMES: Record<Language, string> = {
	zh_cn: "简体中文",
	zh_tw: "正體中文",
	en_us: "English",
	ja_jp: "日本語",
	ko_kr: "한국어",
};

export type Catalogue = Record<string, string>;
export type Translate = (
	key: string,
	values?: Record<string, unknown>,
) => string;

/**
 * Every catalogue, built from the same `.ts` sources the desktop compiles.
 *
 * They arrive as imports rather than as a fetch: `scripts/build-i18n.mjs` writes
 * them before Vite runs, so the bundle carries the exact strings it was built
 * with, under a content hash.  Fetching them from a fixed path under `public/`
 * meant a page could load the previous deploy's catalogue, and a key the page
 * had gained since then resolved to itself - the raw key, on screen.
 */
const CATALOGUES: Record<Language, Catalogue> = {
	zh_cn: zhCn,
	zh_tw: zhTw,
	en_us: enUs,
	ja_jp: jaJp,
	ko_kr: koKr,
};

export function catalogueFor(language: Language): Catalogue {
	return CATALOGUES[language];
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
		// Traditional Chinese reaches us either as a script subtag or as a
		// region: zh-Hant carries no region, zh-TW carries no script.
		if (lower.startsWith("zh")) {
			return /(?:^|-)(?:hant|tw|hk|mo)(?:-|$)/.test(lower) ? "zh_tw" : "zh_cn";
		}
		if (lower.startsWith("ja")) return "ja_jp";
		if (lower.startsWith("ko")) return "ko_kr";
		if (lower.startsWith("en")) return "en_us";
	}
	return DEFAULT_LANGUAGE;
}
