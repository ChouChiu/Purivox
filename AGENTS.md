# Repository Guidelines

Purivox v1.0.1 (`purivox`): vocal isolation from stage and live recordings. Python 3.11+, PySide6 +
PySide6-Fluent-Widgets, AGPL-3.0-or-later. `CLAUDE.md` symlinks here.

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

Two pipelines. The GUI, the CLI and the browser build are shells over them:

- **Reference cancellation** — align the song against the known accompaniment (GCC-PHAT + clock
  drift tracking), estimate a complex transfer, subtract the prediction, soft-mask the residual.
  The cancellation result is the output; there is no spatial post-processing. Used by **MR Remove**
  (`purivox mr`, GUI) on one pair, and by **Full Stage** (GUI) on the clips a timeline matched
  inside a continuous stage recording — only the enabled ones are processed.
- **Neural separation** — UVR MDX-Net ONNX, no reference (`purivox ai`, GUI); models fetched on
  demand and SHA-256 verified.

GUI and CLI are thin shells over `run_reference_job` / `run_neural_job`; full-stage rendering is
orchestrated in `src/app/full_stage_processing.py`. The **browser build** (`web/`) runs both
reference workflows under Pyodide as a static site with no backend
(<https://purivox.wwchun.top/>, `docs/web.md`); `onnxruntime` has no wasm build, so AI is
desktop-only. `README.md` (Chinese) is authoritative for users, with `README_EN.md` and `docs/en/`
as translations, paired file-for-file.

## Layout

```text
src/entrypoints/   cli.py, gui.py — startup only
src/app/           MainWindow, JobPresenter, JobRunner/worker, full_stage_processing
src/features/      reference_removal, full_stage, neural_separation, home, settings
src/shared/        audio/, dsp/, ui/, config, i18n, jobs, logging, processing, progress, branding
src/web/           bridge.py (JSON in/out), timeline.py, limits.py — sibling of app
web/               Vite + React + Fluent UI v9, same feature layering, bun
```

Dependencies flow downward only: `shared` imports nothing of ours, features never import each
other, `app`/`web` never import `entrypoints`. `tests/test_architecture.py` and
`web/scripts/check-architecture.mjs` parse the imports and fail the build otherwise. A new feature
is one new directory under `src/features/`. Anything two features — or the GUI and the CLI — both
need moves down into `shared` (`BLOCK_FRAMES`, `AUDIO_EXTENSIONS`, `validate_reference_settings`,
`log_flux_bands`, `AUDIO_FILE_FILTER`, `normalized_wav_path`, `branding.user_agent`,
`OutputTracks`, `subtract_into`, `export_audio`).

| Path | What lives there |
|---|---|
| `src/app/` | `main_window.py` (FluentWindow shell: navigation, i18n/theme, auto-find, the window `QShortcut`s), `job_presenter.py` (page and result state), `job_runner.py`/`worker.py` (QThread lifecycle and adapter), `version.py` |
| `src/features/reference_removal/` | `dsp/algorithms.py` (complex subtraction + residual mask, linked peak protection), `dsp/transfer.py` (smoothed spectra, vectorised LDL^H solve, adjusted multiple coherence), `dsp/alignment.py` (GCC-PHAT + drift tracking + Lanczos warp), `finder.py` (automatic accompaniment match), `processing.py`, `page.py`, `models.py` |
| `src/features/full_stage/` | Multi-source fingerprint matching, timeline models, `timeline_model.py` (`QAbstractTableModel` behind the editable timeline, `clip_edited`/`edit_rejected`) |
| `src/features/neural_separation/` | `inference.py` (MdxNet ONNX, chunked overlap-add), `model_store.py` (search + `QNetworkAccessManager` download + `QSaveFile` verify-then-commit), `catalog.py` (`MODEL_BASE_URL`, 4 entries) |
| `src/features/home/`, `settings/` | Brand and entry cards; language/theme/log level, `updates.py` (GitHub release query + version compare) and `dialog.py`. The app never installs an update — the dialog opens the release page |
| `src/shared/` (root) | `config.py` (the `cfg` `QConfig`), `i18n.py` (`tr()`, `install_language()`, `SUPPORTED_LANGUAGES`), `jobs.py` (the reference-settings contract behind `ReferenceJob`, `FullStageJob` and the CLI: `SIGMA_CHOICES`, `STRENGTH_RANGE`, `validate_reference_settings`, `OutputTracks`, `planned_outputs`), `logging.py`, `processing.py` (`CancellationToken`, `ProgressEvent`, `ProcessingResult`), `progress.py`, `branding.py` |
| `src/shared/audio/` | `io.py`: mapped I/O, soxr resample, atomic WAV write, `BLOCK_FRAMES` (262 144), `AUDIO_EXTENSIONS`, `release_mapped_pages()`; `analysis.py`: `AudioStats`, peak/RMS, block-wise `copy_audio`/`subtract_into`, `export_audio` |
| `src/shared/dsp/` | `spectral.py`: librosa-compatible `stft`/`istft` (`n_fft=2048`, `hop=512`) and `log_flux_bands()`, shared by full-stage matching and coarse alignment |
| `src/shared/ui/` | `responsive.py` (`LayoutMode`/`LayoutMetrics`, `ResponsiveColumns`, `FoldingRow`, `allow_shrinking`, `HeightForWidth`, `ElidedLabel`), `cards.py` (`FormCard`, `PageScrollArea`), `widgets.py` (`SmoothComboBox`, file filters, `normalized_wav_path`) |
| `src/resources/` | `i18n/{zh_cn,en_us,ja_jp,ko_kr}.{ts,qm}`, `model_data.json` (65 MDX-Net specs keyed by model MD5), `purivox.svg`, `resource_path` |
| `web/scripts/` | `build-python-archive.mjs` (packs `src/` for Pyodide), `build-i18n.mjs`, `build-assets.mjs`, `check-architecture.mjs`. Never a second implementation of the DSP |
| `tests/`, `docs/` | Tests mirror `src/` path-for-path, `benchmarks/` behind `--runslow`; Chinese docs with one translation per file in `docs/en/` |
| `deployment/`, `tools/`, `models/` | Nuitka entry shim + `.deb`/`.rpm` packaging; `eval_cancellation.py` (DSP A/B); ONNX weights, gitignored and never packaged |

## Pipelines

**Reference** (`features/reference_removal/processing.py`): `read_audio` (SoundFile, Qt Multimedia
fallback) → upmix to stereo → resample the song to the stage rate (soxr) → optional `align_audio` →
`process_audio` (blocks from the spectral-cell budget, ~45 s at 44.1 kHz, ≥2 s overlap, cos²/sin²
crossfade) → peak/RMS stats → atomic WAV at the song's own rate and bit depth. `process_audio` has
a pooled and an inline schedule because Pyodide has no pthreads; `test_dsp_execution.py` holds them
to the same output.

**Neural** (`features/neural_separation/processing.py`): resample to 44.1 kHz → `ensure_model`
(`--models-dir` → `PURIVOX_MODELS` → system app-data dir → repo `models/`; TRvlvr download, SHA-256
verified) → `MdxNet.separate` (chunked overlap-add with a hanning divider) → background =
mix − vocal → resample both stems back → `<stem>_vocal.wav` + `<stem>_background.wav` at the song's
bit depth.

**Job lifecycle**: a page emits `start_requested`/`cancel_requested`; `MainWindow` builds the job
dataclass and hands it to `JobPresenter`, which owns page and result state and delegates to
`JobRunner`, which owns the `QThread` and `ProcessingWorker` and emits
`progress`/`succeeded`/`failed`/`cancelled`/`finished`. Cancellation is cooperative —
`CancellationToken.raise_if_cancelled()`, never swallowed. The CLI runs the same jobs synchronously
and cancels the token on SIGINT.

## Commands

```bash
uv sync --locked

uv run --locked purivox                            # GUI
uv run --locked purivox mr <song> <acc> <out.wav> --strength 75 --sigma 8 --align --lang zh_cn
uv run --locked purivox ai <song> [--output-dir <dir>] [--model mdxnet_1] [--models-dir <dir>]
uv run --locked purivox --selftest                 # pipeline smoke, offscreen-safe

# DSP A/B across a change
uv run --locked python tools/eval_cancellation.py --save baseline.json
uv run --locked python tools/eval_cancellation.py --compare baseline.json

# checks (Qt needs the offscreen platform)
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow   # 15-min gate
uv build                                           # sdist + wheel

# browser build (predev/prebuild repack src/ and regenerate the translation JSON)
cd web && bun install && bun run dev       # http://localhost:5173/
cd web && bun run check                    # lint + tsc + layering; also `lint`, `format`, `build`
PURIVOX_BASE=/repo/ bun run build          # only for a Pages *project* site subpath

# translations: edit the .ts, recompile, commit both
uv run --locked pyside6-lrelease src/resources/i18n/<locale>.ts -qm src/resources/i18n/<locale>.qm

# onefile executable (dist/Purivox.bin; macOS builds dist/Purivox.app instead)
uv sync --locked --group deploy
uv run --locked --group deploy pyside6-deploy -c pysidedeploy.spec
```

Language keys: `zh_cn`, `en_us`, `ja_jp`, `ko_kr`.

## Commits & Releases

Rule 15 first: none of this happens until you are asked. When you are:

- Commits land on `main`. The history is linear and single-author, so do not open a branch first —
  not for a cleanup, not for a refactor, not for anything you were told to commit. A branch is for
  work that was asked for as a branch or a pull request.
- Subject: `type(scope): what changed`, imperative and lower case, no trailing period. Types in use
  are `feat`, `fix`, `perf`, `refactor`, `docs`, `ci`, `build`, `chore`; the scope is the area
  (`dsp`, `ui`, `web`, `audio`, `i18n`, `full-stage`, `settings`, `shared`, `release`) and may be
  dropped for a change that spans the repository.
- Body: prose wrapped at 80 columns, in English, explaining why the change looks like this — the
  problem, the constraint that decided the design, what was rejected and why. Not a restatement of
  the diff, and not a bullet list.
- `CHANGELOG.md` gets one bilingual section per released version. The release workflow publishes the
  section whose heading matches the tag, and the in-app update dialog shows that same text.
- A release tag is `v<version>` and must match `src/app/version.py`; CI checks that first and fails
  the build in its opening minutes rather than after an hour of compiling.
- The AUR package (`deployment/aur/`) is published after a release by running
  `deployment/aur/publish.sh`, never by CI — it re-points `purivox-bin` at the release `.deb`,
  builds it once as a check, and pushes `PKGBUILD` and `.SRCINFO`.

## Conventions & Invariants

Most of what follows is here because it cost someone time.

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
- An unknown key returns itself — never rely on that. A new or removed key means all four `.ts`
  files plus a `pyside6-lrelease` recompile, committed together; parity, freshness and literal-key
  use are all tested.
- Search the catalogues before inventing a string: the desktop already named most states
  (`warn_no_song`, `stage_need_sources`, `preview_empty`, the whole `home_*` set), and reuse keeps
  four locales correct for free.
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
  `current_page()`, never on a page — three page-local `Ctrl+O` bindings would be ambiguous, and a
  window shortcut works before a page takes focus. `_apply_shortcut_hints()`
  appends each binding to its button's tooltip, so no shortcut needs a translation key.
- Four `LayoutMode`s by page width: `PORTRAIT` < 620 stacks label over control, `HALF` < 960 and
  `LANDSCAPE` < 1440 stay one column, `ULTRAWIDE` ≥ 1440 splits into two lanes at
  `CONTENT_MAX_WIDTH`; height only sets `LayoutMetrics.short`. `PageScrollArea` measures the
  viewport and pushes metrics down to every `Responsive` child — a widget must never fold on its own
  width, because a page already squeezed is a page cut off and the scroll areas keep
  `ScrollBarAlwaysOff`. Cards join through
  `add_card(card, lane)`, never `layout.addWidget`.
- A label that can hold a path needs `allow_shrinking()` or its longest word becomes the page
  minimum; paths belong in `ElidedLabel` (one line, full text in `text()` and the tooltip); wrapping
  text needs `HeightForWidth` on every container up to the page, because Qt asks the widget, never
  the layout inside it, whether height follows from width.
- Files arrive through `QFileDialog` only, funnelled into one method per page (`set_song`,
  `set_stage`, `add_source_paths`) that also does the follow-up — a default output name, an
  invalidated analysis. The AI page watches the model directories with `QFileSystemWatcher`.
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

- `MrPage` and `FullStagePage` stay mounted and hide with `hidden`; unmounting stops a preview
  mid-play and discards a finished result or a running job. Since every page is mounted at once,
  window-scoped behaviour gates on the `active` prop.
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

A new source directory must be registered in three places or it silently ships nowhere:
`[tool.hatch.build.targets.wheel] packages` and `[tool.pyside6-project] files` (both
`pyproject.toml` — the latter is also where `pyside6-deploy` finds the Nuitka entry,
`deployment/main.py`), and `include-package` in `pysidedeploy.spec`. `tests/test_packaging.py`
checks the roster against the tree.

## Tooling

Python ≥3.11, pinned to 3.14 for development by `.python-version`; uv with `uv.lock` committed, the
`dev` group synced by default and `deploy` opt-in. PySide6 ≥6.8 + `PySide6-Fluent-Widgets[full]`
(vendored `qfluentwidgets`) and never a second Fluent package; Qt is mandatory even for the CLI,
which falls back to `QAudioDecoder` for decoding. numpy ≥2, scipy, soundfile, soxr, onnxruntime
(CPU), all range-pinned. ruff only (`line-length = 100`, E/F/I/UP/B/SIM/RUF), `ruff format`, no
black or isort. Nuitka 4.1.3 via `pyside6-deploy`, onefile (`dist/Purivox.bin` / `Purivox.exe`) and
a macOS arm64 app bundle (`dist/Purivox.app`, from a CI-derived spec); ONNX weights are downloaded
at runtime, never packaged.

## Testing

- `QT_QPA_PLATFORM=offscreen uv run --locked pytest` — offscreen is mandatory; conftest sets it and
  auto-skips `slow` tests unless `--runslow`, which runs the 15-minute 44.1 kHz stereo benchmark
  (`tests/benchmarks/test_long_audio.py`: seam smoothness, peak RSS ≤ 2 GiB).
- `tests/` mirrors `src/` path-for-path, so a change's tests are at the mirrored path: DSP and
  alignment regressions under `tests/features/reference_removal/`, timeline and matching under
  `full_stage/`, model download/verify/cancel under `neural_separation/`, runner and presenter
  lifecycles and the pytest-qt GUI/layout tests under `tests/app/`, the browser shell's JSON
  contract and Qt-free imports under `tests/web/`.
- Three repository-wide gates: `test_architecture.py` (import boundaries), `test_packaging.py`
  (shipped-source roster, compiled catalogues), `test_documentation.py` (README index, doc
  translation pairing, internal links).
- No test reaches a real host — the model-store and update tests repoint `catalog.MODEL_BASE_URL`
  and `updates.RELEASES_API` at a localhost server.
- DSP changes are accepted on measurement, not argument: run `purivox --selftest` and
  `tools/eval_cancellation.py --compare` before committing. Synthetic metrics are regression
  evidence only and claim nothing about real music. `docs/reference-removal.md` documents the
  algorithm as it stands — no before/after, no trade-off tables.
