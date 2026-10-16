import {
	Card,
	CardHeader,
	Field,
	Input,
	makeStyles,
	Title3,
	tokens,
} from "@fluentui/react-components";
import { useCallback, useEffect, useRef, useState } from "react";

import { prepare } from "../../shared/audio/prepare";
import { useLanguage } from "../../shared/i18n/context";
import type { OutputTracks } from "../../shared/jobs";
import { backingName, DEFAULT_STRENGTH } from "../../shared/jobs";
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
import type { ResultTrack } from "../../shared/ui/ResultPanel";
import { ResultPanel } from "../../shared/ui/ResultPanel";
import { analyze, estimate, request } from "./job";
import { ParametersCard } from "./ParametersCard";
import { SourcesCard } from "./SourcesCard";
import { StatusCard } from "./StatusCard";
import { TimelineCard } from "./TimelineCard";
import { useOutputName } from "./useOutputName";

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

	const [stage, setStage] = useState<PreparedFile | null>(null);
	const [sources, setSources] = useState<PreparedFile[]>([]);
	const [selectedSource, setSelectedSource] = useState<string | null>(null);
	const [analysis, setAnalysis] = useState<Analysis | null>(null);
	const output = useOutputName();
	const outputName = output.name;
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
				if (!output.typed || output.name.trim() === "") {
					output.rename(prepared, tracks);
				}
			} catch (error) {
				setProblem(error instanceof Error ? error.message : String(error));
			} finally {
				setPreparing(null);
			}
		},
		[output.name, output.rename, output.typed, tracks, upload],
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
				setSources((current) => [...current, ...added]);
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
			setSources((current) => current.filter((source) => source.path !== path));
			setSelectedSource((current) => (current === path ? null : current));
			setAnalysis(null);
			setResult([]);
			setNotice(null);
			await client.remove(path);
		},
		[client],
	);

	// Exporting both stems keeps one more file in the browser filesystem, which
	// is the same heap the budget is measured against.  Only the answer for the
	// inputs still on the page may land: an estimate for a source list that has
	// since changed would unblock, or block, the wrong job.
	useEffect(() => {
		if (stage === null || sources.length === 0) {
			setBudget(null);
			return;
		}
		let current = true;
		estimate(client, stage, sources, tracks).then(
			(next) => current && setBudget(next),
			() => current && setBudget(null),
		);
		return () => {
			current = false;
		};
	}, [client, sources, stage, tracks]);

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
		// The table, and with it this button, only exists once there is a timeline.
		if (analysis === null) return;
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
		// The selected source, as on the desktop, where the list's current row is.
		const index = Math.max(
			0,
			sources.findIndex((source) => source.path === selectedSource),
		);
		const source = sources[index];
		const clip: TimelineClip = {
			kind: "song",
			stage_start: gap.stage_start,
			stage_end: gap.stage_start + length,
			source: source.path,
			source_index: index,
			source_start: 0,
			source_end: length,
			confidence: 0,
			enabled: true,
			manual: true,
			speed: 1,
		};
		void mutate("add_timeline_clip", { analysis, clip }, "stage_manual_added");
	}, [analysis, mutate, selectedSource, sources, t]);

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
							output.type(data.value);
							setResult([]);
						}}
						onBlur={() => output.settle(stage, tracks)}
					/>
				</Field>
			</Card>

			<SourcesCard
				sources={sources}
				selected={selectedSource}
				disabled={!ready || busy}
				onAdd={(files) => void addSources(files)}
				onSelect={setSelectedSource}
				onRemove={(path) => void removeSource(path)}
			/>

			<ParametersCard
				tracks={tracks}
				strength={strength}
				budget={budget}
				disabled={busy}
				onTracks={(next) => {
					setTracks(next);
					setResult([]);
					if (stage !== null && !output.typed) output.rename(stage, next);
				}}
				onStrength={setStrength}
			/>

			<StatusCard
				state={state}
				preparing={preparing}
				notice={notice}
				problem={problem}
				missing={ready ? missing : null}
				canStart={canStart}
				canAnalyze={canAnalyze}
				onStart={() => {
					reset();
					void run();
				}}
				onAnalyze={() => {
					reset();
					void findSongs();
				}}
				onCancel={() => void cancel()}
			/>

			<TimelineCard
				analysis={analysis}
				hasInputs={stage !== null && sources.length > 0}
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
