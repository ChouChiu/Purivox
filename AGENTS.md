# Repository Guidelines

## Project Overview

**Purivox v1.0.0** (`purivox`) is a desktop tool for vocal isolation from stage and live
recordings, built in Python 3.11+ with PySide6 and PySide6-Fluent-Widgets (Fluent Design UI). One
codebase serves three workflows:

- **MR Remove** (`purivox mr`): reference-guided cancellation. Given the known accompaniment as a
  reference, it aligns the two recordings (GCC-PHAT plus clock-drift tracking), estimates a complex
  transfer, subtracts the prediction, and applies a residual soft mask to whatever is left.
  There is no optional spatial post-processing: the output is the cancellation result.
- **Full Stage** (GUI): matches multiple song sources against a continuous stage recording, exposes
  an editable timeline, and applies reference cancellation only to the matched clips that are
  enabled.
- **AI vocal extraction** (`purivox ai`): UVR MDX-Net ONNX inference with no reference. Models are
  downloaded on demand and verified by SHA-256.

The GUI and CLI are thin shells over the same `run_reference_job` / `run_neural_job` pipeline
functions; full-stage cross-feature rendering is orchestrated in
`src/app/full_stage_processing.py`. License: AGPL-3.0-or-later. README.md (Chinese) is the
authoritative user-facing document.

## Architecture & Data Flow

Dependencies flow strictly one way, and `tests/test_architecture.py` checks the boundaries by
parsing the import statements (AST):

```text
src/entrypoints (cli.py, gui.py)          — startup only
   └─> src/app (main_window.py, worker.py) — cross-feature orchestration
          └─> src/features/<feature>/      — self-contained: page.py, processing.py,
          │                                  models.py, dsp/, finder.py, catalog.py
          └─> src/shared/                  — depends on NOTHING (audio/, dsp/, ui/, i18n,
                                              jobs, config, logging, processing)
```

Rules enforced by `tests/test_architecture.py`: `shared` must never import `app` or
`features.*`, and feature packages must never import one another. Adding a feature means creating
one new `src/features/<feature>/` directory; it may import `shared` freely and must not be
imported by other features.

**Reference pipeline** (`features/reference_removal/processing.py`): `read_audio` (SoundFile,
with a Qt Multimedia fallback) → upmix to stereo → resample the song source to the stage rate
(soxr) → optional `align_audio` (GCC-PHAT coarse lag + Lanczos warp) → `process_audio` (blocks
sized by the spectral-cell budget, ~45 s at 44.1 kHz, at least 2 s overlap, cos²/sin² crossfade) →
resample to the 96 kHz Hi-Res export floor when needed → audio stats (peak/RMS dBFS) → atomic
24-bit WAV write.

**Neural pipeline** (`features/neural_separation/processing.py`): resample input to 44.1 kHz →
`ensure_model` (search: `--models-dir` override → `PURIVOX_MODELS` env → system app-data dir →
repo `models/`; download from TRvlvr releases with SHA-256 verification) → `MdxNet.separate`
(chunked overlap-add with a hanning divider accumulator) → background = mix − vocal → resample both
stems to 96 kHz → write 24-bit `<stem>_vocal.wav` + `<stem>_background.wav`.

**Concurrency**: pages declare Qt `Signal()`s (`start_requested`, `cancel_requested`);
`MainWindow` builds a job dataclass and hands it to `JobPresenter`, which owns page state and
result UI and delegates execution to `JobRunner`. The runner owns the `QThread` and
`ProcessingWorker` lifecycles and emits
`progress`/`succeeded`/`failed`/`cancelled`/`finished`. Cancellation is cooperative via
`CancellationToken.raise_if_cancelled()` (`src/shared/processing.py`). The CLI runs the same
jobs synchronously; SIGINT triggers token cancellation.

## Key Directories

