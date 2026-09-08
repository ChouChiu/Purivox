import {
	Button,
	MessageBar,
	MessageBarBody,
	makeStyles,
	ProgressBar,
	Text,
	tokens,
} from "@fluentui/react-components";

import { useLanguage } from "../i18n/context";
import type { JobState } from "../runtime/useJob";

const useStyles = makeStyles({
	panel: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
	},
	actions: {
		display: "flex",
		flexWrap: "wrap",
		gap: tokens.spacingHorizontalS,
	},
	blocked: {
		color: tokens.colorNeutralForeground3,
		fontSize: tokens.fontSizeBase200,
	},
	statusBlock: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalXS,
	},
	statusRow: {
		display: "flex",
		alignItems: "baseline",
		justifyContent: "space-between",
		gap: tokens.spacingHorizontalM,
	},
	statusText: {
		minWidth: 0,
		color: tokens.colorNeutralForeground3,
		fontSize: tokens.fontSizeBase200,
	},
	statusCell: {
		flex: 1,
		minWidth: 0,
	},
	elapsed: {
		flexShrink: 0,
		color: tokens.colorNeutralForeground3,
		fontSize: tokens.fontSizeBase200,
		// Tabular digits keep the readout from jittering as the tenths tick.
		fontVariantNumeric: "tabular-nums",
	},
});

function formatElapsed(milliseconds: number): string {
	const total = Math.max(0, Math.floor(milliseconds));
	const hours = Math.floor(total / 3_600_000);
	const minutes = Math.floor((total % 3_600_000) / 60_000);
	const seconds = Math.floor((total % 60_000) / 1000);
	const millis = total % 1000;
	const pad = (value: number, width = 2) => String(value).padStart(width, "0");
	const stamp = `${pad(minutes)}:${pad(seconds)}.${pad(millis, 3)}`;
	return hours > 0 ? `${hours}:${stamp}` : stamp;
}

interface Props {
	state: JobState;
	startLabel: string;
	canStart: boolean;
	/** Why starting is unavailable, when it is: a translation key. */
	blockedBy?: string | null;
	onStart(): void;
	onCancel(): void;
	children?: React.ReactNode;
}

export function JobPanel({
	state,
	startLabel,
	canStart,
	blockedBy,
	onStart,
	onCancel,
	children,
}: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	// Progress arrives as a catalogue key because the pipelines run without Qt.
	const message =
		state.message === null ? null : t(state.message.key, state.message.values);

	return (
		<div className={styles.panel}>
			<div className={styles.actions}>
				<Button
					appearance="primary"
					disabled={!canStart || state.running}
					onClick={onStart}
				>
					{startLabel}
				</Button>
				<Button disabled={!state.running} onClick={onCancel}>
					{t("cancel")}
				</Button>
				{children}
			</div>
			{!state.running && blockedBy ? (
				<Text className={styles.blocked}>{t(blockedBy)}</Text>
			) : null}
			{state.failure === null && (state.running || state.elapsedMs > 0) ? (
				<div className={styles.statusBlock}>
					<div className={styles.statusRow}>
						<Text
							className={styles.statusText}
							truncate
							wrap={false}
							title={message ?? undefined}
						>
							{message ?? t("ready")}
						</Text>
						<Text className={styles.elapsed}>
							{formatElapsed(state.elapsedMs)}
						</Text>
					</div>
					<ProgressBar value={state.progress / 100} max={1} thickness="large" />
				</div>
			) : null}
			{state.failure !== null ? (
				<div className={styles.statusRow}>
					<MessageBar
						className={styles.statusCell}
						intent={state.failure.kind === "cancelled" ? "info" : "error"}
					>
						<MessageBarBody>
							{state.failure.kind === "cancelled"
								? t("cancelled")
								: t("err_status", { msg: state.failure.message })}
						</MessageBarBody>
					</MessageBar>
					<Text className={styles.elapsed}>
						{formatElapsed(state.elapsedMs)}
					</Text>
				</div>
			) : null}
		</div>
	);
}
