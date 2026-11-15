// Turn the Qt Linguist sources into JSON the page can read.  The `.ts` files
// stay the single authority for every string: the desktop compiles them to
// `.qm` with pyside6-lrelease, and the browser reads the same keys from here.
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const catalogues = resolve(here, "..", "..", "src", "resources", "i18n");
// Outside public/ on purpose: Vite only fingerprints assets the bundle imports,
// and the bundle is what decides which catalogue is read. A fixed file name in
// public/ outlives the bundle that asked for it, so a deploy carrying new strings
// left a returning visitor on the previous catalogue - and a key the page gained
// in between resolved to itself, on screen.
const output = resolve(here, "..", "generated", "i18n");

const MESSAGE = /<message>([\s\S]*?)<\/message>/g;
const SOURCE = /<source>([\s\S]*?)<\/source>/;
const TRANSLATION = /<translation[^>]*>([\s\S]*?)<\/translation>/;

function unescapeXml(text) {
	return text
		.replace(/&lt;/g, "<")
		.replace(/&gt;/g, ">")
		.replace(/&quot;/g, '"')
		.replace(/&apos;/g, "'")
		.replace(/&#(\d+);/g, (_match, code) => String.fromCodePoint(Number(code)))
		.replace(/&amp;/g, "&");
}

function parse(xml) {
	const entries = {};
	for (const [, block] of xml.matchAll(MESSAGE)) {
		const key = SOURCE.exec(block);
		const value = TRANSLATION.exec(block);
		if (key && value) {
			entries[unescapeXml(key[1]).trim()] = unescapeXml(value[1]);
		}
	}
	return entries;
}

mkdirSync(output, { recursive: true });
const sources = readdirSync(catalogues).filter((name) => name.endsWith(".ts"));
if (sources.length === 0) {
	throw new Error(`no translation sources in ${catalogues}`);
}

let reference = null;
for (const name of sources.sort()) {
	const locale = name.replace(/\.ts$/, "");
	const entries = parse(readFileSync(join(catalogues, name), "utf8"));
	const keys = Object.keys(entries).sort();
	if (reference === null) {
		reference = { locale, keys };
	} else {
		// The desktop test suite enforces the same parity; catching it here keeps a
		// half-translated build from reaching Pages with blank strings.
		const missing = reference.keys.filter((key) => !(key in entries));
		if (missing.length > 0) {
			throw new Error(
				`${name} is missing keys present in ${reference.locale}: ${missing.join(", ")}`,
			);
		}
	}
	writeFileSync(
		join(output, `${locale}.json`),
		`${JSON.stringify(entries, null, 2)}\n`,
	);
	console.log(`wrote ${locale}.json (${keys.length} keys)`);
}
