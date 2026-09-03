import {
	Body1,
	Button,
	Caption1,
	Card,
	CardHeader,
	makeStyles,
	mergeClasses,
	Subtitle1,
	Text,
	Title2,
	Title3,
	tokens,
} from "@fluentui/react-components";

import { useLanguage } from "../../shared/i18n/context";
import { BrandMark } from "../../shared/ui/BrandMark";

const useStyles = makeStyles({
	page: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalL,
	},
	greeting: {
		display: "flex",
		alignItems: "center",
		gap: tokens.spacingHorizontalL,
	},
	words: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalXS,
		minWidth: 0,
	},
	muted: { color: tokens.colorNeutralForeground3 },
	choices: {
		display: "grid",
		gap: tokens.spacingHorizontalL,
		gridTemplateColumns: "1fr",
		"@media (min-width: 760px)": { gridTemplateColumns: "1fr 1fr" },
	},
	choice: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
		height: "100%",
	},
	// The description grows so both cards' buttons line up at the bottom.
	body: { flexGrow: 1 },
	unavailable: { opacity: 0.6 },
});

interface Props {
	onOpenMr(): void;
}

export function HomePage({ onOpenMr }: Props) {
	const styles = useStyles();
	const { t } = useLanguage();

	return (
		<div className={styles.page}>
			<Card>
				<div className={styles.greeting}>
					<BrandMark size={56} />
					<div className={styles.words}>
						<Title2>{t("home_greeting")}</Title2>
						<Body1 className={styles.muted}>{t("home_intro")}</Body1>
					</div>
				</div>
			</Card>

			<div className={styles.words}>
				<Title3>{t("home_choose_title")}</Title3>
				<Caption1 className={styles.muted}>{t("home_choose_hint")}</Caption1>
			</div>

			<div className={styles.choices}>
				<Card className={styles.choice}>
					<CardHeader
						header={<Subtitle1>{t("nav_mr")}</Subtitle1>}
						description={
							<Caption1 className={styles.muted}>{t("home_mr_meta")}</Caption1>
						}
					/>
					<Body1 className={styles.body}>{t("home_mr_description")}</Body1>
					<div>
						<Button appearance="primary" onClick={onOpenMr}>
							{t("home_open_mr")}
						</Button>
					</div>
				</Card>

				{/* The AI workflow is listed so its absence is explained rather than
				    silently missing; onnxruntime has no WebAssembly build. */}
				<Card className={mergeClasses(styles.choice, styles.unavailable)}>
					<CardHeader
						header={<Subtitle1>{t("nav_ai")}</Subtitle1>}
						description={
							<Caption1 className={styles.muted}>{t("home_ai_meta")}</Caption1>
						}
					/>
					<Body1 className={styles.body}>{t("home_ai_description")}</Body1>
					<Text size={200} className={styles.muted}>
						{t("web_no_ai")}
					</Text>
				</Card>
			</div>
		</div>
	);
}
