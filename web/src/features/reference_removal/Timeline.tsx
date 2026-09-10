import {
	Button,
	Checkbox,
	Input,
	makeStyles,
	mergeClasses,
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

/** The same seven columns the desktop table model exposes, in the same order. */
const KIND_KEYS: Record<ClipKind, string> = {
	song: "stage_type_song",
	fragment: "stage_type_fragment",
	unmatched: "stage_type_unmatched",
};

// The table lays out fixed, so every column is exactly as wide as its header
// cell claims and nothing negotiates on the content's behalf: seven columns
// otherwise just split the width evenly, and a `td` does not clip what
// overflows it - which is how the time fields, each carrying two clocks and a
// dash, came to sit on top of the column beside them.  Each width below is what
// that column's widest header and content measure across the five languages,
// with room to spare; every column is claimed, because one left to `auto` keeps
// only what the others did not want.  They add up, with the cells' own padding,
// to 968px, which is what the page has to give at its 1100px content width.
const useStyles = makeStyles({
	wrapper: { overflowX: "auto" },
	enabled: { width: "56px" },
	kind: { width: "104px" },
	range: { width: "188px" },
	speed: { width: "56px" },
	confidence: { width: "96px" },
	source: { width: "168px" },
	sourceName: {
		display: "block",
		overflow: "hidden",
		textOverflow: "ellipsis",
		whiteSpace: "nowrap",
	},
	rangeInput: { width: "100%" },
	// Without this the field keeps the browser's default twenty-character
	// intrinsic width, which no column width can talk it out of.
	rangeField: { minWidth: 0 },
	// The field paints its own text colour, so a colour on the wrapper never
	// reaches it; the border is the wrapper's own, and says the same thing to a
	// reader who cannot separate the two colours.
	invalidText: { color: tokens.colorPaletteRedForeground1 },
	// Fluent repaints the underline on hover and on focus, so the invalid colour
	// has to be stated for those states too or it vanishes under the pointer.
	invalidBorder: {
		borderBottomColor: tokens.colorPaletteRedBorder2,
		":hover": { borderBottomColor: tokens.colorPaletteRedBorder2 },
		":focus-within": { borderBottomColor: tokens.colorPaletteRedBorder2 },
	},
	actions: {
		display: "flex",
		gap: tokens.spacingHorizontalS,
		marginTop: tokens.spacingVerticalM,
	},
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
			className={mergeClasses(
				styles.rangeInput,
				invalid && styles.invalidBorder,
			)}
			input={{
				className: mergeClasses(
					styles.rangeField,
					invalid && styles.invalidText,
				),
			}}
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
				<Table size="small">
					<TableHeader>
						<TableRow>
							<TableHeaderCell className={styles.enabled}>
								{t("stage_clip_enabled")}
							</TableHeaderCell>
							<TableHeaderCell className={styles.kind}>
								{t("stage_clip_type")}
							</TableHeaderCell>
							<TableHeaderCell className={styles.range}>
								{t("stage_clip_time")}
							</TableHeaderCell>
							<TableHeaderCell className={styles.range}>
								{t("stage_source_time")}
							</TableHeaderCell>
							<TableHeaderCell className={styles.speed}>
								{t("stage_clip_speed")}
							</TableHeaderCell>
							<TableHeaderCell className={styles.confidence}>
								{t("stage_confidence")}
							</TableHeaderCell>
							<TableHeaderCell className={styles.source}>
								{t("stage_clip_source")}
							</TableHeaderCell>
						</TableRow>
					</TableHeader>
					<TableBody>
						{analysis.clips.map((clip, index) => {
							const unmatched = clip.kind === "unmatched";
							const sourceName =
								clip.source === null
									? t("stage_unmatched_label")
									: (clip.source.split("/").pop() ?? clip.source);
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
										{unmatched || Math.abs(clip.speed - 1) < 1e-9
											? "—"
											: `${clip.speed.toFixed(3)}×`}
									</TableCell>
									<TableCell>
										{clip.manual
											? t("stage_manual_label")
											: unmatched
												? "—"
												: `${Math.round(clip.confidence * 100)}%`}
									</TableCell>
									<TableCell className={styles.source}>
										<span className={styles.sourceName} title={sourceName}>
											{sourceName}
										</span>
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
