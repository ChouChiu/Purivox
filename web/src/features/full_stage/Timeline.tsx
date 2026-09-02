import {
	Button,
	Checkbox,
	Input,
	makeStyles,
	Table,
	TableBody,
	TableCell,
	TableHeader,
	TableHeaderCell,
	TableRow,
	Text,
	tokens,
} from "@fluentui/react-components";
import { useState } from "react";

import { useLanguage } from "../../shared/i18n/context";
import type {
	Analysis,
	ClipKind,
	TimelineClip,
} from "../../shared/runtime/types";
import { formatRange, parseRange } from "./clock";

/** The same six columns the desktop table model exposes, in the same order. */
const KIND_KEYS: Record<ClipKind, string> = {
	song: "stage_type_song",
	fragment: "stage_type_fragment",
	unmatched: "stage_type_unmatched",
};

const useStyles = makeStyles({
	wrapper: { overflowX: "auto" },
	table: { minWidth: "760px" },
	range: { minWidth: "180px" },
	actions: {
		display: "flex",
		gap: tokens.spacingHorizontalS,
		marginTop: tokens.spacingVerticalM,
	},
	invalid: { color: tokens.colorPaletteRedForeground1 },
});

/** One editable time range that only commits a value the parser accepts. */
function RangeCell({
	start,
	end,
	disabled,
	onCommit,
}: {
	start: number;
	end: number;
	disabled: boolean;
	onCommit(start: number, end: number): void;
}) {
	const styles = useStyles();
	const [draft, setDraft] = useState<string | null>(null);
	const [invalid, setInvalid] = useState(false);

	if (disabled) return <Text>—</Text>;

	const commit = () => {
		if (draft === null) return;
		try {
			const [first, second] = parseRange(draft);
			setInvalid(false);
			setDraft(null);
			onCommit(first, second);
		} catch {
			setInvalid(true);
		}
	};

	return (
		<Input
			className={`${styles.range} ${invalid ? styles.invalid : ""}`}
			value={draft ?? formatRange(start, end)}
			onChange={(_event, data) => setDraft(data.value)}
			onBlur={commit}
			onKeyDown={(event) => {
				if (event.key === "Enter") commit();
				if (event.key === "Escape") {
					setDraft(null);
					setInvalid(false);
				}
			}}
		/>
	);
}

interface Props {
	analysis: Analysis;
	disabled: boolean;
	onEdit(index: number, changes: Partial<TimelineClip>): void;
	onAdd(): void;
	onRemove(index: number): void;
}

export function Timeline({
	analysis,
	disabled,
	onEdit,
	onAdd,
	onRemove,
}: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const [selected, setSelected] = useState<number | null>(null);

	return (
		<div>
			<div className={styles.wrapper}>
				<Table className={styles.table} size="small">
					<TableHeader>
						<TableRow>
							<TableHeaderCell>{t("stage_clip_enabled")}</TableHeaderCell>
							<TableHeaderCell>{t("stage_clip_type")}</TableHeaderCell>
							<TableHeaderCell>{t("stage_clip_time")}</TableHeaderCell>
							<TableHeaderCell>{t("stage_source_time")}</TableHeaderCell>
							<TableHeaderCell>{t("stage_confidence")}</TableHeaderCell>
							<TableHeaderCell>{t("stage_clip_source")}</TableHeaderCell>
						</TableRow>
					</TableHeader>
					<TableBody>
						{analysis.clips.map((clip, index) => {
							const unmatched = clip.kind === "unmatched";
							return (
								<TableRow
									key={`${clip.kind}-${clip.stage_start}-${clip.stage_end}`}
									appearance={selected === index ? "brand" : "none"}
									onClick={() => setSelected(index)}
								>
									<TableCell>
										<Checkbox
											checked={clip.enabled}
											disabled={disabled || unmatched}
											onChange={(_event, data) =>
												onEdit(index, { enabled: Boolean(data.checked) })
											}
										/>
									</TableCell>
									<TableCell>{t(KIND_KEYS[clip.kind])}</TableCell>
									<TableCell>
										<RangeCell
											start={clip.stage_start}
											end={clip.stage_end}
											disabled={disabled}
											onCommit={(start, end) =>
												onEdit(index, { stage_start: start, stage_end: end })
											}
										/>
									</TableCell>
									<TableCell>
										<RangeCell
											start={clip.source_start}
											end={clip.source_end}
											disabled={disabled || unmatched}
											onCommit={(start, end) =>
												onEdit(index, { source_start: start, source_end: end })
											}
										/>
									</TableCell>
									<TableCell>
										{clip.manual
											? t("stage_manual_label")
											: unmatched
												? "—"
												: `${Math.round(clip.confidence * 100)}%`}
									</TableCell>
									<TableCell>
										{clip.source === null
											? t("stage_unmatched_label")
											: clip.source.split("/").pop()}
									</TableCell>
								</TableRow>
							);
						})}
					</TableBody>
				</Table>
			</div>
			<div className={styles.actions}>
				<Button disabled={disabled} onClick={onAdd}>
					{t("stage_add_clip")}
				</Button>
				<Button
					disabled={
						disabled || selected === null || !analysis.clips[selected]?.manual
					}
					onClick={() => {
						if (selected !== null) {
							onRemove(selected);
							setSelected(null);
						}
					}}
				>
					{t("stage_remove_clip")}
				</Button>
			</div>
		</div>
	);
}
