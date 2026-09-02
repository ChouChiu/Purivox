import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The site is served from the root of its own domain, so asset URLs need no
// prefix.  `PURIVOX_BASE` covers the other case: a GitHub Pages project site
// lives under /<repository>/ and every URL has to carry that.
const base = process.env.PURIVOX_BASE ?? "/";

export default defineConfig({
	base,
	plugins: [react()],
	worker: { format: "es" },
	build: { target: "es2022", chunkSizeWarningLimit: 1500 },
});
