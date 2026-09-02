// Pack the Python tree the browser runs into one archive Pyodide unpacks at
// startup.  The browser executes the very same `src/` the desktop ships - there
// is no second implementation of the DSP to keep in step.
import {
	mkdirSync,
	readdirSync,
	readFileSync,
	statSync,
	writeFileSync,
} from "node:fs";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import JSZip from "jszip";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "..", "..", "src");
const target = resolve(here, "..", "public", "purivox-src.zip");

// `app` carries `full_stage_processing`, which orchestrates the render.  Its GUI
// modules travel along but are never imported: nothing in the browser reaches
// `app.main_window`.  `entrypoints` is left out entirely - it is Qt startup.
const PACKAGES = ["app", "features", "resources", "shared", "web"];
// Compiled catalogues and Linguist sources are dead weight here; the page
// translates from the JSON that build-i18n.mjs writes.
const SKIPPED_SUFFIXES = [".pyc", ".qm", ".ts"];

function* walk(directory) {
	for (const entry of readdirSync(directory, { withFileTypes: true }).sort(
		(a, b) => a.name.localeCompare(b.name),
	)) {
		const path = join(directory, entry.name);
		if (entry.isDirectory()) {
			if (entry.name === "__pycache__") continue;
			yield* walk(path);
		} else if (
			entry.isFile() &&
			!SKIPPED_SUFFIXES.some((suffix) => entry.name.endsWith(suffix))
		) {
			yield path;
		}
	}
}

const archive = new JSZip();
let count = 0;
for (const name of PACKAGES) {
	const root = join(source, name);
	if (!statSync(root).isDirectory()) {
		throw new Error(`expected a Python package at ${root}`);
	}
	for (const path of walk(root)) {
		// Zip entries always use forward slashes, whatever the host separator is.
		archive.file(
			relative(source, path).split(sep).join("/"),
			readFileSync(path),
		);
		count += 1;
	}
}

const bytes = await archive.generateAsync({
	type: "nodebuffer",
	compression: "DEFLATE",
	compressionOptions: { level: 9 },
	// A stable timestamp keeps the artefact byte-identical between builds of the
	// same sources, so a redeploy does not bust every visitor's cache for nothing.
	date: new Date("2000-01-01T00:00:00Z"),
});

mkdirSync(dirname(target), { recursive: true });
writeFileSync(target, bytes);
console.log(
	`packed ${count} files into ${target} (${(bytes.length / 1024).toFixed(0)} KiB)`,
);
