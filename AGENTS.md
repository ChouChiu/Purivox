# Purivox — Repository Guidelines

Purivox (`purivox`): reference-guided vocal isolation for stage and live recordings. Python 3.11+,
PySide6 + PySide6-Fluent-Widgets, AGPL-3.0-or-later. `CLAUDE.md` symlinks here.

This file is the operating manual for anyone changing the code. `README.md` (Chinese) is
authoritative for users; `README_EN.md` and `docs/en/` are its translations, paired file-for-file.
The deeper rationale lives in `docs/` — `architecture.md`, `reference-removal.md`, `matching.md`,
`web.md`, `CONTRIBUTING.md` — each with an English twin. Read this before you edit: most rules below
exist because skipping one cost someone time.

## Working Rules

1. **Never guess an interface.** Read the source or the docs before calling it.
2. **Clarify an ambiguous requirement first.** Ask, get the answer, then write code.
3. **Never invent the workflow.** Unclear product behaviour is confirmed, not reconstructed.
4. **Reuse before you add.** Look in `shared/`, then the feature package.
5. **Never break the architecture for convenience.** The layering is enforced by tests.
6. **Say what you do not know.** Name the gap instead of writing over it.
7. **Map the blast radius before changing logic.** Grep the callers; measure DSP changes.
8. **Test by risk, not by volume.**
9. **Verify before you fix.** Reproduce the problem, do not hypothesise it.
10. **No speculative defensive code.** Handle the boundaries that actually occur.
11. **Comments are short and explain why.**
12. **Do not reinvent the wheel.** Prefer a maintained dependency or what is already in the tree.
13. **Write plainly.** No padding; bold labels a term, it does not make a sentence truer.
14. **Log deliberately.** At a level that matches the event — no silence, no flood.
15. **Never touch git history on your own.** Commit, push, tag and branch wait for an instruction.

## The Product

One pipeline, one workflow over it. The GUI, the CLI and the browser build are shells.

Four names mean one thing each, and the UI strings already use them: the **stage/live recording**
is the file being processed, the **song source** is the released song it is cancelled against, the
**live vocal** is what survives, and the **backing** is the song source as the playback carried it
— the second export track, rendered from the source through the transfer the cancellation
estimated, so it keeps the source's quality instead of the capture's.

Backing is not *accompaniment*. The accompaniment is a song's instrumental; the backing is
whatever of the song source the stage playback actually carried, source vocals included. The code
uses the same names: `IsolationJob.stage` is the stage/live recording, `IsolationJob.sources` are
the song sources, and the CLI positionals follow them. `ReferenceJob` is only the whole-file
engine's input, which is why it still names one `stage` and one `source`.

**Reference cancellation** aligns the stage/live recording against a song source (GCC-PHAT plus
clock-drift tracking), estimates a complex transfer, subtracts the prediction and soft-masks the
residual. The cancellation result *is* the output; there is no spatial post-processing.

One job takes the recording and one or more song sources, and the only operational difference
between one source and twenty is how many you add. The sources are matched against the recording
(`analyze_stage`), and every matched clip is cancelled out of its own stretch of it
(`render_stage_job`). A lone source about as long as the recording *is* the recording's own content
and runs the whole-file path instead (`run_reference_job`), which aligns the pair over its whole
length and corrects a clock difference between them: a capture running at a different tempo is
exactly what stops the matcher placing the source, so the whole-file path keeps 1–2 dB more
cancellation depth where it applies, while the matched clips are 2–4 dB better for a song that
starts inside a longer take. `run_isolation_job` is the one entry point, and the GUI, the CLI and
the browser bridge all call it.

Neural separation was removed in favour of dedicated tools such as UVR5: it carried onnxruntime,
58 MB of the packaged binary, for a workflow that does not use a song source at all. Do not bring it
back.

