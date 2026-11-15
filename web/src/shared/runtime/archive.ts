/**
 * The Python tree the browser runs, as one archive.
 *
 * `scripts/build-python-archive.mjs` writes it before Vite starts, and importing
 * it is what makes Vite emit it under a content hash. Copying it into `public/`
 * instead gave it a fixed name, so a deploy could hand a returning visitor the
 * new page and the previous archive - a job field the Python side never learned
 * to read, and a pipeline that silently ran on stale code.
 */
import archiveUrl from "../../../generated/purivox-src.zip?url";

export const SOURCE_ARCHIVE_URL: string = archiveUrl;