| Path | Purpose |
|---|---|
| `src/entrypoints/` | `cli.py` (argparse: `mr`, `ai`, `--selftest`) and `gui.py` |
| `src/app/` | `main_window.py` (FluentWindow shell), `job_presenter.py` (page state/results), `job_runner.py`/`worker.py` (QThread lifecycle and adapter), cross-feature orchestration, `version.py` |
| `src/features/reference_removal/` | MR pipeline: `dsp/algorithms.py` (coherent cancellation), `dsp/transfer.py` (transfer estimation), `dsp/alignment.py`, `finder.py` (automatic accompaniment match), `processing.py`, `page.py`, `models.py` |
| `src/features/full_stage/` | Multi-source fingerprint matching, timeline models, `timeline_model.py` (`QAbstractTableModel` behind the editable timeline), and the full-stage page |
| `src/features/neural_separation/` | AI pipeline: `inference.py` (MdxNet ONNX wrapper), `model_store.py` (search + `QNetworkAccessManager` download + `QSaveFile` verify-then-commit), `catalog.py` (4 shipped model entries, `MODEL_BASE_URL`), `processing.py`, `page.py` |
| `src/features/home/`, `src/features/settings/` | HomePage (brand + entry cards), SettingsPage (language/theme/log level) |
| `src/shared/audio/` | `io.py`: mapped audio I/O/resampling/atomic writes, `BLOCK_FRAMES` (262 144) and `AUDIO_EXTENSIONS`, `release_mapped_pages()`; `analysis.py`: shared `AudioStats`, block copy, peak/RMS analysis |
| `src/shared/dsp/` | `spectral.py`: librosa-compatible `stft`/`istft` (`n_fft=2048`, `hop=512`) and `log_flux_bands()`, the onset feature shared by full-stage matching and coarse alignment |
| `src/shared/ui/` | `responsive.py` (`LayoutMode`/`LayoutMetrics` breakpoints, `ResponsiveColumns`, `FoldingRow`, `allow_shrinking`), `cards.py` (`FormCard` folding rows, `PageScrollArea` breakpoint dispatch), `combo_box.py` (`SmoothComboBox`, qfw slide animation disabled), `dialogs.py` (file-dialog filters), `drop.py` (`AudioDropLineEdit`/`AudioDropListWidget`, audio-only drag and drop) |
| `src/shared/` | `config.py` (QConfig), `i18n.py` (`tr()`, `install_language()`, `SUPPORTED_LANGUAGES`), `jobs.py` (`SIGMA_CHOICES`/`STRENGTH_RANGE`/`validate_reference_settings`), `logging.py` (single-line formatter, `LOG_LEVELS`), `processing.py` (token/progress types) |
| `src/resources/` | `i18n/{zh_cn,en_us,ja_jp,ko_kr}.ts` + compiled `.qm` (Qt Linguist, key-indexed, must stay key-identical), `model_data.json` (MDX-Net spec table keyed by MD5), `__init__.py` (`resource_path` via `importlib.resources`) |
| `tests/` | Mirrors `src/` path-for-path (`tests/shared/` ↔ `src/shared/`, `tests/features/…`); `benchmarks/` for long/`--runslow` gates |
| `models/` | 4 prebuilt ONNX weights (gitignored, never committed); not shipped in wheels or standalone builds |
| `deployment/` | `main.py` — standalone Nuitka entry shim |
| `tools/` | Developer scripts kept out of the package: `eval_cancellation.py` reports cancellation depth and live-source fidelity per synthetic scene, for A/B comparison across a DSP change |

## Development Commands

```bash
uv sync --locked

# run
uv run --locked purivox                            # GUI
uv run --locked purivox mr <song> <acc> <out.wav> --strength 75 --sigma 8 --align --lang zh_cn
uv run --locked purivox ai <song> [--output-dir <dir>] [--model mdxnet_1] [--models-dir <dir>]
uv run --locked purivox --selftest                 # self-test smoke (offscreen-safe)

# DSP A/B: capture a baseline before a change, compare after
uv run --locked python tools/eval_cancellation.py --save baseline.json
uv run --locked python tools/eval_cancellation.py --compare baseline.json

# checks (no lint/test without offscreen Qt platform)
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow   # 15-min memory/quality gate
uv build                           # sdist+wheel

# translations (edit src/resources/i18n/*.ts, then recompile and commit both)
uv run --locked pyside6-lrelease src/resources/i18n/<locale>.ts -qm src/resources/i18n/<locale>.qm

# Onefile executable (Nuitka via pyside6-deploy; output dist/Purivox.bin)
uv sync --locked --group deploy
uv run --locked --group deploy pyside6-deploy -c pysidedeploy.spec
```

Language keys: `zh_cn`, `en_us`, `ja_jp`, `ko_kr`.

## Code Conventions & Common Patterns

