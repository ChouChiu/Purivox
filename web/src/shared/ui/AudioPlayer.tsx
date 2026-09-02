import {
	Button,
	makeStyles,
	Slider,
	Text,
	tokens,
} from "@fluentui/react-components";
import {
	Pause20Filled,
	Play20Filled,
	Stop20Regular,
} from "@fluentui/react-icons";
import { useCallback, useEffect, useRef, useState } from "react";

import { useLanguage } from "../i18n/context";
import { duration as clock } from "./duration";

/**
 * Only one preview plays at a time.
 *
 * Both working pages stay mounted so a preview survives a tab change, which
 * means two players can exist at once. Starting one stops the other rather than
 * letting them overlap.
 */
let playing: HTMLAudioElement | null = null;

const useStyles = makeStyles({
	player: {
		display: "flex",
		alignItems: "center",
		gap: tokens.spacingHorizontalS,
		flexWrap: "wrap",
	},
	seek: { flex: "1 1 200px", minWidth: "140px" },
	time: {
		color: tokens.colorNeutralForeground2,
		fontVariantNumeric: "tabular-nums",
		whiteSpace: "nowrap",
	},
	volume: {
		// A phone has hardware volume keys; the slider is desktop furniture.
		display: "none",
		alignItems: "center",
		gap: tokens.spacingHorizontalXS,
		"@media (min-width: 620px)": { display: "flex" },
	},
	volumeSlider: { width: "88px" },
});

interface Props {
	url: string | null;
	/** Total seconds, known from the job's statistics before metadata loads. */
	seconds: number;
	/** Hand the caller a play/pause toggle, for the Ctrl+P shortcut. */
	registerToggle?(toggle: () => void): void;
}

export function AudioPlayer({ url, seconds, registerToggle }: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const audio = useRef<HTMLAudioElement>(null);
	const [isPlaying, setPlaying] = useState(false);
	const [position, setPosition] = useState(0);
	const [total, setTotal] = useState(seconds);
	const [volume, setVolume] = useState(100);
	const [failed, setFailed] = useState(false);
	// While the handle is held, the slider owns the position and the element's
	// own timeupdate must not fight it.
	const seeking = useRef(false);

	useEffect(() => setTotal(seconds), [seconds]);

	useEffect(() => {
		setPlaying(false);
		setPosition(0);
		setFailed(false);
	}, []);

	const toggle = useCallback(() => {
		const element = audio.current;
		if (element === null || url === null) return;
		if (element.paused) {
			if (playing !== null && playing !== element) playing.pause();
			// Pressing play at the end restarts, as the desktop preview does.
			if (element.duration && element.currentTime >= element.duration - 0.05) {
				element.currentTime = 0;
			}
			playing = element;
			void element.play().catch(() => setFailed(true));
		} else {
			element.pause();
		}
	}, [url]);

	useEffect(() => registerToggle?.(toggle), [registerToggle, toggle]);

	const stop = useCallback(() => {
		const element = audio.current;
		if (element === null) return;
		element.pause();
		element.currentTime = 0;
		setPosition(0);
	}, []);

	const ready = url !== null;

	return (
		<div className={styles.player}>
			{/* biome-ignore lint/a11y/useMediaCaption: this is audio the visitor just rendered from their own files, so no caption track exists or could be written */}
			<audio
				ref={audio}
				src={url ?? undefined}
				preload="metadata"
				onPlay={() => setPlaying(true)}
				onPause={() => setPlaying(false)}
				onEnded={() => setPlaying(false)}
				onError={() => setFailed(true)}
				onLoadedMetadata={(event) => {
					const value = event.currentTarget.duration;
					if (Number.isFinite(value) && value > 0) setTotal(value);
				}}
				onTimeUpdate={(event) => {
					if (!seeking.current) setPosition(event.currentTarget.currentTime);
				}}
			/>

			<Button
				appearance="primary"
				icon={isPlaying ? <Pause20Filled /> : <Play20Filled />}
				disabled={!ready}
				onClick={toggle}
			>
				{t(isPlaying ? "preview_pause" : "preview_play")}
			</Button>
			<Button icon={<Stop20Regular />} disabled={!ready} onClick={stop}>
				{t("preview_stop")}
			</Button>

			<Slider
				aria-label={t("preview_title")}
				className={styles.seek}
				min={0}
				max={Math.max(total, 0.1)}
				// No step: Fluent draws a tick per step, and a step fine enough for
				// audio would bury the rail under thousands of them. Seeking is
				// continuous anyway.
				value={Math.min(position, total)}
				disabled={!ready}
				onChange={(_event, data) => {
					seeking.current = true;
					setPosition(data.value);
					if (audio.current !== null) audio.current.currentTime = data.value;
					seeking.current = false;
				}}
			/>
			<Text className={styles.time} size={200}>
				{clock(position)} / {clock(total)}
			</Text>

			<div className={styles.volume}>
				<Text size={200}>{t("preview_volume")}</Text>
				<Slider
					aria-label={t("preview_volume")}
					className={styles.volumeSlider}
					min={0}
					max={100}
					value={volume}
					disabled={!ready}
					onChange={(_event, data) => {
						setVolume(data.value);
						if (audio.current !== null) audio.current.volume = data.value / 100;
					}}
				/>
			</div>

			{failed ? <Text size={200}>{t("preview_error")}</Text> : null}
		</div>
	);
}
