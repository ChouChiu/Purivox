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
	track: {
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
	trackTitle: { marginTop: tokens.spacingVerticalS },
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

/** One rendered stem: the bytes, the name it downloads as, and its statistics. */
export interface ResultTrack {
	blob: Blob;
	filename: string;
	/** Translation key naming the stem; omitted when there is only one. */
	titleKey?: string;
	stats?: AudioStats;
}

interface Props {
	tracks: readonly ResultTrack[];
	/** Shown before the first render, when there is nothing to preview yet. */
	placeholderName: string;
	/** Hand the caller a play/pause toggle, for the Ctrl+P shortcut. */
	registerToggle?(toggle: () => void): void;
}

/** Preview and download the rendered stems; nothing leaves the tab until asked. */
export function ResultPanel({
	tracks,
	placeholderName,
	registerToggle,
}: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const [urls, setUrls] = useState<readonly string[]>([]);

	useEffect(() => {
		const created = tracks.map((track) => URL.createObjectURL(track.blob));
		setUrls(created);
		// Each blob holds a whole rendered file; release them as soon as the page
		// shows a different result, or a long session accumulates every render.
		return () => {
			for (const url of created) URL.revokeObjectURL(url);
		};
	}, [tracks]);

	// An empty panel still shows the player and the download button, disabled,
	// so the card does not change shape the moment a render lands.
	const shown = tracks.length === 0 ? [null] : tracks;

	return (
		<Card className={styles.card}>
			<CardHeader header={<Title3>{t("preview_title")}</Title3>} />
			{tracks.length === 0 ? (
				<Text className={styles.empty}>{t("preview_empty")}</Text>
			) : null}
			{shown.map((track, index) => (
				<Stem
					key={track?.filename ?? "empty"}
					track={track}
					url={urls[index] ?? null}
					filename={track?.filename ?? placeholderName}
					// Ctrl+P has always driven one player; keep it on the first stem.
					registerToggle={index === 0 ? registerToggle : undefined}
					showTitle={tracks.length > 1}
				/>
			))}
		</Card>
	);
}

function Stem({
	track,
	url,
	filename,
	registerToggle,
	showTitle,
}: {
	track: ResultTrack | null;
	url: string | null;
	filename: string;
	registerToggle?(toggle: () => void): void;
	showTitle: boolean;
}) {
	const styles = useStyles();
	const { t } = useLanguage();
	const stats = track?.stats;

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
			[
				t("audio_file_size"),
				formatBytes(stats.file_size || (track?.blob.size ?? 0)),
			],
		];
	}, [stats, t, track?.blob.size]);

	return (
		<div className={styles.track}>
			{showTitle && track?.titleKey !== undefined ? (
				<Title3 className={styles.trackTitle}>{t(track.titleKey)}</Title3>
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
		</div>
	);
}
