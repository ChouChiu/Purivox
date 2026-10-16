import {
	Card,
	CardHeader,
	Field,
	makeStyles,
	Select,
	Slider,
	Title3,
	tokens,
} from "@fluentui/react-components";

import { useLanguage } from "../../shared/i18n/context";
import {
	OUTPUT_TRACKS,
	type OutputTracks,
	STRENGTH_MAXIMUM,
	STRENGTH_MINIMUM,
} from "../../shared/jobs";
import type { Estimate } from "../../shared/runtime/types";
import { MemoryNotice } from "../../shared/ui/MemoryNotice";

const useStyles = makeStyles({
	card: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
	},
});

interface Props {
	tracks: OutputTracks;
	strength: number;
	/** What the job would cost against the tab's memory, once there are inputs. */
	budget: Estimate | null;
	disabled: boolean;
	onTracks(tracks: OutputTracks): void;
	onStrength(strength: number): void;
}

export function ParametersCard({
	tracks,
	strength,
	budget,
	disabled,
	onTracks,
	onStrength,
}: Props) {
	const styles = useStyles();
	const { t } = useLanguage();

	return (
		<Card className={styles.card}>
			<CardHeader header={<Title3>{t("params")}</Title3>} />
			<Field label={t("output_tracks")}>
				<Select
					value={tracks}
					disabled={disabled}
					onChange={(_event, data) => onTracks(data.value as OutputTracks)}
				>
					{OUTPUT_TRACKS.map((choice) => (
						<option key={choice} value={choice}>
							{t(`output_tracks_${choice}`)}
						</option>
					))}
				</Select>
			</Field>
			<Field label={`${t("strength")} ${strength}%`}>
				<Slider
					min={STRENGTH_MINIMUM}
					max={STRENGTH_MAXIMUM}
					value={strength}
					disabled={disabled}
					onChange={(_event, data) => onStrength(data.value)}
				/>
			</Field>
			<MemoryNotice estimate={budget} />
		</Card>
	);
}
