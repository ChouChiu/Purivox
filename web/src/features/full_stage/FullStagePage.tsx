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
	Switch,
	Text,
	Title3,
	tokens,
} from "@fluentui/react-components";
import { useCallback, useEffect, useRef, useState } from "react";

import { prepare } from "../../shared/audio/prepare";
import { useLanguage } from "../../shared/i18n/context";
import type { OutputTracks } from "../../shared/jobs";
import {
	backingName,
	DEFAULT_STRENGTH,
	OUTPUT_TRACKS,
	STRENGTH_MAXIMUM,
	STRENGTH_MINIMUM,
} from "../../shared/jobs";
import type { PurivoxClient } from "../../shared/runtime/PurivoxClient";
import type { Shortcuts } from "../../shared/runtime/shortcuts";
import type {
	Analysis,
	AnalysisResult,
	Estimate,
	PreparedFile,
	RenderResult,
	TimelineClip,
} from "../../shared/runtime/types";
import { useJob } from "../../shared/runtime/useJob";
import { AudioSummary } from "../../shared/ui/AudioSummary";
import { FilePicker } from "../../shared/ui/FilePicker";
import { JobPanel } from "../../shared/ui/JobPanel";
import { MemoryNotice } from "../../shared/ui/MemoryNotice";
import type { ResultTrack } from "../../shared/ui/ResultPanel";
import { ResultPanel } from "../../shared/ui/ResultPanel";
import { estimate, request } from "./job";
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

