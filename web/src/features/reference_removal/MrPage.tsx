import {
	Button,
	Card,
	CardHeader,
	Field,
	Input,
	MessageBar,
	MessageBarBody,
	makeStyles,
	Select,
	Slider,
	Text,
	Title3,
	tokens,
} from "@fluentui/react-components";
import { useCallback, useEffect, useRef, useState } from "react";

import { prepare } from "../../shared/audio/prepare";
import { useLanguage } from "../../shared/i18n/context";
import type { OutputTracks } from "../../shared/jobs";
import {
	BACKING_MARKER,
	backingName,
	DEFAULT_STRENGTH,
	OUTPUT_TRACKS,
	STRENGTH_MAXIMUM,
	STRENGTH_MINIMUM,
	VOCAL_MARKER,
} from "../../shared/jobs";
import type { PurivoxClient } from "../../shared/runtime/PurivoxClient";
import type { Shortcuts } from "../../shared/runtime/shortcuts";
import type {
	Analysis,
	AnalysisResult,
	Estimate,
	IsolationResult,
	PreparedFile,
	TimelineClip,
} from "../../shared/runtime/types";
import { useJob } from "../../shared/runtime/useJob";
import { AudioSummary } from "../../shared/ui/AudioSummary";
import { FilePicker } from "../../shared/ui/FilePicker";
import { JobPanel } from "../../shared/ui/JobPanel";
import { MemoryNotice } from "../../shared/ui/MemoryNotice";
import type { ResultTrack } from "../../shared/ui/ResultPanel";
import { ResultPanel } from "../../shared/ui/ResultPanel";
import { analyze, estimate, request } from "./job";
import { Timeline } from "./Timeline";

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
	sources: {
		display: "flex",
		flexDirection: "column",
		gap: tokens.spacingVerticalXS,
	},
	source: {
		display: "flex",
		justifyContent: "space-between",
		alignItems: "center",
		gap: tokens.spacingHorizontalS,
		minWidth: 0,
	},
	sourceText: { display: "flex", flexDirection: "column", minWidth: 0 },
	hint: { color: tokens.colorNeutralForeground3 },
});

interface Props {
	client: PurivoxClient;
	ready: boolean;
	/** Whether this page is the one on screen; only it owns the shortcuts. */
	active: boolean;
	/** Register what the window shortcuts do while this page is on screen. */
	onBind(shortcuts: Shortcuts): void;
}

/** The desktop names the output after the recording, so the browser does too. */
function defaultOutputName(stage: PreparedFile, tracks: OutputTracks): string {
	const marker = tracks === "backing" ? BACKING_MARKER : VOCAL_MARKER;
	const dot = stage.label.lastIndexOf(".");
	const stem = dot > 0 ? stage.label.slice(0, dot) : stage.label;
	return `${stem}${marker}.wav`;
}

/** The desktop's `normalized_wav_path` makes every output a `.wav`. */
function normalizedOutputName(text: string): string {
	const trimmed = text.trim();
	return trimmed.toLowerCase().endsWith(".wav") ? trimmed : `${trimmed}.wav`;
}