- **Typing**: type hints everywhere (`from __future__ import annotations`, PEP 604 `X | None`,
  `collections.abc`); frozen+slots dataclasses for jobs/config. snake_case functions/vars; Qt
  widget attributes camelCase.
- **Errors**: raise `ValueError`/`KeyError`/`FileNotFoundError`/`RuntimeError`. Long jobs
  catch `(FileNotFoundError, KeyError, ValueError)` → CLI exit 2; anything else → exit 1. The GUI
  surfaces errors through the worker `failed` signal + InfoBar. Cancellation via
  `CancellationToken.raise_if_cancelled()` — never swallow cancellation; documented fallbacks
  (e.g. alignment failure → `logger.warning` + fallback) are the only tolerated swallows.
- **Logging**: `logging.getLogger(__name__)`; single-line format
  `YYYY-MM-DD HH:MM:SS.xx [LEVEL] module: message` (`ApplicationLogFormatter`,
  `src/shared/logging.py`); CLI progress prints `progress: %3d%%`. Qt/FFmpeg messages route to
  `qt.*` loggers.
- **i18n**: `tr(key, **values)` (`src/shared/i18n.py`) resolves through
  `QCoreApplication.translate()` against the `QTranslator` that `install_language()`
  installed — language is application state, NOT a job/page parameter. An unknown key returns the
  key itself — never rely on that; adding or removing a key MUST be mirrored in all four locale
  `.ts` files AND recompiled to `.qm` (`pyside6-lrelease`, tests enforce parity and
  freshness). Switching UI language reinstalls the translator, calls each page's `retranslate()`
  and rebuilds combo boxes. Never load a `.qm` from bytes without pinning them:
  `QTranslator.load()` borrows the buffer and silently returns another language's strings once it
  is freed.
- **PySide ownership**: Qt objects that only *borrow* what they are handed will read freed memory —
  a `.qm` buffer passed to `QTranslator.load()` returns another language's strings, and a
  `QMimeData` passed to a `QDragEnterEvent`/`QDropEvent` constructor segfaults the
  interpreter. Keep such an object in a named local or an attribute for as long as its reader
  lives.
- **Config**: qfluentwidgets `QConfig` (`src/shared/config.py`, `cfg` singleton,
  `config.json` in AppConfigLocation).
- **Qt**: pages declare `Signal()`s and never touch the worker directly; `MainWindow` connects
  them. Prefer `SmoothComboBox` (qfw slide animation is disabled there) and
  FormCard/PageScrollArea from `shared/ui/`. Preview = `QMediaPlayer` + `QAudioOutput`.
- **Prefer the Qt facility over a hand-rolled one** where Qt owns the problem: model/view
  (`QAbstractTableModel` + qfw `TableView`) for any editable table rather than `QTableWidget`
  items; `QNetworkAccessManager` (system proxy, redirects, `setTransferTimeout`,
  `downloadProgress`, `abort()`) for HTTP; `QSaveFile` for verify-then-commit writes;
  `QStandardPaths` for locations; `QCoreApplication.applicationName()/applicationVersion()`
  for identity. Python's stdlib stays where it is already equal or better (`hashlib`,
  `tempfile` + `numpy.memmap`, `argparse` subcommands, `concurrent.futures` for the DSP pool).
- **Slots**: decorate slots that receive signals across a thread boundary with `@Slot(<types>)`
  (worker → `JobRunner` → `JobPresenter`); Qt then dispatches the queued connection with the
  declared signature instead of a generic Python wrapper.
- **Shortcuts** live on `MainWindow`, never on pages: three page-local `Ctrl+O` bindings would
  be an ambiguous overload, and a window shortcut works before a page takes focus.
  `_apply_shortcut_hints()` appends each binding to the tooltip of the button it drives via
  `QKeySequence.toString(NativeText)`, so a shortcut needs no translation key.
- **Responsive layout**: window shape is one of four `LayoutMode`s decided by page width
  (`shared/ui/responsive.py`): `PORTRAIT` < 620 stacks a form label above its control, `HALF`
  < 960 and `LANDSCAPE` < 1440 keep one column, `ULTRAWIDE` >= 1440 splits the cards into two
  lanes and centres the column at `CONTENT_MAX_WIDTH`. Height only sets `LayoutMetrics.short`.
  `PageScrollArea` measures its viewport and pushes the metrics down to every `Responsive`
  child — a widget must never fold on its own width, because a page that has already been squeezed
  is a page that got cut off (the scroll areas keep `ScrollBarAlwaysOff`). A card joins the page
  through `add_card(card, lane)`, never `self.layout.addWidget`, and one column keeps the order
  the cards were added in. Any label that can hold a path needs `allow_shrinking()`, or its
  longest unwrappable word becomes the page's minimum width.
