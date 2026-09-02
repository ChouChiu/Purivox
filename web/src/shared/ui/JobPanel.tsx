import {
	Button,
	Field,
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
});

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
			{state.running ? (
				<Field validationMessage={message ?? t("ready")} validationState="none">
					<ProgressBar value={state.progress / 100} max={1} thickness="large" />
				</Field>
			) : null}
			{state.failure !== null ? (
				<MessageBar
					intent={state.failure.kind === "cancelled" ? "info" : "error"}
				>
					<MessageBarBody>
						{state.failure.kind === "cancelled"
							? t("cancelled")
							: t("err_status", { msg: state.failure.message })}
					</MessageBarBody>
				</MessageBar>
			) : null}
		</div>
	);
}
