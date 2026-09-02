// Enforce the same layering the Python tree has.
//
// `tests/test_architecture.py` parses imports to keep `shared` from reaching up
// and features from reaching sideways. The front end is organised by feature for
// the same reason, so it gets the same check rather than a convention nobody can
// see breaking.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..", "src");

const FROM_IMPORT =
	/(?:^|\n)\s*(?:import|export)[\s\S]*?from\s*["']([^"']+)["']/g;
const BARE_IMPORT = /(?:^|\n)\s*import\s*["']([^"']+)["']/g;

function* walk(directory) {
	for (const entry of readdirSync(directory, { withFileTypes: true })) {
		const path = join(directory, entry.name);
		if (entry.isDirectory()) yield* walk(path);
		else if (/\.tsx?$/.test(entry.name)) yield path;
	}
}

/** Which layer a path belongs to: "shared", "app", "features/<name>" or "entry". */
function layerOf(parts) {
	if (parts[0] === "shared") return "shared";
	if (parts[0] === "app") return "app";
	if (parts[0] === "features") return `features/${parts[1]}`;
	return "entry";
}

/** Resolve a relative specifier back to a layer, ignoring package imports. */
function targetLayer(file, specifier) {
	if (!specifier.startsWith(".")) return null;
	const resolved = resolve(dirname(file), specifier);
	const parts = relative(root, resolved).split(sep);
	if (parts[0] === "..") return null;
	return layerOf(parts);
}

const violations = [];
for (const file of walk(root)) {
	const from = layerOf(relative(root, file).split(sep));
	const source = readFileSync(file, "utf8");
	const specifiers = [
		...[...source.matchAll(FROM_IMPORT)].map((match) => match[1]),
		...[...source.matchAll(BARE_IMPORT)].map((match) => match[1]),
	];
	for (const specifier of specifiers) {
		const to = targetLayer(file, specifier);
		if (to === null || to === from) continue;
		const where = `${relative(root, file)} -> ${specifier}`;
		if (from === "shared") {
			// shared underpins everything and may depend on nothing above it.
			violations.push(`${where} (shared must not import ${to})`);
		} else if (from.startsWith("features/")) {
			if (to === "app" || to.startsWith("features/")) {
				violations.push(`${where} (a feature must not import ${to})`);
			}
		} else if (from === "app" && to === "entry") {
			violations.push(`${where} (app must not import the entry point)`);
		}
	}
}

if (violations.length > 0) {
	console.error("invalid front-end dependencies:");
	for (const violation of violations) console.error(`  ${violation}`);
	process.exit(1);
}
console.log(`front-end layering is intact`);