- **File input**: every audio entry point accepts drag and drop through `shared/ui/drop.py`; a
  dropped path must go through the same method as the file dialog (`set_song`, `set_stage`,
  `add_source_paths`) so both routes behave identically. The AI page keeps a
  `QFileSystemWatcher` on the model directories to refresh its ready/needs-download label.
- **Memory discipline** (long audio): stream in `shared.audio.BLOCK_FRAMES` (262 144) blocks —
  never re-spell the literal — use `create_pcm_audio` memmap + `cleanup()`/`release_pages()`;
  never accumulate whole files in RAM; add a `QTimer` poll for cancellation inside decoder loops.
- **De-duplication**: a constant, range or algorithm needed by two features — or by both the GUI
  and the CLI — goes down into `shared` (feature packages cannot import each other). Existing
  examples: `shared.audio.BLOCK_FRAMES`, `shared.audio.AUDIO_EXTENSIONS`,
  `shared.jobs.validate_reference_settings`, `shared.dsp.log_flux_bands`,
  `shared.ui.AUDIO_FILE_FILTER`.
- **Adding a source dir**: register in THREE places or it silently ships nowhere:
  `[tool.hatch.build.targets.wheel] packages` + `[tool.pyside6-project] files` (both
  `pyproject.toml`) + `include-package` in `pysidedeploy.spec`.

## Important Files

| File | Role |
|---|---|
| `pyproject.toml` | hatchling packaging; ruff + pytest config; `[tool.pyside6-project] files` = authoritative shipped-source roster — every `src/**/*.py`, every `i18n/*.ts`, and `deployment/main.py`, which `pyside6-deploy` resolves as the Nuitka entry from this list |
| `pysidedeploy.spec` | Nuitka build (onefile mode, `deployment/main.py` → `dist/Purivox.bin`) |
| `src/entrypoints/cli.py` | `purivox` entry point (`main`); mr/ai subcommands, `--selftest` |
| `src/app/main_window.py` | FluentWindow shell: navigation, i18n/theme, worker orchestration, auto-find, and the window-level `QShortcut`s (`Ctrl+O`/`Ctrl+Return`/`F5`/`Esc`/`Ctrl+P`) dispatched to `current_page()` |
| `src/app/job_runner.py` / `worker.py` | Single-job QThread lifecycle and QObject operation adapter |
| `src/shared/processing.py` | `CancellationToken`, `ProcessingCancelled`, `ProgressEvent`, `ProcessingResult`, `ProgressCallback` |
| `src/shared/jobs.py` | Reference-job settings contract shared by `ReferenceJob`, `FullStageJob` and the CLI parser |
| `src/shared/audio/io.py` | memmap audio loading, soxr resample, ≥96 kHz / 24-bit Hi-Res preparation, atomic WAV write |
| `src/shared/config.py` / `i18n.py` / `logging.py` | settings persistence, `QTranslator` install + `tr()`, single-line log format |
| `src/features/reference_removal/dsp/algorithms.py` | Coherent cancellation (complex subtraction + residual mask) and linked peak protection |
| `src/features/reference_removal/dsp/transfer.py` | Smoothed spectral statistics, the vectorised LDL^{H} solve, and the complex transfer with its adjusted multiple coherence |
| `src/features/reference_removal/dsp/alignment.py` | GCC-PHAT coarse alignment + local drift tracking + Lanczos warp |
| `src/features/neural_separation/inference.py` / `model_store.py` | MdxNet ONNX wrapper (chunked overlap-add); model search, Qt-network download, incremental SHA-256 verified before `QSaveFile.commit()` |
| `src/features/full_stage/timeline_model.py` | `TimelineModel`: the analysis as an editable `QAbstractTableModel` (`data`/`flags`/`setData`), with `clip_edited` / `edit_rejected` for page status text |
| `src/resources/model_data.json` | 65-entry MDX-Net spec table keyed by model-MD5 (`compensate`, `mdx_dim_f_set`, `mdx_dim_t_set`, `mdx_n_fft_scale_set`, `primary_stem`) |
| `src/resources/i18n/*.ts` / `*.qm` | UI strings: Qt Linguist XML sources keyed by snake_case identifiers in one `Purivox` context, plus the `pyside6-lrelease` output the app loads (149 keys; parity, freshness and literal-key use all tested). Edit the `.ts`, recompile, commit both |
| `tests/test_architecture.py` | AST import-boundary gate (shared isolation, feature isolation) |
| `tests/conftest.py` | forces `QT_QPA_PLATFORM=offscreen`, adds `--runslow`, auto-skips `slow` tests |

