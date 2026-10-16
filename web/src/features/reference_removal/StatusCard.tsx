import {
	Button,
	Card,
	CardHeader,
	MessageBar,
	MessageBarBody,
	makeStyles,
	Title3,
	tokens,
} from "@fluentui/react-components";

import { useLanguage } from "../../shared/i18n/context";
import type { JobState } from "../../shared/runtime/useJob";
import { JobPanel } from "../../shared/ui/JobPanel";

const useStyles = makeStyles({
	card: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
	},
});

interface Props {
	state: JobState;
	/** An upload in progress, a note about the last edit, and the last failure. */
	preparing: string | null;
	notice: string | null;
	problem: string | null;
	/** The warning key naming the input Start is waiting for, if any. */
	missing: string | null;
	canStart: boolean;
	canAnalyze: boolean;
	onStart(): void;
	onAnalyze(): void;
	onCancel(): void;
}

/**
 * Where the page reports and where a job starts, as the desktop's status card.
 *
 * It follows the parameters, which is where filling in the form ends, so
 * starting never needs a scroll past the timeline and the result.
 */
export function StatusCard({
	state,
	preparing,
	notice,
	problem,
	missing,
	canStart,
	canAnalyze,
	onStart,
	onAnalyze,
	onCancel,
}: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const messages = [
		{ intent: "info", text: preparing },
		{ intent: "info", text: notice },
		{ intent: "error", text: problem },
	] as const;

	return (
		<Card className={styles.card}>
			<CardHeader header={<Title3>{t("status_group")}</Title3>} />
			{messages.map(({ intent, text }) =>
				text === null ? null : (
					<MessageBar key={`${intent}:${text}`} intent={intent}>
						<MessageBarBody>{text}</MessageBarBody>
					</MessageBar>
				),
			)}
			<JobPanel
				state={state}
				startLabel={t("start")}
				blockedBy={missing}
				canStart={canStart}
				onStart={onStart}
				onCancel={onCancel}
			>
				<Button disabled={!canAnalyze} onClick={onAnalyze}>
					{t("stage_analyze")}
				</Button>
			</JobPanel>
		</Card>
	);
}
