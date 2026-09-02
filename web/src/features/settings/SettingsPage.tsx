import {
	Card,
	CardHeader,
	Field,
	MessageBar,
	MessageBarBody,
	makeStyles,
	Select,
	Text,
	Title3,
	tokens,
} from "@fluentui/react-components";

import {
	LANGUAGE_NAMES,
	LANGUAGES,
	type Language,
} from "../../shared/i18n/catalogue";
import { useLanguage } from "../../shared/i18n/context";
import type { ThemeChoice } from "../../shared/theme";

const useStyles = makeStyles({
	page: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalL,
	},
	card: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
	},
	hint: { color: tokens.colorNeutralForeground3 },
});

interface Props {
	theme: ThemeChoice;
	onTheme(theme: ThemeChoice): void;
}

export function SettingsPage({ theme, onTheme }: Props) {
	const styles = useStyles();
	const { language, setLanguage, t } = useLanguage();

	return (
		<div className={styles.page}>
			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("nav_settings")}</Title3>} />
				<Field label={t("lang_label")}>
					<Select
						value={language}
						onChange={(_event, data) => setLanguage(data.value as Language)}
					>
						{LANGUAGES.map((code) => (
							<option key={code} value={code}>
								{LANGUAGE_NAMES[code]}
							</option>
						))}
					</Select>
				</Field>
				<Field label={t("theme_label")}>
					<Select
						value={theme}
						onChange={(_event, data) => onTheme(data.value as ThemeChoice)}
					>
						<option value="auto">auto</option>
						<option value="light">light</option>
						<option value="dark">dark</option>
					</Select>
				</Field>
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("nav_ai")}</Title3>} />
				<MessageBar intent="info">
					<MessageBarBody>{t("web_no_ai")}</MessageBarBody>
				</MessageBar>
				<Text className={styles.hint}>{t("web_boot_hint")}</Text>
			</Card>
		</div>
	);
}
