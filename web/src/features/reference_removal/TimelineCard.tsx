import {
	Card,
	CardHeader,
	makeStyles,
	Text,
	Title3,
	tokens,
} from "@fluentui/react-components";

import { useLanguage } from "../../shared/i18n/context";
import type { Analysis, TimelineClip } from "../../shared/runtime/types";
import { Timeline } from "./Timeline";

const useStyles = makeStyles({
	card: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
	},
	hint: { color: tokens.colorNeutralForeground3 },
});

interface Props {
	analysis: Analysis | null;
	/** Whether there is a recording and a source to find songs in yet. */
	hasInputs: boolean;
	disabled: boolean;
	onEdit(index: number, changes: Partial<TimelineClip>): void;
	onAdd(): void;
	onRemove(index: number): void;
}

/** What the matcher found, and the table the user corrects it in. */
export function TimelineCard({
	analysis,
	hasInputs,
	disabled,
	onEdit,
	onAdd,
	onRemove,
}: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const count = (kind: TimelineClip["kind"]) =>
		analysis?.clips.filter((clip) => clip.kind === kind).length ?? 0;

	return (
		<Card className={styles.card}>
			<CardHeader header={<Title3>{t("stage_timeline")}</Title3>} />
			<Text className={styles.hint}>{t("stage_timeline_hint")}</Text>
			{analysis === null ? (
				hasInputs ? (
					<Text className={styles.hint}>{t("stage_need_analysis")}</Text>
				) : null
			) : (
				<>
					<Text className={styles.hint}>
						{t("stage_analysis_summary", {
							songs: count("song"),
							fragments: count("fragment"),
							missing: analysis.missing_sources.length,
						})}
					</Text>
					<Timeline
						analysis={analysis}
						disabled={disabled}
						onEdit={onEdit}
						onAdd={onAdd}
						onRemove={onRemove}
					/>
				</>
			)}
		</Card>
	);
}
