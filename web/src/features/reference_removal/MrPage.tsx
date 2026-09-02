import {
	Card,
	CardHeader,
	Field,
	Input,
	MessageBar,
	MessageBarBody,
	makeStyles,
	Slider,
	Title3,
	tokens,
} from "@fluentui/react-components";
import { useCallback, useEffect, useRef, useState } from "react";

import { prepare } from "../../shared/audio/prepare";
import { useLanguage } from "../../shared/i18n/context";
import {
	DEFAULT_STRENGTH,
	STRENGTH_MAXIMUM,
	STRENGTH_MINIMUM,
} from "../../shared/jobs";
import type { PurivoxClient } from "../../shared/runtime/PurivoxClient";
import type { Shortcuts } from "../../shared/runtime/shortcuts";
import type {
	AudioStats,
	Estimate,
	PreparedFile,
	ReferenceResult,
} from "../../shared/runtime/types";
import { useJob } from "../../shared/runtime/useJob";
import { AudioSummary } from "../../shared/ui/AudioSummary";
import { FilePicker } from "../../shared/ui/FilePicker";
import { JobPanel } from "../../shared/ui/JobPanel";
import { MemoryNotice } from "../../shared/ui/MemoryNotice";
import { ResultPanel } from "../../shared/ui/ResultPanel";
import { estimate, request } from "./job";

const useStyles = makeStyles({
	page: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalL,
	},
	card: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalM,
	},
});

interface Props {
	client: PurivoxClient;
	ready: boolean;
	/** Whether this page is the one on screen; only it owns the shortcuts. */
	active: boolean;
	/** Register what the window shortcuts do while this page is on screen. */
	onBind(shortcuts: Shortcuts): void;
}

export function MrPage({ client, ready, active, onBind }: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const { state, start, cancel, reset } = useJob(client);

	const [song, setSong] = useState<PreparedFile | null>(null);
	const [accompaniment, setAccompaniment] = useState<PreparedFile | null>(null);
	const [outputName, setOutputName] = useState("purivox.wav");
	const [strength, setStrength] = useState(DEFAULT_STRENGTH);
	const [budget, setBudget] = useState<Estimate | null>(null);
	const [preparing, setPreparing] = useState<string | null>(null);
	const [problem, setProblem] = useState<string | null>(null);
	const [result, setResult] = useState<{
		blob: Blob;
		stats?: AudioStats;
	} | null>(null);

	const pick = useCallback(
		async (
			file: File,
			index: number,
			keep: (prepared: PreparedFile) => void,
		) => {
			setProblem(null);
			setPreparing(t("web_uploading", { name: file.name }));
			try {
				keep(
					await prepare(client, file, index, (fraction) => {
						setPreparing(
							t("web_uploading_percent", {
								name: file.name,
								percent: Math.round(fraction * 100),
							}),
						);
					}),
				);
			} catch (error) {
				setProblem(error instanceof Error ? error.message : String(error));
			} finally {
				setPreparing(null);
			}
		},
		[client, t],
	);

	const refreshEstimate = useCallback(
		async (first: PreparedFile | null, second: PreparedFile | null) => {
			setBudget(
				first !== null && second !== null
					? await estimate(client, first, second)
					: null,
			);
		},
		[client],
	);

	const run = useCallback(async () => {
		if (song === null || accompaniment === null) return;
		setResult(null);
		const payload = await start<ReferenceResult>(
			"run_reference",
			request(song, accompaniment, outputName, strength),
		);
		if (payload === null) return;
		const blob = await client.download(payload.outputs[0]);
		// The rendered file is now a Blob the browser owns; drop the runtime's copy
		// so a second run does not hold two of them.
		await client.remove(payload.outputs[0]);
		setResult({ blob, stats: payload.audio_stats[0] });
	}, [accompaniment, client, outputName, song, start, strength]);

	const openSong = useRef<(() => void) | null>(null);
	const togglePreview = useRef<(() => void) | null>(null);
	// The desktop names the missing input rather than only disabling Start.
	const missing =
		song === null
			? "warn_no_song"
			: accompaniment === null
				? "warn_no_acc"
				: outputName.trim() === ""
					? "warn_no_out"
					: null;
	const blocked = budget !== null && !budget.fits;
	const canStart = ready && missing === null && !blocked && preparing === null;

	useEffect(() => {
		if (!active) return;
		onBind({
			choose: () => openSong.current?.(),
			start: () => {
				if (canStart && !state.running) {
					reset();
					void run();
				}
			},
			cancel: () => void cancel(),
			togglePreview: () => togglePreview.current?.(),
		});
	}, [active, canStart, cancel, onBind, reset, run, state.running]);

	return (
		<div className={styles.page}>
			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("mr_single_title")}</Title3>} />
				<FilePicker
					label={t("mr_audio_label")}
					registerOpen={(open) => {
						openSong.current = open;
					}}
					value={song?.label ?? null}
					detail={song === null ? undefined : <AudioSummary file={song} />}
					disabled={!ready || state.running}
					onPick={([file]) =>
						void pick(file, 0, (prepared) => {
							setSong(prepared);
							void refreshEstimate(prepared, accompaniment);
						})
					}
				/>
				<FilePicker
					label={t("acc_label")}
					value={accompaniment?.label ?? null}
					detail={
						accompaniment === null ? undefined : (
							<AudioSummary file={accompaniment} />
						)
					}
					disabled={!ready || state.running}
					onPick={([file]) =>
						void pick(file, 1, (prepared) => {
							setAccompaniment(prepared);
							void refreshEstimate(song, prepared);
						})
					}
				/>
				<Field label={t("output_file")} hint={t("web_output_hint")}>
					<Input
						value={outputName}
						disabled={state.running}
						onChange={(_event, data) => setOutputName(data.value)}
					/>
				</Field>
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("params")}</Title3>} />
				<Field label={`${t("strength")} ${strength}%`}>
					<Slider
						min={STRENGTH_MINIMUM}
						max={STRENGTH_MAXIMUM}
						value={strength}
						disabled={state.running}
						onChange={(_event, data) => setStrength(data.value)}
					/>
				</Field>
				<MemoryNotice estimate={budget} />
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("status_group")}</Title3>} />
				{preparing !== null ? (
					<MessageBar intent="info">
						<MessageBarBody>{preparing}</MessageBarBody>
					</MessageBar>
				) : null}
				{problem !== null ? (
					<MessageBar intent="error">
						<MessageBarBody>{problem}</MessageBarBody>
					</MessageBar>
				) : null}
				<JobPanel
					state={state}
					startLabel={t("start")}
					canStart={canStart}
					blockedBy={ready ? missing : null}
					onStart={() => {
						reset();
						void run();
					}}
					onCancel={() => void cancel()}
				/>
			</Card>

			<ResultPanel
				blob={result?.blob ?? null}
				filename={outputName}
				stats={result?.stats}
				registerToggle={(toggle) => {
					togglePreview.current = toggle;
				}}
			/>
		</div>
	);
}