export function FullStagePage({ client, ready, active, onBind }: Props) {
	const styles = useStyles();
	const { t } = useLanguage();
	const { state, start, cancel, reset } = useJob(client);

	const [stage, setStage] = useState<PreparedFile | null>(null);
	const [sources, setSources] = useState<PreparedFile[]>([]);
	const [analysis, setAnalysis] = useState<Analysis | null>(null);
	const [outputName, setOutputName] = useState("purivox-stage.wav");
	const [strength, setStrength] = useState(DEFAULT_STRENGTH);
	const [includeFragments, setIncludeFragments] = useState(true);
	const [budget, setBudget] = useState<Estimate | null>(null);
	const [notice, setNotice] = useState<string | null>(null);
	const [problem, setProblem] = useState<string | null>(null);
	const [tracks, setTracks] = useState<OutputTracks>("vocal");
	const [result, setResult] = useState<readonly ResultTrack[]>([]);

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

	const pickStage = useCallback(
		async (file: File) => {
			setProblem(null);
			setNotice(t("web_uploading", { name: file.name }));
			try {
				const prepared = await prepare(client, file, 0, (fraction) => {
					setNotice(
						t("web_uploading_percent", {
							name: file.name,
							percent: Math.round(fraction * 100),
						}),
					);
				});
				setStage(prepared);
				// A new recording invalidates a timeline built against the old one.
				setAnalysis(null);
				await refreshEstimate(prepared, sources);
			} catch (error) {
				setProblem(error instanceof Error ? error.message : String(error));
			} finally {
				setNotice(null);
			}
		},
		[client, refreshEstimate, sources, t],
	);

	const addSources = useCallback(
		async (files: File[]) => {
			setProblem(null);
			const added: PreparedFile[] = [];
			try {
				for (const [offset, file] of files.entries()) {
					setNotice(t("web_uploading", { name: file.name }));
					added.push(
						await prepare(
							client,
							file,
							sources.length + offset + 1,
							(fraction) => {
								setNotice(
									t("web_uploading_percent", {
										name: file.name,
										percent: Math.round(fraction * 100),
									}),
								);
							},
						),
					);
				}
			} catch (error) {
				setProblem(error instanceof Error ? error.message : String(error));
			} finally {
				setNotice(null);
			}
			const next = [...sources, ...added];
			setSources(next);
			setAnalysis(null);
			await refreshEstimate(stage, next);
		},
		[client, refreshEstimate, sources, stage, t],
	);

	const removeSource = useCallback(
		async (path: string) => {
			const next = sources.filter((source) => source.path !== path);
			setSources(next);
			setAnalysis(null);
			await client.remove(path);
			await refreshEstimate(stage, next);
		},
		[client, refreshEstimate, sources, stage],
	);

	const jobRequest = useCallback(
		() =>
			request(stage, sources, outputName, strength, includeFragments, tracks),
		[includeFragments, outputName, sources, stage, strength, tracks],
	);

	const analyze = useCallback(async () => {
		setResult([]);
		const payload = await start<AnalysisResult>("analyze_stage", jobRequest());
		if (payload !== null) setAnalysis(payload.analysis);
	}, [jobRequest, start]);

	const render = useCallback(async () => {
		if (analysis === null) return;
		setResult([]);
		const payload = await start<RenderResult>("render_stage", {
			...jobRequest(),
			analysis,
		});
		if (payload === null) return;
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
			// the same heap the render just worked in.
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

	/** Every timeline edit goes back through the matching rules, not around them. */
	const mutate = useCallback(
		async (name: string, request: unknown) => {
			setProblem(null);
			try {
				const payload = await client.call<AnalysisResult>(name, request);
				setAnalysis(payload.analysis);
				setNotice(t("stage_manual_updated"));
			} catch (error) {
				setProblem(
					error instanceof Error ? error.message : t("stage_invalid_edit"),
				);
			}
		},
		[client, t],
	);

	const addClip = useCallback(() => {
		if (analysis === null || sources.length === 0) return;
		// Drop a new clip into the first unidentified stretch, the way the desktop
		// does, and let the user correct its times afterwards.
		const gap = analysis.clips.find((clip) => clip.kind === "unmatched");
		if (gap === undefined) {
			setProblem(t("stage_no_room_for_clip"));
			return;
		}
		const length = Math.min(
			gap.stage_end - gap.stage_start,
			sources[0].probe.seconds ?? 0,
		);
		const clip: TimelineClip = {
			kind: "song",
			stage_start: gap.stage_start,
			stage_end: gap.stage_start + length,
			source: sources[0].path,
			source_index: 0,
			source_start: 0,
			source_end: length,
			confidence: 0,
			enabled: true,
			manual: true,
		};
		void mutate("add_timeline_clip", { analysis, clip });
	}, [analysis, mutate, sources, t]);

	const openStage = useRef<(() => void) | null>(null);
	const togglePreview = useRef<(() => void) | null>(null);
	// The desktop names what is missing rather than only disabling the button.
	const missing =
		stage === null
			? "stage_need_audio"
			: sources.length === 0
				? "stage_need_sources"
				: analysis === null
					? "stage_need_analysis"
					: null;
	const blocked = budget !== null && !budget.fits;
	const hasInputs = stage !== null && sources.length > 0;
	const busy = state.running || notice !== null;

	useEffect(() => {
		if (!active) return;
		onBind({
			choose: () => openStage.current?.(),
			start: () => {
				if (ready && hasInputs && analysis !== null && !blocked && !busy) {
					reset();
					void render();
				}
			},
			cancel: () => void cancel(),
			togglePreview: () => togglePreview.current?.(),
			analyze: () => {
				if (ready && hasInputs && !busy) {
					reset();
					void analyze();
				}
			},
		});
	}, [
		active,
		analysis,
		analyze,
		blocked,
		busy,
		cancel,
		hasInputs,
		onBind,
		ready,
		render,
		reset,
	]);

	return (
		<div className={styles.page}>
			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("stage_files")}</Title3>} />
				<FilePicker
					label={t("stage_audio")}
					registerOpen={(open) => {
						openStage.current = open;
					}}
					value={stage?.label ?? null}
					detail={stage === null ? undefined : <AudioSummary file={stage} />}
					disabled={!ready || busy}
					onPick={([file]) => void pickStage(file)}
				/>
				<FilePicker
					label={t("stage_sources")}
					hint={t("stage_sources_hint")}
					value={sources.length > 0 ? `${sources.length}` : null}
					multiple
					disabled={!ready || busy}
					onPick={(files) => void addSources(files)}
				/>
				<div className={styles.sources}>
					{sources.map((source) => (
						<div className={styles.source} key={source.path}>
							<div className={styles.sourceText}>
								<Text truncate title={source.label}>
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
				<Field label={t("output_file")} hint={t("web_output_hint")}>
					<Input
						value={outputName}
						disabled={busy}
						onChange={(_event, data) => setOutputName(data.value)}
					/>
				</Field>
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("params")}</Title3>} />
				<Field label={t("output_tracks")}>
					<Select
						value={tracks}
						disabled={busy}
						onChange={(_event, data) => {
							setTracks(data.value as OutputTracks);
							setResult([]);
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
				<Switch
					label={`${t("stage_include_fragments")} ${includeFragments ? t("switch_on") : t("switch_off")}`}
					checked={includeFragments}
					disabled={busy}
					onChange={(_event, data) => setIncludeFragments(data.checked)}
				/>
				<MemoryNotice estimate={budget} />
			</Card>

			<Card className={styles.card}>
				<CardHeader header={<Title3>{t("stage_timeline")}</Title3>} />
				<Text className={styles.hint}>{t("stage_timeline_hint")}</Text>
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
				) : null}
				{analysis === null ? (
					<Text className={styles.hint}>
						{hasInputs ? t("stage_need_analysis") : t("stage_ready")}
					</Text>
				) : (
					<Timeline
						analysis={analysis}
						disabled={busy}
						onEdit={(index, changes) =>
							void mutate("edit_timeline_clip", { analysis, index, changes })
						}
						onAdd={addClip}
						onRemove={(index) =>
							void mutate("remove_timeline_clip", { analysis, index })
						}
					/>
				)}
				<JobPanel
					state={state}
					startLabel={t("stage_start")}
					blockedBy={ready ? missing : null}
					canStart={
						ready && hasInputs && analysis !== null && !blocked && !busy
					}
					onStart={() => {
						reset();
						void render();
					}}
					onCancel={() => void cancel()}
				>
					<Button
						disabled={!ready || !hasInputs || busy}
						onClick={() => {
							reset();
							void analyze();
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
