# Contributing to Purivox

<p align="left">
  <a href="../CONTRIBUTING.md">简体中文</a> · <strong>English</strong>
</p>

This document is for people changing this repository: how to get it running, where code belongs,
how to verify a change, and what a commit should look like. For the algorithms and the architecture
themselves, see [Architecture and Data Flow](architecture.md) and the per-feature documents.

## Setting Up

The project uses uv to manage Python, the isolated environment, and the lock file. With uv
installed, install the locked runtime and default development dependencies from the repository
root; `.python-version` decides the interpreter and uv fetches it:

```bash
uv sync --locked
```

Confirm the environment works:

```bash
uv run --locked purivox                                        # GUI
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest   # pipeline smoke test, headless
```

Change dependencies with `uv add <package>`, `uv add --dev <package>`, or
`uv add --group deploy <package>`, and commit the updated `pyproject.toml` and `uv.lock` together.

Do not install another PyQt or PySide Fluent package that exports `qfluentwidgets` into this
environment. The project pins `PySide6-Fluent-Widgets[full]`, and a second one makes it
unpredictable which copy an import resolves to.

## Where Code Belongs

Dependencies flow downward only: `shared` imports nothing of ours, feature packages never import
each other, and neither `app` nor `web` imports `entrypoints`. `tests/test_architecture.py` parses
the imports and enforces this, so crossing a boundary fails the build.

- A new feature is one new directory under `src/features/`, carrying its own page, models, and
  processing logic.
- Anything two features need, or that both the GUI and the CLI need, moves down into `shared` and
  is defined once — for example `shared.audio.BLOCK_FRAMES`, `shared.audio.AUDIO_EXTENSIONS`,
  `shared.jobs.SIGMA_CHOICES`, `shared.i18n.SUPPORTED_LANGUAGES`, and `shared.logging.LOG_LEVELS`.
- Orchestration that joins several features lives in `app`; do not make feature packages import
  each other for the sake of reuse.
- Shared data models belong to their consumers: a model used by several features goes to `shared`,
  one used inside a single feature stays there, and none of them may be re-exported from another
  feature for convenience.

The full layering and each layer's responsibilities are in
[Architecture and Data Flow](architecture.md).

## Code Conventions

### Python

- New modules use `from __future__ import annotations` and complete type annotations.
- Job models with few mutable parameters prefer `frozen=True, slots=True` dataclasses; fixed string
  sets use `StrEnum`.
- Log through `logging.getLogger(__name__)`; only an explicitly recorded fallback path may swallow
  a local failure.
- Ruff's line width is 100 with the E, F, I, UP, B, SIM, and RUF rules; E501 is left to the
  formatter and to review.

### Qt

- Background jobs are coordinated by `app/job_presenter.py` for page state and handed to
  `app/job_runner.py` for the thread; pages and processing pipelines must not create threads.
- A slot receiving a cross-thread signal is annotated `@Slot(<types>)`
  (worker → `JobRunner` → `JobPresenter`) so Qt dispatches the queued connection with the declared
  signature.
- Where Qt already owns the problem, use Qt's answer: `QAbstractTableModel` + `TableView` for an
  editable table rather than filling `QTableWidget` item by item; `QNetworkAccessManager` for HTTP
  (system proxy, redirects, timeouts, progress, `abort()`); `QSaveFile` when a file must be
  verified before it is committed; `QStandardPaths` for locations. Where the standard library is
  already equal or better, leave it (`hashlib`, `tempfile` + `numpy.memmap`, argparse subcommands,
  the DSP thread pool).
- Split a self-contained interactive widget into its own module inside the same feature package —
  the preview seek control lives in `reference_removal/preview.py`, for instance.

### Audio and Memory

- Stream long audio with `create_pcm_audio` and block loops (block size from
  `shared.audio.BLOCK_FRAMES`); never copy a whole file into an ordinary in-memory array. Release
  mapped pages with `shared.audio.release_mapped_pages()`.
- A cancellable loop must call `CancellationToken.raise_if_cancelled()` regularly, and must never
  swallow the cancellation exception.
- Write output through `write_wav_atomic`; never overwrite the target file directly.
- The export format follows the input file: `AudioData` carries the decoded source's `sample_rate`
  alongside its `bit_depth`, `resample_audio` and `stereo()` carry both forward, and
  `write_wav_atomic` and `analyze_audio` read them off the audio rather than taking a format
  argument. `WAV_BIT_DEPTHS` is `(16, 24)`: 8-bit and 16-bit PCM inputs are written as 16-bit,
  while wider 24/32-bit PCM, float, and every lossy format are written as 24-bit. There is no
  export floor, and nothing may be resampled upwards to hit a nicer-looking number.

