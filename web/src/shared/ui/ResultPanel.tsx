import {
	Button,
	Card,
	CardHeader,
	makeStyles,
	Text,
	Title3,
	tokens,
} from "@fluentui/react-components";
import { useEffect, useMemo, useState } from "react";
import { formatBytes } from "../audio/prepare";
import { useLanguage } from "../i18n/context";
import type { AudioStats } from "../runtime/types";
import { AudioPlayer } from "./AudioPlayer";
import { duration as formatDuration } from "./duration";

const useStyles = makeStyles({
	card: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
	},
	stats: {
		display: "grid",
		// Two columns on a phone, as many as fit on a desktop.
		gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
		gap: tokens.spacingVerticalS,
	},
	empty: { color: tokens.colorNeutralForeground3 },
	statsTitle: { marginTop: tokens.spacingVerticalS },
	stat: { display: "flex", flexDirection: "column" },
	label: {
		color: tokens.colorNeutralForeground3,
		fontSize: tokens.fontSizeBase200,
	},
});

function channelLabel(
	channels: number,
	t: (key: string, values?: Record<string, unknown>) => string,
) {
	if (channels === 1) return t("audio_mono");
	if (channels === 2) return t("audio_stereo");
	return t("audio_channel_count", { count: channels });
}

interface Props {
	blob: Blob | null;
	filename: string;
	stats?: AudioStats;
	/** Hand the caller a play/pause toggle, for the Ctrl+P shortcut. */
	registerToggle?(toggle: () => void): void;
}

/** Preview and download one rendered file; nothing leaves the tab until asked. */
export function ResultPanel({ blob, filename, stats, registerToggle }: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const [url, setUrl] = useState<string | null>(null);

	useEffect(() => {
		if (blob === null) {
			setUrl(null);
			return;
		}
		const created = URL.createObjectURL(blob);
		setUrl(created);
		// The blob holds the whole rendered file; release it as soon as the page
		// shows a different result, or a long session accumulates every render.
		return () => URL.revokeObjectURL(created);
	}, [blob]);

	const rows = useMemo(() => {
		if (stats === undefined) return [];
		const decibels = (value: number | null) =>
			value === null ? "-∞ dBFS" : `${value.toFixed(1)} dBFS`;
		return [
			[t("audio_duration"), formatDuration(stats.duration_seconds)],
			[t("audio_sample_rate"), `${stats.sample_rate} Hz`],
			[t("audio_channels"), channelLabel(stats.channels, t)],
			[t("audio_bit_depth"), `${stats.bit_depth} bit`],
			[t("audio_peak"), decibels(stats.peak_dbfs)],
			[t("audio_rms"), decibels(stats.rms_dbfs)],
			[t("audio_file_size"), formatBytes(stats.file_size || (blob?.size ?? 0))],
		];
	}, [blob?.size, stats, t]);

	return (
		<Card className={styles.card}>
			<CardHeader header={<Title3>{t("preview_title")}</Title3>} />
			{url === null ? (
				<Text className={styles.empty}>{t("preview_empty")}</Text>
			) : null}
			<AudioPlayer
				url={url}
				seconds={stats?.duration_seconds ?? 0}
				registerToggle={registerToggle}
			/>
			<div>
				<Button
					appearance="primary"
					as="a"
					href={url ?? undefined}
					download={filename}
					disabled={url === null}
				>
					{t("web_download")}
				</Button>
			</div>
			{rows.length > 0 ? (
				<Title3 className={styles.statsTitle}>{t("audio_data_title")}</Title3>
			) : null}
			{rows.length > 0 ? (
				<div className={styles.stats}>
					{rows.map(([label, value]) => (
						<div className={styles.stat} key={label}>
							<Text className={styles.label}>{label}</Text>
							<Text>{value}</Text>
						</div>
					))}
				</div>
			) : null}
		</Card>
	);
}
