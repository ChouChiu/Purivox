import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { LanguageProvider } from "./shared/i18n/context";
import "./index.css";

const container = document.getElementById("root");
if (container === null) {
	throw new Error("the page is missing its root element");
}

createRoot(container).render(
	<StrictMode>
		<LanguageProvider>
			<App />
		</LanguageProvider>
	</StrictMode>,
);