### DSP

Every user-selectable path must reconstruct its output from the original stage mix, and must never
write source-only content or its inverted polarity into the result. DSP changes are accepted on
measurement, not on argument: pass the automated checks first, then export directly comparable
versions from fixed real-world material. Technical check results must not be reported as
confirmation of listening quality.

## Interface Text and Translations

Interface strings are edited in Qt Linguist `.ts` files (XML); the compiled `.qm` output is loaded
by `QTranslator`:

```text
src/resources/i18n/zh_cn.ts   src/resources/i18n/zh_cn.qm
src/resources/i18n/en_us.ts   src/resources/i18n/en_us.qm
src/resources/i18n/ja_jp.ts   src/resources/i18n/ja_jp.qm
src/resources/i18n/ko_kr.ts   src/resources/i18n/ko_kr.qm
```

The `.ts` files are indexed by key rather than by source text: `<source>` is a short identifier
like `nav_mr`, `<translation>` is the text for that language, and all four files share the single
`Purivox` context. Changing the Chinese wording therefore does not disturb the other languages,
`pyside6-lupdate` does not apply (it extracts literals from source code), and the entries are
maintained by hand.

Search the four catalogues before inventing a string: the desktop has already named most states
(`warn_no_song`, `stage_need_sources`, `preview_empty`, the whole `home_*` set), and reusing an
existing key gets four locales right at once.

Any `.ts` change must be recompiled, and the `.ts` and `.qm` committed together:

```bash
for locale in zh_cn en_us ja_jp ko_kr; do
  uv run --locked pyside6-lrelease "src/resources/i18n/$locale.ts" \
    -qm "src/resources/i18n/$locale.qm"
done
```

Adding, removing, or renaming a translation key means editing all four `.ts` files. The tests check
that the key sets match exactly, that no `.qm` is stale against its `.ts`, and that every literal
key appearing in the source exists in every language. Calls to `tr(key, **values)` must not rely on
the "unknown key returns the key" fallback.

Language is application state: `shared.i18n.install_language()` installs that language's
`QTranslator` and `tr()` looks up through `QCoreApplication.translate()`, so job objects and
processing pipelines carry no language parameter. Switching the language in the GUI settings page
reinstalls the translator and calls each page's `retranslate()`; the CLI installs once at startup
from `--lang`.

Configuration is the QConfig singleton in `src/shared/config.py`. Changing a persistent option
means considering its default, its validator, page retranslation, and the tests together.

## New Files Must Be Registered in Three Places

When adding a source directory or file, check three shipping manifests. Missing any one of them can
leave the development environment working while the wheel or the standalone build is missing files:

1. the wheel package list in `pyproject.toml`;
2. `[tool.pyside6-project].files` in `pyproject.toml`;
3. `include-package`, or the corresponding entry, in `pysidedeploy.spec`.

`tests/test_packaging.py` compares every `src/**/*.py` against `[tool.pyside6-project].files` and
rejects a missing or dead entry; a new top-level package still needs the wheel and Nuitka lists
confirmed by hand.

## The Browser Front End

`web/` is a Vite + React front end running the same `src/`: `predev` / `prebuild` pack the Python
tree into `purivox-src.zip` and regenerate the translation JSON, so rerunning them is all that a
change to Python or to a `.ts` catalogue needs.

```bash
cd web && bun install
bun run dev        # http://localhost:5173/
bun run check      # tsc + Biome + the layering check, which build runs first
```

The front end's layering mirrors the Python side and is enforced the same way, by
`scripts/check-architecture.mjs`. When changing DSP, note that Pyodide has no pthreads, so
`process_audio` carries a serial branch, and
`tests/features/reference_removal/test_dsp_execution.py` holds both paths to the same output. See
[Browser Build (WebAssembly)](web.md) for the details.

## Verifying a Change

Qt tests need the offscreen platform, which conftest sets:

```bash
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest
uv build
```

A DSP change also owes a measurement rather than an explanation:

```bash
uv run --locked python tools/eval_cancellation.py --save baseline.json    # before
uv run --locked python tools/eval_cancellation.py --compare baseline.json # after
```

