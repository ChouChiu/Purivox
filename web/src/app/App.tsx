import {
	Button,
	FluentProvider,
	MessageBar,
	MessageBarActions,
	MessageBarBody,
	makeStyles,
	ProgressBar,
	Tab,
	TabList,
	Text,
	Title2,
	tokens,
} from "@fluentui/react-components";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { FullStagePage } from "../features/full_stage/FullStagePage";
import { HomePage } from "../features/home/HomePage";
import { MrPage } from "../features/reference_removal/MrPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { useLanguage } from "../shared/i18n/context";
import { FIRST_VISIT_MEGABYTES } from "../shared/runtime/packages";
import { type Shortcuts, useShortcuts } from "../shared/runtime/shortcuts";
import { BOOT_KEYS, useRuntime } from "../shared/runtime/useRuntime";
import {
	readTheme,
	resolveTheme,
	storeTheme,
	type ThemeChoice,
} from "../shared/theme";
import { BrandMark } from "../shared/ui/BrandMark";

type Section = "home" | "mr" | "stage" | "settings";

const useStyles = makeStyles({
	shell: {
		minHeight: "100vh",
		backgroundColor: tokens.colorNeutralBackground2,
	},
	page: {
		maxWidth: "1100px",
		margin: "0 auto",
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalL,
		// The gutter shrinks before the content does, so a narrow phone spends
		// its width on the form rather than on margins.
		padding: tokens.spacingVerticalL,
		"@media (min-width: 640px)": { padding: tokens.spacingVerticalXXL },
	},
	header: {
		display: "flex",
		alignItems: "center",
		gap: tokens.spacingHorizontalM,
	},
	headerText: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalXXS,
		minWidth: 0,
	},
	hint: { color: tokens.colorNeutralForeground3 },
	// A keyboard hint is noise on a touch screen, which has no Ctrl to press.
	shortcuts: {
		display: "none",
		color: tokens.colorNeutralForeground3,
		"@media (min-width: 620px) and (pointer: fine)": { display: "block" },
	},
	boot: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalS,
	},
	// A tab strip is the one thing allowed to scroll sideways; the alternative
	// is three labels wrapping onto three lines.
	tabs: { overflowX: "auto", flexShrink: 0 },
});

function usePrefersDark(): boolean {
	const [dark, setDark] = useState(
		() => window.matchMedia("(prefers-color-scheme: dark)").matches,
	);
	useEffect(() => {
		const query = window.matchMedia("(prefers-color-scheme: dark)");
		const update = (event: MediaQueryListEvent) => setDark(event.matches);
		query.addEventListener("change", update);
		return () => query.removeEventListener("change", update);
	}, []);
	return dark;
}

export function App() {
	const styles = useStyles();
	const { t } = useLanguage();
	const [section, setSection] = useState<Section>("home");
	const [themeChoice, setThemeChoice] = useState<ThemeChoice>(readTheme);
	const prefersDark = usePrefersDark();
	const runtime = useRuntime();

	// Each page registers what its shortcuts should do while it is on screen.
	const bindings = useRef<Shortcuts>({});
	const bind = useCallback((shortcuts: Shortcuts) => {
		bindings.current = shortcuts;
	}, []);
	useShortcuts(
		useMemo<Shortcuts>(
			() => ({
				choose: () => bindings.current.choose?.(),
				start: () => bindings.current.start?.(),
				cancel: () => bindings.current.cancel?.(),
				analyze: () => bindings.current.analyze?.(),
				togglePreview: () => bindings.current.togglePreview?.(),
			}),
			[],
		),
	);

	return (
		<FluentProvider
			theme={resolveTheme(themeChoice, prefersDark)}
			className={styles.shell}
		>
			<div className={styles.page}>
				<header className={styles.header}>
					<BrandMark size={40} />
					<div className={styles.headerText}>
						<Title2>{t("window_title")}</Title2>
						<Text className={styles.hint}>{t("web_boot_hint")}</Text>
					</div>
				</header>

				{runtime.failure !== null ? (
					<MessageBar intent="error">
						<MessageBarBody>
							{t("web_boot_failed", { msg: runtime.failure })}
						</MessageBarBody>
						<MessageBarActions>
							<Button size="small" onClick={runtime.retry}>
								{t("web_retry")}
							</Button>
						</MessageBarActions>
					</MessageBar>
				) : !runtime.ready ? (
					<MessageBar intent="info">
						<MessageBarBody>
							<span className={styles.boot}>
								<Text weight="semibold">{t(BOOT_KEYS[runtime.stage])}</Text>
								{/* The bar shows which of the four startup steps is running.  It is
								    deliberately not a download percentage: Pyodide's lock file
								    carries no sizes, so one would be invented. */}
								<ProgressBar
									value={runtime.fraction}
									max={1}
									thickness="large"
								/>
								<Text size={200}>
									{t("web_boot_size", { size: `${FIRST_VISIT_MEGABYTES} MB` })}
								</Text>
							</span>
						</MessageBarBody>
					</MessageBar>
				) : null}

				<div className={styles.tabs}>
					<TabList
						selectedValue={section}
						onTabSelect={(_event, data) => setSection(data.value as Section)}
					>
						<Tab value="home">{t("nav_home")}</Tab>
						<Tab value="mr">{t("mr_tab_single")}</Tab>
						<Tab value="stage">{t("mr_tab_full_stage")}</Tab>
						<Tab value="settings">{t("nav_settings")}</Tab>
					</TabList>
				</div>

				{section === "home" ? (
					<HomePage onOpenMr={() => setSection("mr")} />
				) : null}
				{/* The working pages stay mounted and are only hidden. Unmounting them
				    would stop a preview mid-play and throw away a finished result or a
				    running job, none of which the visitor asked for by changing tab. */}
				<div hidden={section !== "mr"}>
					<MrPage
						client={runtime.client}
						ready={runtime.ready}
						active={section === "mr"}
						onBind={bind}
					/>
				</div>
				<div hidden={section !== "stage"}>
					<FullStagePage
						client={runtime.client}
						ready={runtime.ready}
						active={section === "stage"}
						onBind={bind}
					/>
				</div>
				{section === "settings" ? (
					<SettingsPage
						theme={themeChoice}
						onTheme={(choice) => {
							setThemeChoice(choice);
							storeTheme(choice);
						}}
					/>
				) : null}

				<Text className={styles.shortcuts} size={200}>
					{t("shortcut_hint")}
				</Text>
			</div>
		</FluentProvider>
	);
}
