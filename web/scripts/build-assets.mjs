// Copy the brand mark the desktop already ships into the site's public files.
//
// `src/resources/purivox.svg` is the one source: the desktop renders it into a
// window icon through `shared/branding.py`, and the page uses the same file for
// its favicon and header mark. Copying beats a second drawing that drifts.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "..", "..", "src", "resources", "purivox.svg");
const target = resolve(here, "..", "public");

mkdirSync(target, { recursive: true });
copyFileSync(source, join(target, "purivox.svg"));
console.log("copied the brand mark to public/purivox.svg");
