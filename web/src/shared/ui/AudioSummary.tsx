import { Caption1, makeStyles, tokens } from "@fluentui/react-components";
import { formatBytes } from "../audio/prepare";
import { useLanguage } from "../i18n/context";
import type { PreparedFile } from "../runtime/types";
import { duration } from "./duration";

const useStyles = makeStyles({
	summary: { color: tokens.colorNeutralForeground3 },
});

/**
 * What the decoder actually read out of a chosen file.
 *
 * `probe_audio` has always returned this; showing it means a wrong sample rate
 * or a truncated file is visible before a job runs rather than after, and the
 * numbers here are the same ones the memory estimate is computed from.
 */
export function AudioSummary({ file }: { file: PreparedFile }) {
	const styles = useStyles();
	const { t } = useLanguage();
	const { sample_rate: rate, channels, seconds } = file.probe;

	const channelLabel =
		channels === 1
			? t("audio_mono")
			: channels === 2
				? t("audio_stereo")
				: t("audio_channel_count", { count: channels ?? 0 });

	const parts = [
		seconds === undefined ? null : duration(seconds),
		rate === undefined ? null : `${(rate / 1000).toFixed(1)} kHz`,
		channels === undefined ? null : channelLabel,
		formatBytes(file.bytes),
	].filter((part): part is string => part !== null);

	return <Caption1 className={styles.summary}>{parts.join(" · ")}</Caption1>;
}