The slow benchmark is opt-in. It runs 15 minutes of 44.1 kHz stereo audio through reference
cancellation and checks output length, seam smoothness, and peak resident memory against a 2 GiB
ceiling:

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow
```

Synthetic metrics exist to catch implementation regressions and claim nothing about real music.

### Where Tests Go

`tests/` mirrors `src/` path for path, so a change's tests are at the mirrored location: DSP and
alignment regressions under `tests/features/reference_removal/`, timeline and matching under
`full_stage/`, model download / verification / cancellation under `neural_separation/`, runner and
presenter lifecycles and the pytest-qt interface tests under `tests/app/`, and shared audio, job
contracts, and widgets under `tests/shared/`.

Pytest uses the `importlib` import mode, so different directories may reuse the test file name that
matches their source without a module collision. Three repository-wide gates sit alongside:
`test_architecture.py` (import boundaries), `test_packaging.py` (the shipped-source roster), and
`test_documentation.py` (README index, documentation translation pairing, internal links). When
renaming a document, update the index and the references with it rather than leaving a dead link
for someone else to find.

No test reaches a real host: the model-store and update-check tests point
`catalog.MODEL_BASE_URL` and `updates.RELEASES_API` at a local server.

### What CI Runs

Pull requests and commits on `main` trigger `.github/workflows/build.yml`, a thin shell that calls
`.github/workflows/common.yml` for the full pipeline: the quality checks above, then Linux,
Windows, and macOS artifacts built in parallel. The quality checks run once, on Ubuntu; the Windows
and macOS jobs only produce binaries. Artifacts are kept for 14 days, and a new commit on the same
branch cancels the older run.

## Commits

- The **subject** is `type(scope): what changed` — imperative, lower case, no trailing period. The
  types in use are `feat`, `fix`, `perf`, `refactor`, `docs`, `ci`, `build`, and `chore`; the scope
  is the area (`dsp`, `ui`, `web`, `audio`, `i18n`, `full-stage`, `settings`, `shared`, `release`)
  and may be dropped for a change that spans the repository.
- The **body** is English prose wrapped at 80 columns explaining why the change looks like this:
  the problem, the constraint that decided the design, what was rejected and why. Not a restatement
  of the diff, and not a bullet list.
- One commit does one thing. A translation change carries its recompiled `.qm`; a dependency change
  carries `uv.lock`.

The existing commits are the examples:

```text
perf(dsp): build the cancellation chain in place instead of a temporary per step
fix(web): merge Fluent class names instead of concatenating them
refactor(dsp): run the pipelines where there is no Qt and no threads
```

A user-facing change also earns a line in the matching version's section of `CHANGELOG.md`. There
is one bilingual section per released version — the release workflow publishes the section whose
heading matches the tag, and the in-app update dialog shows that same text.

## Packaging and Release (Maintainers)

Ordinary contributions do not run anything in this section.

`uv build` writes the wheel and sdist to `dist/`. The version has one source, `src/app/version.py`,
which Hatch reads at build time; the ONNX weights are in the ignore list and reach neither the
wheel nor the sdist. The standalone builds go through `pyside6-deploy` wrapping Nuitka
(`uv sync --locked --group deploy`): Linux and Windows get the onefile `dist/Purivox.bin` /
`Purivox.exe`, macOS gets the `dist/Purivox.app` bundle and is built for arm64 only, because the
lock file's macOS ONNX Runtime wheel comes in no other architecture. All three bundle Python and Qt
and carry no model weights. CI builds them; before a release, actually launch one and confirm the
resources under the unpacked path can still be found.

Releases are tag-driven, with no manual step beyond the tag:

1. update `__version__` in `src/app/version.py`;
2. add a section at the top of `CHANGELOG.md` titled `## v<version> — <date>`;
3. commit, then tag with the same name and push.

```bash
git tag -a v1.0.0 -m "Purivox v1.0.0"
git push origin main --follow-tags
```

Once the tag is pushed, `release.yml` runs the whole `common.yml` pipeline and its `publish` job
ships the artifacts from that same run, regenerating a flat `SHA256SUMS`. The first quality-check
step compares the tag against `src/app/version.py` and fails within minutes on a mismatch rather
than after an hour of compiling. A suffixed tag (`v1.1.0-rc1`, say) is published as a pre-release
and does not appear at `releases/latest`. Re-running a build for the same tag overwrites the
existing assets instead of creating a second release.

The AUR package (`deployment/aur/`) is pushed after a release by running
`deployment/aur/publish.sh` by hand, never by CI: it re-points `purivox-bin` at that release's
`.deb`, builds it once as a check, and pushes `PKGBUILD` and `.SRCINFO`.