## Runtime/Tooling Preferences

- **Python ≥ 3.11**, pinned to 3.14 for development via `.python-version`. Package/environment
  manager: uv; commit `uv.lock`. The `dev` dependency group is synced by default and `deploy`
  is opt-in.
- **UI stack**: PySide6 ≥6.8 + `PySide6-Fluent-Widgets[full]` (vendored `qfluentwidgets`; never
  mix with other Fluent widget packages). Qt is mandatory for audio fallback decode
  (`QAudioDecoder`) — CLI tests still need `QT_QPA_PLATFORM=offscreen`.
- **DSP deps**: numpy ≥2, scipy, soundfile, soxr; neural: onnxruntime (CPU). All pinned to bounded
  ranges in `pyproject.toml`.
- **Lint/format**: ruff only (`line-length = 100`, rules E/F/I/UP/B/SIM/RUF, E501 ignored).
  Format = `ruff format`; there is no separate black/isort.
- **Deploy**: Nuitka 4.1.3 via `pyside6-deploy`; onefile mode (Linux `dist/Purivox.bin`, Windows
  `dist/Purivox.exe`). ONNX weights are never packaged (downloaded at runtime;
  `models/*.onnx` gitignored).

## Testing & QA

- **Framework**: pytest ≥8.3 + pytest-qt ≥4.4. Run:
  `QT_QPA_PLATFORM=offscreen uv run --locked pytest` (offscreen mandatory; conftest sets it and
  adds `--runslow`, auto-skipping `@pytest.mark.slow` tests otherwise). Marker `model` is
  declared but currently unused; `--runslow` runs the 15-minute, 44.1 kHz stereo
  reference-cancellation benchmark (`tests/benchmarks/test_long_audio.py`) asserting seam
  smoothness and peak RSS ≤ 2 GiB.
- **Layout**: `tests/` mirrors `src/` path-for-path. Per-area coverage: audio
  IO/resample/atomic-write (`tests/shared/test_audio.py`), STFT round-trip (`test_spectral.py`),
  i18n key parity (`test_i18n.py`), log format (`test_logging.py`), coherent cancellation +
  alignment/MIMO (`tests/features/reference_removal/test_dsp.py`), drift/jitter regressions
  (`test_dsp_regression.py`), finder similarity (`test_finder.py`), end-to-end reference job +
  AudioStats + same-input rejection (`test_processing.py`), neural chunked overlap-add identity
  (`test_neural.py`), CLI option handling (`tests/entrypoints/test_cli.py`), GUI
  navigation/theme/combos/stats and the portrait/half/landscape/ultrawide layouts via pytest-qt
  (`tests/app/test_gui.py`), breakpoints and the responsive containers (`tests/shared/test_responsive.py`), timeline model
  data/flags/edit rejection (`tests/features/full_stage/test_timeline_model.py`), and model
  download/verify/cancel against a localhost HTTP server
  (`tests/features/neural_separation/test_model_store.py` — it repoints
  `catalog.MODEL_BASE_URL`, so no test ever reaches the real release host).
- **Architecture gate**: `tests/test_architecture.py` parses ASTs — any `shared → app/features`
  or feature↔feature import fails the suite.
- **Expectations**: synthetic DSP metrics are regression evidence only — they do not claim
  real-music quality (stated in README). Run `uv run --locked purivox --selftest` for a quick
  pipeline smoke check before committing DSP changes. DSP changes are accepted or rejected on
  measurement here, so run `tools/eval_cancellation.py` as well to see what a change did to depth
  and fidelity; `docs/reference-removal.md` records the numbers for the ones that landed and the
  ones that did not.