export function MrPage({ client, ready, active, onBind }: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const { state, start, cancel, reset } = useJob(client);

	const [stage, setStage] = useState<PreparedFile | null>(null);
	const [sources, setSources] = useState<PreparedFile[]>([]);
	const [analysis, setAnalysis] = useState<Analysis | null>(null);
	const [outputName, setOutputName] = useState("");
	const [outputEdited, setOutputEdited] = useState(false);
	const [strength, setStrength] = useState(DEFAULT_STRENGTH);
	const [budget, setBudget] = useState<Estimate | null>(null);
	const [preparing, setPreparing] = useState<string | null>(null);
	const [notice, setNotice] = useState<string | null>(null);
	const [problem, setProblem] = useState<string | null>(null);
	const [tracks, setTracks] = useState<OutputTracks>("vocal");
	const [result, setResult] = useState<readonly ResultTrack[]>([]);
	// Uploaded names are prefixed with this, so a removed source must not let a
	// later file reuse its path in the runtime's filesystem.
	const nextIndex = useRef(1);

	const upload = useCallback(
		async (file: File, index: number): Promise<PreparedFile> => {
			setPreparing(t("web_uploading", { name: file.name }));
			return prepare(client, file, index, (fraction) => {
				setPreparing(
					t("web_uploading_percent", {
						name: file.name,
						percent: Math.round(fraction * 100),
					}),
				);
			});
		},
		[client, t],
	);

	const pickStage = useCallback(
		async (file: File) => {
			setProblem(null);
			try {
				const prepared = await upload(file, 0);
				setStage(prepared);
				setAnalysis(null);
				setResult([]);
				if (!outputEdited || outputName.trim() === "") {
					setOutputName(defaultOutputName(prepared, tracks));
					setOutputEdited(false);
				}
			} catch (error) {
				setProblem(error instanceof Error ? error.message : String(error));
			} finally {
				setPreparing(null);
			}
		},
		[outputEdited, outputName, tracks, upload],
	);

	const addSources = useCallback(
		async (files: File[]) => {
			setProblem(null);
			// A browser file has no path to compare, so name and size are the
			// identity a repeated pick can be recognised by.
			const seen = new Set(
				sources.map((source) => `${source.label}:${source.bytes}`),
			);
			const added: PreparedFile[] = [];
			let failed = false;
			try {
				for (const file of files) {
					const key = `${file.name}:${file.size}`;
					if (seen.has(key)) continue;
					seen.add(key);
					added.push(await upload(file, nextIndex.current++));
				}
			} catch (error) {
				failed = true;
				setProblem(error instanceof Error ? error.message : String(error));
			} finally {
				setPreparing(null);
			}
			if (added.length > 0) {
				setSources([...sources, ...added]);
				setAnalysis(null);
				setResult([]);
				setNotice(null);
			} else if (files.length > 0 && !failed) {
				setNotice(t("source_already_added"));
			}
		},
		[sources, t, upload],
	);

	const removeSource = useCallback(
		async (path: string) => {
			setProblem(null);
			setSources(sources.filter((source) => source.path !== path));
			setAnalysis(null);
			setResult([]);
			setNotice(null);
			await client.remove(path);
		},
		[client, sources],
	);

	const refreshEstimate = useCallback(
		async (recording: PreparedFile | null, songs: PreparedFile[]) => {
			setBudget(
				recording !== null && songs.length > 0
					? await estimate(client, recording, songs, tracks)
					: null,
			);
		},
		[client, tracks],
	);

	// Exporting both stems keeps one more file in the browser filesystem, which
	// is the same heap the budget is measured against.
	useEffect(() => {
		void refreshEstimate(stage, sources);
	}, [refreshEstimate, sources, stage]);

	const jobRequest = useCallback(
		() => request(stage, sources, outputName, strength, tracks),
		[outputName, sources, stage, strength, tracks],
	);

	const run = useCallback(async () => {
		setResult([]);
		setNotice(null);
		setProblem(null);
		const payload = await start<IsolationResult>("run_isolation", {
			...jobRequest(),
			// Without a timeline the pipeline matches the sources itself, and
			// falls back to cancelling the recording as a whole.
			...(analysis === null ? {} : { analysis }),
		});
		if (payload === null) return;
		setAnalysis(payload.analysis);
		const names =
			tracks === "both" ? [outputName, backingName(outputName)] : [outputName];
		const titles =
			tracks === "both"
				? ["track_vocal", "track_backing"]
				: [tracks === "backing" ? "track_backing" : "track_vocal"];
		const downloaded: ResultTrack[] = [];
		for (const [index, path] of payload.outputs.entries()) {
			const blob = await client.download(path);
			// Drop the runtime's copy before fetching the next: the filesystem is
			// the same heap the job just worked in.
			await client.remove(path);
			downloaded.push({
				blob,
				filename: names[index],
				titleKey: titles[index],
				stats: payload.audio_stats[index],
			});
		}
		setResult(downloaded);
	}, [analysis, client, jobRequest, outputName, start, tracks]);

	const findSongs = useCallback(async () => {
		setNotice(null);
		setProblem(null);
		setResult([]);
		setAnalysis(null);
		const payload = await analyze(start, jobRequest());
		if (payload !== null) setAnalysis(payload.analysis);
	}, [jobRequest, start]);

	/** Every timeline edit goes back through the matching rules, not around them. */
	const mutate = useCallback(
		async (name: string, payload: unknown, messageKey: string) => {
			setProblem(null);
			try {
				const next = await client.call<AnalysisResult>(name, payload);
				setAnalysis(next.analysis);
				setNotice(t(messageKey));
			} catch (error) {
				setProblem(
					error instanceof Error ? error.message : t("stage_invalid_edit"),
				);
			}
		},
		[client, t],
	);

	const addClip = useCallback(() => {
		if (analysis === null) {
			setNotice(t("stage_need_analysis"));
			return;
		}
		// Start inside the first gap the matcher left, which is where a spliced
		// backing track's missing pieces almost always belong.
		const gap = analysis.clips.find((clip) => clip.kind === "unmatched");
		if (gap === undefined) {
			setNotice(t("stage_no_room_for_clip"));
			return;
		}
		const length = Math.min(30, gap.stage_end - gap.stage_start);
		if (length <= 0) {
			setNotice(t("stage_no_room_for_clip"));
			return;
		}
		const source = sources[0];
		const clip: TimelineClip = {
			kind: "song",
			stage_start: gap.stage_start,
			stage_end: gap.stage_start + length,
			source: source.path,
			source_index: 0,
			source_start: 0,
			source_end: length,
			confidence: 0,
			enabled: true,
			manual: true,
			speed: 1,
		};
		void mutate("add_timeline_clip", { analysis, clip }, "stage_manual_added");
	}, [analysis, mutate, sources, t]);

	const openStage = useRef<(() => void) | null>(null);
	const togglePreview = useRef<(() => void) | null>(null);
	// The desktop names the missing input rather than only disabling Start.
	const missing =
		stage === null
			? "warn_no_stage"
			: sources.length === 0
				? "warn_no_source"
				: outputName.trim() === ""
					? "warn_no_out"
					: null;
	const blocked = budget !== null && !budget.fits;
	const busy = state.running || preparing !== null;
	const canStart = ready && missing === null && !blocked && !busy;
	// Analysing allocates far less than rendering, so the render estimate does
	// not block it.
	const canAnalyze = ready && missing === null && !busy;
	const hasInputs = stage !== null && sources.length > 0;

	useEffect(() => {
		if (!active) return;
		onBind({
			choose: () => openStage.current?.(),
			start: () => {
				if (canStart && !state.running) {
					reset();
					void run();
				}
			},
			cancel: () => void cancel(),
			togglePreview: () => togglePreview.current?.(),
			analyze: () => {
				if (canAnalyze) {
					reset();
					void findSongs();
				}
			},
		});
	}, [
		active,
		canAnalyze,
		canStart,
		cancel,
		findSongs,
		onBind,
		reset,
		run,
		state.running,
	]);

	return (
		<div className={styles.page}>
			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("file_select")}</Title3>} />
				<FilePicker
					label={t("mr_audio_label")}
					registerOpen={(open) => {
						openStage.current = open;
					}}
					value={stage?.label ?? null}
					detail={stage === null ? undefined : <AudioSummary file={stage} />}
					disabled={!ready || busy}
					onPick={([file]) => void pickStage(file)}
				/>
				<Field label={t("output_file")} hint={t("web_output_hint")}>
					<Input
						value={outputName}
						placeholder={t("output_name_hint")}
						disabled={busy}
						onChange={(_event, data) => {
							setOutputName(data.value);
							setOutputEdited(true);
							setResult([]);
						}}
						onBlur={() => {
							if (stage !== null && outputName.trim() === "") {
								setOutputName(defaultOutputName(stage, tracks));
								setOutputEdited(false);
							} else if (outputName.trim() !== "") {
								setOutputName(normalizedOutputName(outputName));
							}
						}}
					/>
				</Field>
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("sources_title")}</Title3>} />
				<Text className={styles.hint}>{t("stage_sources_hint")}</Text>
				<FilePicker
					label={t("stage_add_sources")}
					value={sources.length > 0 ? `${sources.length}` : null}
					multiple
					disabled={!ready || busy}
					onPick={(files) => void addSources(files)}
				/>
				<div className={styles.sources}>
					{sources.map((source) => (
						<div className={styles.source} key={source.path}>
							<div className={styles.sourceText}>
								<Text truncate title={source.path}>
									{source.label}
								</Text>
								<AudioSummary file={source} />
							</div>
							<Button
								size="small"
								appearance="subtle"
								disabled={busy}
								onClick={() => void removeSource(source.path)}
							>
								{t("stage_remove_source")}
							</Button>
						</div>
					))}
				</div>
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("params")}</Title3>} />
				<Field label={t("output_tracks")}>
					<Select
						value={tracks}
						disabled={busy}
						onChange={(_event, data) => {
							const next = data.value as OutputTracks;
							setTracks(next);
							setResult([]);
							if (!outputEdited && stage !== null) {
								setOutputName(defaultOutputName(stage, next));
							}
						}}
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
						disabled={busy}
						onChange={(_event, data) => setStrength(data.value)}
					/>
				</Field>
				<MemoryNotice estimate={budget} />
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("stage_timeline")}</Title3>} />
				<Text className={styles.hint}>{t("stage_timeline_hint")}</Text>
				{analysis !== null ? (
					<Text className={styles.hint}>
						{t("stage_analysis_summary", {
							songs: analysis.clips.filter((clip) => clip.kind === "song")
								.length,
							fragments: analysis.clips.filter(
								(clip) => clip.kind === "fragment",
							).length,
							missing: analysis.missing_sources.length,
						})}
					</Text>
				) : hasInputs ? (
					<Text className={styles.hint}>{t("stage_need_analysis")}</Text>
				) : null}
				{analysis === null ? null : (
					<Timeline
						analysis={analysis}
						disabled={busy}
						onEdit={(index, changes) =>
							void mutate(
								"edit_timeline_clip",
								{ analysis, index, changes },
								"stage_manual_updated",
							)
						}
						onAdd={addClip}
						onRemove={(index) =>
							void mutate(
								"remove_timeline_clip",
								{ analysis, index },
								"stage_manual_removed",
							)
						}
					/>
				)}
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("status_group")}</Title3>} />
				{preparing !== null ? (
					<MessageBar intent="info">
						<MessageBarBody>{preparing}</MessageBarBody>
					</MessageBar>
				) : null}
				{notice !== null ? (
					<MessageBar intent="info">
						<MessageBarBody>{notice}</MessageBarBody>
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
					blockedBy={ready ? missing : null}
					canStart={canStart}
					onStart={() => {
						reset();
						void run();
					}}
					onCancel={() => void cancel()}
				>
					<Button
						disabled={!canAnalyze}
						onClick={() => {
							reset();
							void findSongs();
						}}
					>
						{t("stage_analyze")}
					</Button>
				</JobPanel>
			</Card>

			<ResultPanel
				tracks={result}
				placeholderName={outputName}
				registerToggle={(toggle) => {
					togglePreview.current = toggle;
				}}
			/>
		</div>
	);
}
