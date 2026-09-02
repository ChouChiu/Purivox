import {
	createContext,
	type ReactNode,
	useContext,
	useEffect,
	useMemo,
	useState,
} from "react";

import {
	type Catalogue,
	DEFAULT_LANGUAGE,
	type Language,
	loadCatalogue,
	preferredLanguage,
	type Translate,
	translateWith,
} from "./catalogue";

const STORAGE_KEY = "purivox.language";

interface LanguageContextValue {
	language: Language;
	setLanguage(language: Language): void;
	t: Translate;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

function readStored(): string | null {
	try {
		return localStorage.getItem(STORAGE_KEY);
	} catch {
		// A private window can refuse storage entirely; the browser's own
		// preference is a good enough answer when it does.
		return null;
	}
}

export function LanguageProvider({ children }: { children: ReactNode }) {
	const [language, setLanguageState] = useState<Language>(() =>
		preferredLanguage(readStored()),
	);
	const [catalogue, setCatalogue] = useState<Catalogue>({});

	useEffect(() => {
		let current = true;
		loadCatalogue(language)
			.then((entries) => {
				if (current) setCatalogue(entries);
			})
			.catch(() => {
				// Every key then resolves to itself, which is visible but not blank.
				if (current) setCatalogue({});
			});
		document.documentElement.lang = language.replace("_", "-");
		return () => {
			current = false;
		};
	}, [language]);

	const value = useMemo<LanguageContextValue>(
		() => ({
			language,
			setLanguage(next: Language) {
				setLanguageState(next);
				try {
					localStorage.setItem(STORAGE_KEY, next);
				} catch {
					// Remembering the choice is a convenience, not a requirement.
				}
			},
			t: (key, values) => translateWith(catalogue, key, values),
		}),
		[catalogue, language],
	);

	return (
		<LanguageContext.Provider value={value}>
			{children}
		</LanguageContext.Provider>
	);
}

export function useLanguage(): LanguageContextValue {
	const value = useContext(LanguageContext);
	if (value === null) {
		throw new Error("useLanguage must be used inside a LanguageProvider");
	}
	return value;
}

export { DEFAULT_LANGUAGE };