The **browser build** (`web/`) runs the same pipeline under Pyodide as a static site with no
backend (<https://purivox.wwchun.top/>, `docs/web.md`).

## Layout

```text
src/entrypoints/   cli.py, gui.py — startup only
src/app/           MainWindow, JobPresenter
src/features/      reference_removal, home, settings
src/shared/        audio/, download/, dsp/, ui/, config, i18n, jobs, logging, processing, progress,
                   branding
src/web/           bridge.py (JSON in/out), timeline.py, limits.py — sibling of app
web/               Vite + React + Fluent UI v9, same feature layering, bun
```

Dependencies flow downward only: `shared` imports nothing of ours, features never import each
other, `app`/`web` never import `entrypoints`. `tests/test_architecture.py` and
`web/scripts/check-architecture.mjs` parse the imports and fail the build otherwise. A new
feature is one new directory under `src/features/`. Anything two features — or the GUI and the
CLI — both need moves down into `shared`: `BLOCK_FRAMES`, `AUDIO_EXTENSIONS`,
`validate_reference_settings`, `log_flux_bands`, `AUDIO_FILE_FILTER`, `normalized_wav_path`,
`branding.user_agent`, `OutputTracks`, `export_audio`, `download/`,
`DownloadDialog`.

| Path | What lives there |
|---|---|
| `src/app/` | `main_window.py` (FluentWindow shell: navigation, i18n/theme, the window `QShortcut`s), `job_presenter.py` (page running/progress state; each page shows its own result through `show_result()`), `version.py` |
| `src/features/reference_removal/` | `dsp/algorithms.py` (complex subtraction + residual mask, linked peak protection), `dsp/transfer.py` (smoothed spectra, vectorised LDL^H solve, adjusted multiple coherence), `dsp/alignment.py` (tempo correction + GCC-PHAT + drift tracking + Lanczos warp), `matching.py` (multi-source fingerprint matching, candidate clustering, manual clip edits — `edit_clip` is the one rule the desktop table and the browser timeline both apply), `timeline_model.py` (`QAbstractTableModel` behind the editable timeline, `clip_edited`/`edit_rejected`), `rendering.py` (segmented per-clip render), `processing.py` (both engines and `run_isolation_job`), `outputs.py` (`export_tracks`, how both engines write what `OutputTracks` asked for), `models.py`, `page.py` (inputs, sources, parameters, status with the actions, timeline), `preview.py` (`PreviewCard` player, `AudioDataCard`, `SeekSlider`) |
| `src/features/home/`, `settings/` | Brand and entry cards; language/theme/log level, `updates.py` (GitHub release query + version compare) and `dialog.py`. The app never installs an update — the dialog opens the release page |
| `src/shared/` (root) | `config.py` (the `cfg` `QConfig`), `i18n.py` (`tr()`, `install_language()`, `SUPPORTED_LANGUAGES`), `jobs.py` (the settings contract behind `ReferenceJob`, `IsolationJob` and the CLI: `SIGMA_CHOICES`, `STRENGTH_RANGE`, `validate_reference_settings`, `validate_job_paths`, `OutputTracks`, `planned_outputs`), `logging.py`, `processing.py` (`CancellationToken`, `ProgressEvent`, `ProcessingResult`), `progress.py`, `tasks.py` (`TaskRunner`: the one `QThread` lifecycle, behind jobs and downloads), `branding.py` |
| `src/shared/audio/` | `io.py`: mapped I/O (`AudioData` is a context manager over its mapping), soxr resample and `conform_rate`, atomic WAV write, `BLOCK_FRAMES` (262 144), `AUDIO_EXTENSIONS`, `release_mapped_pages()`; `analysis.py`: `AudioStats`, peak/RMS, block-wise `copy_audio`, `export_audio` |
| `src/shared/download/` | `media.py`: the yt-dlp wrapper — `search()` (`ytsearch`, flat), `fetch()` (best audio, `noplaylist` — a watch URL carrying a radio `list` is hundreds of entries — WAV through ffmpeg when it is there, the container as it arrived when it is not, cancellable in extraction through `match_filter` as well as in transfer through the progress hook), `looks_like_url`, `ffmpeg_available`; `cache.py`: the `downloads.json` index under AppLocalData, so a link is fetched once — matched by video id as well as by URL, because the link pasted is rarely the canonical one recorded; `runner.py`: `DownloadRunner`, a `TaskRunner` that names which answer a result is. YouTube Music is link-only — its search answers with channels, not songs |
| `src/shared/dsp/` | `spectral.py`: librosa-compatible `stft`/`istft` (`n_fft=2048`, `hop=512`) and `log_flux_bands()`, shared by source matching and coarse alignment; `rate.py`: the global tempo scale search the pipeline runs before matching; `stretch.py`: pitch-preserving WSOLA, numpy/scipy only because Pyodide runs the same pipeline |
| `src/shared/ui/` | `responsive.py` (`LayoutMode`/`LayoutMetrics`, `ResponsiveColumns`, `FoldingRow`, `allow_shrinking`, `HeightForWidth`, `ElidedLabel`), `cards.py` (`FormCard`, `PageScrollArea`, `format_clock`), `widgets.py` (`SmoothComboBox`, file filters, `normalized_wav_path`), `download_dialog.py` (the fetch dialog the page opens, imported in the slot rather than at module scope — yt-dlp is a tenth of a second of startup) |
| `src/resources/` | `i18n/{zh_cn,zh_tw,en_us,ja_jp,ko_kr}.{ts,qm}`, `purivox.svg`, `resource_path` |
| `web/scripts/` | `build-python-archive.mjs` (packs `src/` for Pyodide), `build-i18n.mjs`, `build-assets.mjs`, `check-architecture.mjs`. Never a second implementation of the DSP |
| `tests/`, `docs/` | Tests mirror `src/` path-for-path, `benchmarks/` behind `--runslow`; Chinese docs with one translation per file in `docs/en/` |
| `deployment/`, `tools/` | PyInstaller spec, entry script, runtime hook and `smoke.sh` + `.deb`/`.rpm` packaging; `eval_cancellation.py` (DSP A/B), `eval_isolation.py` (pipeline engine A/B), `bench_pipeline.py` (per-phase wall time and peak RSS) |

## Pipelines

**One pipeline, two engines.** `features/reference_removal/processing.py:run_isolation_job` matches
the sources against the recording, then picks the engine by geometry: a lone source about as long as
the recording (within a second) is the recording's own content and runs the whole-file engine;
anything else runs the segmented engine over the clips the matcher placed. Nothing matched with one
source falls back to the whole-file engine; nothing matched with several is an error, because
cancelling a whole show against one song removes the wrong content. A timeline the user checked is
rendered as it stands — an edited timeline is a decision, an untouched one leaves the engine to the
geometry.

**Whole-file** (`run_reference_job`): `read_audio` (SoundFile, Qt Multimedia fallback) → upmix to
stereo → resample the song source to the stage recording's rate (soxr) → optional `align_audio` →
`process_audio` (blocks from the spectral-cell budget, ~45 s at 44.1 kHz, ≥2 s overlap, cos²/sin²
crossfade) → peak/RMS stats → atomic WAV at the stage recording's own rate and bit depth.
`process_audio` has a pooled and an inline schedule because Pyodide has no pthreads;
`dsp/test_algorithms.py` holds them to the same output.

**Segmented** (`render_stage_job`): the recording is read once into the output buffer, then each
enabled clip reads and resamples its source, stretches it by the clip's tempo ratio, aligns the
slice (drift tracking, gated by a direct 2x2 fit that keeps the matcher's position when alignment
would make it worse), cancels with `process_audio` and blends the result in over a 50 ms crossfade.
Ranges no clip covers are copied through untouched, so the backing track is silent exactly where
nothing was cancelled.

**Job lifecycle**: a page emits `start_requested`/`cancel_requested`; `MainWindow` builds the job
dataclass and hands it to `JobPresenter`, which owns page running and progress state, hands the
result to the page's `show_result()`, and delegates to `shared/tasks.py:TaskRunner`, which owns the
`QThread` and emits `progress`/`succeeded`/`failed`/`cancelled`/`finished`. Cancellation is cooperative —
`CancellationToken.raise_if_cancelled()`, never swallowed. The CLI runs the same jobs synchronously
and cancels the token on SIGINT.

## Conventions & Invariants

### Python

- Type hints everywhere (`from __future__ import annotations`, `X | None`, `collections.abc`);
  frozen+slots dataclasses for jobs and config; snake_case, except Qt widget attributes (camelCase).
- Raise `ValueError`/`KeyError`/`FileNotFoundError`/`RuntimeError`. Jobs catch
  `(FileNotFoundError, KeyError, ValueError)` → CLI exit 2, cancellation → 130, anything else →
  exit 1; the GUI shows the worker's `failed` signal in an InfoBar. Never swallow cancellation — a
  documented fallback (alignment failure → `logger.warning`) is the only tolerated swallow.
- `logging.getLogger(__name__)`; single line, `YYYY-MM-DD HH:MM:SS.xx [LEVEL] module: message`
  (`ApplicationLogFormatter`). CLI progress prints `progress: %3d%%`; Qt/FFmpeg route to `qt.*`.

### i18n

- Language is application state, not a job or page parameter: `tr(key, **values)` reads whatever
  `install_language()` installed. Switching it reinstalls the translator, calls each page's
  `retranslate()` and rebuilds the combo boxes.
- An unknown key returns itself — never rely on that. A new or removed key means all five `.ts`
  files plus a `pyside6-lrelease` recompile, committed together; parity, freshness and literal-key
  use are all tested. `zh_tw` is Taiwanese usage, not a character conversion of `zh_cn`
  (檔案/取樣率/辨識, not 文件/采样率/识别); a test pins a few of those terms.
- Search the catalogues before inventing a string: the desktop already named most states
  (`warn_no_source`, `stage_need_sources`, `preview_empty`, the whole `home_*` set), and reuse keeps
  five locales correct for free.
- Progress carries its key and values alongside the translated text (`shared/progress.py`), because
  the browser build runs the same pipelines without Qt and translates on the page.

### Qt

- Qt objects that *borrow* what they are handed read freed memory: a `.qm` buffer given to
  `QTranslator.load()` starts serving another language's strings the moment it is freed. Keep such
  a buffer in a named local or attribute as long as its reader lives.
- Pages declare `Signal()`s and never touch the worker; `MainWindow` connects them. A slot receiving
  a cross-thread signal needs `@Slot(<types>)`, or the queued connection loses the declared
  signature to a generic Python wrapper.
- Prefer the Qt facility where Qt owns the problem: `QAbstractTableModel` + qfw `TableView` over
  `QTableWidget` items, `QNetworkAccessManager` for HTTP (proxy, redirects, `setTransferTimeout`,
  `downloadProgress`, `abort()`), `QSaveFile` for verify-then-commit, `QStandardPaths` for
  locations, `QCoreApplication` for identity. Stdlib stays where it is already equal or better
  (`hashlib`, `tempfile` + `numpy.memmap`, `argparse`, `concurrent.futures`).
- Config is the `cfg` `QConfig` singleton (`shared/config.py`, `config.json` in AppConfigLocation).
  Prefer `SmoothComboBox` and the `shared/ui/` cards; preview is `QMediaPlayer` + `QAudioOutput`.

### Desktop UI

- Shortcuts (`Ctrl+O`, `Ctrl+Return`, `F5`, `Esc`, `Ctrl+P`) live on `MainWindow` and dispatch to
  `current_page()`, never on a page — page-local bindings would be ambiguous, and a window shortcut
  works before a page takes focus. `_apply_shortcut_hints()` appends each binding to
  its button's tooltip, so no shortcut needs a translation key.
- Four `LayoutMode`s by page width: `PORTRAIT` < 620 stacks label over control, `HALF` < 960 and
  `LANDSCAPE` < 1440 stay one column, `ULTRAWIDE` ≥ 1440 splits into two lanes at
  `CONTENT_MAX_WIDTH`; height only sets `LayoutMetrics.short`. `PageScrollArea` measures the
  viewport and pushes metrics down to every `Responsive` child — a widget must never fold on its own
  width, because a page already squeezed is a page cut off and the scroll areas keep
  `ScrollBarAlwaysOff`. Cards join through `add_card(card, lane)`, never `layout.addWidget`.
- A label that can hold a path needs `allow_shrinking()` or its longest word becomes the page
  minimum; paths belong in `ElidedLabel` (one line, full text in `text()` and the tooltip); wrapping
  text needs `HeightForWidth` on every container up to the page, because Qt asks the widget, never
  the layout inside it, whether height follows from width.
- The status card's clock belongs to the presenter, not the page: `start_clock()`/`stop_clock()`
  bracket the job, so a page that never ran one shows nothing and a finished job keeps its total.
  It shares the status line and is reserved the width of `00:00.000`, so it cannot re-elide the
  text beside it as the tenths tick; `format_clock(seconds, millis=True)` is the one formatter,
  and the preview readout keeps the whole-second form of it.
- Files arrive through `QFileDialog` only, funnelled into one method per input (`set_stage`,
  `add_source_paths`) that also does the follow-up — a default output name, an invalidated
  analysis.
- The page's actions (cancel, find songs, start) sit in the status card under the progress bar:
  first in the second lane on a wide window, right after the parameters in one column. A pane
  with nothing to show says what to do instead (the source list, the timeline), and the audio-data
  card stays hidden until a job has written a file.
- Settings strings Fluent words through its own catalogue (switch states, option texts) are set
  from `tr()` in `retranslate()`, because this application installs only its own translator.
- No tooltips on transport controls: a Fluent `Tooltip` opens on keyboard focus, not just hover, so
  it covers what is above the button every time it is tabbed to. Put the word on the button.

### Audio & memory

- An export matches the file it came from: `AudioData` carries `bit_depth` with `sample_rate`,
  `resample_audio`/`stereo()` carry both forward, and `write_wav_atomic`/`analyze_audio` read them
  off the audio rather than taking a format argument. `WAV_BIT_DEPTHS` is `(16, 24)` — 8/16-bit PCM
  stays 16, everything wider goes to 24. There is no export floor: never resample upwards for a
  nicer-looking number.
- Stream in `BLOCK_FRAMES` blocks (never re-spell the literal), use `create_pcm_audio` +
  `cleanup()`/`release_pages()`, never accumulate a whole file in RAM, and poll cancellation inside
  decoder loops with a `QTimer`.
- `create_pcm_audio` maps a temp file where there is a disk and allocates on the heap under
  Emscripten, whose filesystem is heap too and whose `mmap` copies rather than aliases — a mapped
  buffer costs two of everything there. Scrub and convert inside the block loop, never in one pass
  over the mapping first.

### Front end (`web/`)

- The working page stays mounted and hides with `hidden`; unmounting stops a preview mid-play and
  discards a finished result or a running job. Window-scoped behaviour gates on the `active` prop.
- Window shortcuts (`Ctrl+O`/`Ctrl+Enter`/`Esc`/`F5`) live in `shared/runtime/shortcuts.ts` and are
  bound by `app/App.tsx`, never by a page, which registers through `onBind` — the rule `MainWindow`
  follows. Breakpoints mirror the desktop (620px = `PORTRAIT`).
- The boot banner shows four startup stages and the ~23 MB first-visit cost rather than a
  percentage: Pyodide's lock file has no sizes, so a byte-level bar would be invented. Uploads chunk
  at `CHUNK_BYTES` (4 MiB) carrying offset and final size, which is what makes progress real and
  stops Emscripten reallocating and copying on every append.
- The brand mark comes from `src/resources/purivox.svg` via `build-assets.mjs`; never redraw it.
  Biome's recommended rules with its own defaults (tab indent); suppress inline with a reason rather
  than turning a rule off globally.

### Packaging

A new top-level source directory must be listed in `[tool.hatch.build.targets.wheel] packages`
(`pyproject.toml`), or the wheel silently leaves it out; `tests/test_packaging.py` checks the list
against the tree. The standalone builds need no list: `deployment/purivox.spec` (PyInstaller)
collects every top-level package under `src/` itself, because the GUI imports its pages, the
download dialog and yt-dlp inside slots, where import analysis cannot follow. A module reached
only through `importlib` still has to be named in the spec's `hiddenimports`, as scipy's array-API
shim is. A missed one fails when the frozen program first reaches it, not when it is built, which
is why CI runs every build through `deployment/smoke.sh` (the GUI, then one CLI job).

On Linux the build leaves the desktop's own stack to the desktop — X11, xcb and Wayland,
fontconfig, GLib, DBus, GTK, PulseAudio — and ships the Python environment, Qt, and the OpenSSL
that Qt's TLS backend loads by name. The bootloader points `LD_LIBRARY_PATH` into the bundle;
`deployment/runtime_library_path.py` restores it for child processes, so the browser or file
manager the app opens does not load this Qt in place of its own. `QT_DEBUG_PLUGINS=1` makes even
a source run crash on exit, so it says nothing about a build.

## Commands

```bash
uv sync --locked

uv run --locked purivox                            # GUI
uv run --locked purivox mr <stage> <source>... <out.wav> --strength 75 --sigma 8 --align --lang zh_cn
uv run --locked purivox fetch <link>                # or: <keywords> [--limit N] [--pick N]
uv run --locked purivox fetch --list                # what has been downloaded
uv run --locked purivox --selftest                 # pipeline smoke, offscreen-safe

# DSP A/B across a change
uv run --locked python tools/eval_cancellation.py --save baseline.json
uv run --locked python tools/eval_cancellation.py --compare baseline.json

# pipeline A/B: both engines over the same scenes, so the geometry rule stays honest
uv run --locked python tools/eval_isolation.py --save isolation-baseline.json
uv run --locked python tools/eval_isolation.py --compare isolation-baseline.json

# what one job costs, phase by phase, with peak RSS
uv run --locked python tools/bench_pipeline.py --save bench-baseline.json
uv run --locked python tools/bench_pipeline.py --compare bench-baseline.json

# checks (Qt needs the offscreen platform)
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/shared/test_jobs.py     # one file
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow   # 15-min gate
uv build                                           # sdist + wheel

# browser build (predev/prebuild repack src/ and regenerate the translation JSON)
cd web && bun install && bun run dev       # http://localhost:5173/
cd web && bun run check                    # lint + tsc + layering; also `lint`, `format`, `build`
PURIVOX_BASE=/repo/ bun run build          # only for a Pages *project* site subpath

# translations: edit the .ts, recompile, commit both
uv run --locked pyside6-lrelease src/resources/i18n/<locale>.ts -qm src/resources/i18n/<locale>.qm

# standalone build (dist/Purivox.bin, dist/Purivox.exe; macOS builds dist/Purivox.app instead)
uv sync --locked --group deploy
uv run --locked --group deploy pyinstaller deployment/purivox.spec --noconfirm
deployment/smoke.sh dist/Purivox.bin               # run it through the GUI and one CLI job
```

Language keys: `zh_cn`, `zh_tw`, `en_us`, `ja_jp`, `ko_kr`.

## Testing

- Offscreen is mandatory (conftest sets it); `slow` tests are auto-skipped unless `--runslow`, which
  runs the 15-minute 44.1 kHz stereo benchmark (`tests/benchmarks/test_long_audio.py`: seam
  smoothness, peak RSS ≤ 2 GiB).
- `tests/` mirrors `src/` path-for-path, so a change's tests are at the mirrored path: the DSP
  under `tests/features/reference_removal/dsp/`, matching, timeline, render and the page beside
  them, the window's shortcuts, routing and window-shape layouts under `tests/app/`, the browser
  shell's JSON contract and Qt-free imports under `tests/web/`.
- conftest starts every test from the default language and default settings and deletes the
  test-mode `config.json`, so a test that calls `cfg.set` leaks nothing into the next one.
- A test asserts behaviour a user or a caller relies on. Pinning copy, restating a config file, or
  checking that a patched function was called is not a test; the raw-key check in
  `test_main_window.py` covers "every label is translated" for all five locales at once.
- Three repository-wide gates: `test_architecture.py` (import boundaries), `test_packaging.py`
  (the wheel's package list against the tree, compiled catalogues),
  `test_documentation.py` (README index, doc translation pairing, internal links).
- No test reaches a real host — the update tests repoint `updates.RELEASES_API` at a localhost
  server.
- DSP changes are accepted on measurement, not argument: run `purivox --selftest` and
  `tools/eval_cancellation.py --compare` before committing, `tools/eval_isolation.py --compare`
  when the change touches which engine runs, and `tools/bench_pipeline.py --compare` to show what
  the change bought. Synthetic metrics are regression evidence only and claim nothing
  about real music. `docs/reference-removal.md` documents the algorithm as it stands — no
  before/after, no trade-off tables.

**Before you call a change done:**

- `ruff check` and `ruff format --check` are clean, and `pytest` passes.
- The new behaviour has a test at the mirrored path, or a reason why it cannot.
- A DSP change carries an `eval_cancellation.py --compare` delta, a change to the engine choice an
  `eval_isolation.py --compare` delta, and a performance change a `bench_pipeline.py --compare`
  delta.
- A UI change was looked at in `PORTRAIT` and `ULTRAWIDE`, not only at the default window size.
- A new or reworded string exists in all five `.ts` files, and both `.qm` files were recompiled.
- A new top-level source directory is in the wheel's package list.

## Tooling

Python ≥3.11, pinned to 3.14 for development by `.python-version`; uv with `uv.lock` committed, the
`dev` group synced by default and `deploy` opt-in. PySide6 ≥6.8 + `PySide6-Fluent-Widgets`
(vendored `qfluentwidgets`) and never a second Fluent package — not the `[full]` extra, whose
pillow and colorthief only feed an AcrylicLabel this app never builds; Qt is mandatory even for the
CLI, which falls back to `QAudioDecoder` for decoding. numpy ≥2, scipy, soundfile, soxr, yt-dlp,
all range-pinned; yt-dlp needs updating whenever a site changes under it. ruff only
(`line-length = 100`, E/F/I/UP/B/SIM/RUF) plus `ruff format` — no black, no isort. PyInstaller
6.22.3 from `deployment/purivox.spec`: onefile (`dist/Purivox.bin` / `Purivox.exe`) and macOS app
bundles for arm64 and x86_64 (`dist/Purivox.app`).

## Commits & Releases

Rule 15 first: none of this happens until you are asked. When you are:

- Commits land on `main`. The history is linear and single-author, so do not open a branch first —
  not for a cleanup, not for a refactor, not for anything you were told to commit. A branch is for
  work that was asked for as a branch or a pull request.
- Subject: `type(scope): what changed`, imperative and lower case, no trailing period. Types in use
  are `feat`, `fix`, `perf`, `refactor`, `docs`, `ci`, `build`, `chore`; the scope is the area
  (`dsp`, `ui`, `web`, `audio`, `i18n`, `isolation`, `settings`, `shared`, `release`) and may be
  dropped for a change that spans the repository.
- Body: prose wrapped at 80 columns, in English, explaining why the change looks like this — the
  problem, the constraint that decided the design, what was rejected and why. Not a restatement of
  the diff, and not a bullet list.
- `CHANGELOG.md` gets one bilingual section per released version. The release workflow publishes the
  section whose heading matches the tag, and the in-app update dialog shows that same text.
- A release tag is `v<version>` and must match `src/app/version.py`; CI checks that first and fails
  the build in its opening minutes rather than after every build has run.
- The AUR package (`deployment/aur/`) is published after a release by running
  `deployment/aur/publish.sh`, never by CI — it re-points `purivox-bin` at the release `.deb`,
  builds it once as a check, and pushes `PKGBUILD` and `.SRCINFO`.
