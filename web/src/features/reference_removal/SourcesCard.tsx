import {
	Button,
	Card,
	CardHeader,
	makeStyles,
	Radio,
	RadioGroup,
	Text,
	Title3,
	tokens,
} from "@fluentui/react-components";

import { useLanguage } from "../../shared/i18n/context";
import type { PreparedFile } from "../../shared/runtime/types";
import { AudioSummary } from "../../shared/ui/AudioSummary";
import { FilePicker } from "../../shared/ui/FilePicker";

const useStyles = makeStyles({
	card: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
	},
	sources: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalXS,
	},
	// The group hugs its widest radio; a row has to claim the card's width
	// itself, or its remove button sits against the file name.
	source: {
		alignSelf: "stretch",
		display: "flex",
		justifyContent: "space-between",
		alignItems: "center",
		gap: tokens.spacingHorizontalS,
		minWidth: 0,
	},
	// The radio's label holds a file name that can be any length; without a
	// floor of zero it would widen the card instead of truncating.
	choice: { minWidth: 0 },
	label: { display: "flex", flexDirection: "column", minWidth: 0 },
	hint: { color: tokens.colorNeutralForeground3 },
});

interface Props {
	sources: readonly PreparedFile[];
	/** The source a manual timeline clip is taken from, as the desktop list's selection. */
	selected: string | null;
	disabled: boolean;
	onAdd(files: File[]): void;
	onSelect(path: string): void;
	onRemove(path: string): void;
}

export function SourcesCard({
	sources,
	selected,
	disabled,
	onAdd,
	onSelect,
	onRemove,
}: Props) {
	const styles = useStyles();
	const { t } = useLanguage();

	return (
		<Card className={styles.card}>
			<CardHeader header={<Title3>{t("sources_title")}</Title3>} />
			<Text className={styles.hint}>{t("stage_sources_hint")}</Text>
			<FilePicker
				label={t("stage_add_sources")}
				value={sources.length > 0 ? `${sources.length}` : null}
				multiple
				disabled={disabled}
				onPick={onAdd}
			/>
			{sources.length === 0 ? (
				<Text className={styles.hint}>{t("warn_no_source")}</Text>
			) : (
				<RadioGroup
					className={styles.sources}
					value={selected ?? sources[0].path}
					disabled={disabled}
					onChange={(_event, data) => onSelect(data.value)}
				>
					{sources.map((source) => (
						<div className={styles.source} key={source.path}>
							<Radio
								className={styles.choice}
								value={source.path}
								label={
									<span className={styles.label}>
										<Text truncate wrap={false} title={source.path}>
											{source.label}
										</Text>
										<AudioSummary file={source} />
									</span>
								}
							/>
							<Button
								size="small"
								appearance="subtle"
								disabled={disabled}
								onClick={() => onRemove(source.path)}
							>
								{t("stage_remove_source")}
							</Button>
						</div>
					))}
				</RadioGroup>
			)}
		</Card>
	);
}
