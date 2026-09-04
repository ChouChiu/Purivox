# Development, Testing, and Release

<p align="left">
  <a href="../development.md">简体中文</a> · <strong>English</strong>
</p>

## Development Environment

The project uses uv to manage Python, its isolated environment, and the lockfile. After installing
uv, synchronize the locked runtime and default development dependencies from the repository root:

```bash
uv sync --locked
```

Install the deployment dependencies only when building the Linux standalone application:

```bash
uv sync --locked --group deploy
```

When changing dependencies, use `uv add <package>`, `uv add --dev <package>`, or
`uv add --group deploy <package>`, and commit the corresponding changes to both `pyproject.toml`
and `uv.lock`.

Do not install another PyQt or PySide Fluent component that exports `qfluentwidgets` into the same
environment. This project specifically uses `PySide6-Fluent-Widgets[full]`.

## Code Conventions

- New modules use `from __future__ import annotations` and complete type annotations.
- Prefer `frozen=True, slots=True` data classes for job models with few mutable parameters, and
  use `StrEnum` for fixed string sets.
- Shared infrastructure belongs in `shared`; feature-specific pages, models, and processing logic
  belong in the corresponding `features/<feature>/` package.
- Cross-feature orchestration belongs in `app`. Do not make feature packages import one another
  merely for reuse.
- Data models consumed by multiple features should move down to `shared`; models used by only one
  feature must not be re-exported from another feature for convenience.
- Constants, accepted ranges, and algorithms follow the same rule: a value that appears in two
  features, or in both the GUI and the CLI, is defined once in `shared` and referenced from there —
  for example `shared.audio.BLOCK_FRAMES`, `shared.audio.AUDIO_EXTENSIONS`,
  `shared.jobs.SIGMA_CHOICES`, `shared.i18n.SUPPORTED_LANGUAGES`, and `shared.logging.LOG_LEVELS`.
- Qt background tasks are coordinated by `app/job_presenter.py`, which manages page state, and
  are then passed to `app/job_runner.py`, which owns the threads. Pages and processing pipelines
  must not create their own threads.
- Slots that receive signals across a thread boundary are declared with `@Slot(<types>)`
  (worker → `JobRunner` → `JobPresenter`) so Qt dispatches the queued connection with the declared
  signature.
- Prefer the Qt facility where Qt owns the problem: `QAbstractTableModel` + `TableView` for an
  editable table instead of filling `QTableWidget` items; `QNetworkAccessManager` for HTTP (system
  proxy, redirects, transfer timeout, progress, `abort()`); `QSaveFile` for verify-then-commit
  writes; `QStandardPaths` for locations. Leave the standard library where it is already equal or
  better (`hashlib`, `tempfile` + `numpy.memmap`, argparse subcommands, the DSP thread pool).
- Independent interactive widgets on a page should live in a small module inside the same feature
  package. The preview-seek widget, for example, is in `reference_removal/preview.py`.
- Use `create_pcm_audio` and chunked loops for long audio, sized by `shared.audio.BLOCK_FRAMES`;
  do not copy an entire file into an ordinary in-memory array, and release mapped pages through
  `shared.audio.release_mapped_pages()`.
- Cancellable loops must call `CancellationToken.raise_if_cancelled()` periodically and must not
  swallow cancellation exceptions.
- Use `write_wav_atomic` for output instead of overwriting the destination directly.
- The export format follows the input file: `AudioData` carries the decoded source's `sample_rate`
  and `bit_depth` together, `resample_audio` and `stereo()` carry both forward, and
  `write_wav_atomic` and `analyze_audio` read them off the audio rather than taking a format
  argument. `WAV_BIT_DEPTHS` is `(16, 24)`: an 8- or 16-bit PCM input is written at 16 bits, and
  wider 24-/32-bit PCM, float and every lossy format at 24. There is no export floor, and a result
  must never be resampled upwards just to reach one.
- Log through `logging.getLogger(__name__)`; a local failure may be ignored only on an explicitly
  documented fallback path.

Ruff uses a line length of 100 and enables E, F, I, UP, B, SIM, and RUF rules. E501 is left to
formatting and review.

## Translation and Configuration

Interface strings live in Qt Linguist `.ts` sources (XML), compiled to the `.qm` catalogues that
`QTranslator` loads:

```text
src/resources/i18n/zh_cn.ts   src/resources/i18n/zh_cn.qm
src/resources/i18n/en_us.ts   src/resources/i18n/en_us.qm
src/resources/i18n/ja_jp.ts   src/resources/i18n/ja_jp.qm
src/resources/i18n/ko_kr.ts   src/resources/i18n/ko_kr.qm
```

The catalogues are keyed by identifier rather than by source text: `<source>` holds a short key such
as `nav_mr`, `<translation>` holds the text for that language, and all four files share the single
`Purivox` context. Rewording Chinese therefore leaves the other languages untouched, `pyside6-lupdate`
does not apply (it extracts literals from source code), and entries are maintained by hand.

After editing any `.ts`, recompile and commit the `.ts` and `.qm` together:

```bash
for locale in zh_cn en_us ja_jp ko_kr; do
  uv run --locked pyside6-lrelease "src/resources/i18n/$locale.ts" \
    -qm "src/resources/i18n/$locale.qm"
done
```

Adding, removing, or renaming a key requires updating all four `.ts` files. Tests enforce identical
key sets, check that no `.qm` is stale, and check that every literal key used in the sources exists
in every language. Calls to `tr(key, **values)` must not depend on the fallback that returns an
unknown key unchanged.

Translation is application state: `shared.i18n.install_language()` installs that language's
`QTranslator`, and `tr()` resolves through `QCoreApplication.translate()`. Job objects and
processing pipelines therefore no longer carry a language parameter. The GUI reinstalls and calls
`retranslate()` when the setting changes; the CLI installs `--lang` once at startup.

Configuration is managed by the `QConfig` singleton in `src/shared/config.py`. When changing a
persistent option, account for its default value, validator, page retranslation, and tests.

Reference-guided vocal isolation uses reference cancellation. Every user-selectable path must
reconstruct output from the original stage mix and must never write source-only content or its
inverted polarity into the result. DSP changes cannot be judged from synthetic metrics alone:
first pass the automated checks, then export directly listenable comparisons from fixed real-world
material. Technical check results must not be reported as confirmation of listening quality.

## Adding Source Files

When adding a source directory or file, check three release manifests:

1. The wheel package list in `pyproject.toml`;
2. `[tool.pyside6-project].files` in `pyproject.toml`;
3. `include-package` or the corresponding include entry in `pysidedeploy.spec`.

Missing any one can produce a working development environment but an incomplete wheel or
standalone application. `tests/test_packaging.py` automatically compares all `src/**/*.py` files
with `[tool.pyside6-project].files` and rejects missing or stale entries. New top-level packages
still require manual verification of both the wheel and Nuitka package lists.

## Quality Gates

Qt tests must use the offscreen platform:

```bash
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest
uv build
```

Slow benchmarks must be enabled explicitly:

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow
```

The current slow gate uses 15 minutes of 44.1 kHz stereo audio to check reference-cancellation
output duration, seams, and peak resident memory, with a 2 GiB memory limit.

The test tree mirrors the source structure and primarily covers:

- Shared audio I/O, resampling, atomic output, short-time Fourier transforms, and logging;
- The source-format export contract across all three product pipelines;
- Reference cancellation, time alignment, stereo matrices, regression scenarios, and end-to-end
  jobs;
- Full Stage matching, timeline models, and segmented rendering;
- MDX-Net chunked overlap-add and the model pipeline;
- CLI options, GUI navigation, settings, and statistics display;
- Layered import boundaries, release manifests, and translation-key parity across four languages.

Place a test according to the source it covers. Algorithms internal to a feature belong in
`tests/features/<feature>/`; application orchestration combining multiple features belongs in
`tests/app/`; shared audio, task protocol, and widgets belong in `tests/shared/`. Pytest uses
`importlib` import mode, allowing separate directories to use test filenames that mirror the
source without module collisions. The test tree can therefore expose cross-layer dependencies as
well.

`tests/test_documentation.py` checks internal links in the READMEs and `docs/`, ensures both
language versions contain the same technical-document set, and verifies that every technical
document is reachable from the corresponding project README. When renaming documentation, update
indexes and references together instead of leaving broken links for manual discovery.

## Building the Python Package

```bash
uv build
```

Artifacts are written to `dist/`. The version in `src/app/version.py` is the single source of
truth and is read dynamically by Hatch. ONNX weights are ignored and are not included in the wheel
or source distribution. After building, install the wheel in a temporary uv environment and
verify it; adjust the version in the path to match the actual artifact:

```bash
uvx --from ./dist/purivox-1.0.0-py3-none-any.whl purivox --version
QT_QPA_PLATFORM=offscreen uvx --from ./dist/purivox-1.0.0-py3-none-any.whl \
  purivox --selftest
```

## Standalone Applications

The project uses Qt's official `pyside6-deploy` wrapper around Nuitka and fixes the output to
`onefile` mode:

```bash
uv sync --locked --group deploy
uv run --locked --group deploy pyside6-deploy -c pysidedeploy.spec
```

The output is a single executable — `dist/Purivox.bin` on Linux and `dist/Purivox.exe` on
Windows — containing Python, Qt, Fluent Widgets, SciPy, SoundFile, soxr, and ONNX Runtime, but not
model weights.

`mode = onefile` has no effect on macOS: `pyside6-deploy` always passes `--standalone
--macos-create-app-bundle` there, and the output is the application bundle `dist/Purivox.app` with
the same contents. CI builds arm64 only, because the lockfile's ONNX Runtime has no other macOS
wheel.

Onefile unpacks into a temporary directory on every run, so it needs matching scratch space. The
startup cost is modest in practice: the 126 MB Linux build completes a full `--selftest` run in
about 3.1 seconds, with no meaningful difference between a cold and a warm start. In addition to
automated testing, launch the executable before release and verify page navigation, model lookup,
audio decoding, task cancellation, and output preview — in particular that resource files are
still found under the unpacked path.

The Windows and macOS builds reuse the same `pysidedeploy.spec`, each deriving its own rewritten
copy in CI (`pysidedeploy-windows.spec` and `pysidedeploy-macos.spec`, neither committed):

- `pyside6-deploy` carries a single `icon` key and hands it to Nuitka as
  `--windows-icon-from-ico` on Windows and `--macos-app-icon` on macOS, neither of which accepts
  the SVG the Linux build uses. The committed `deployment/purivox.ico` (seven sizes from 16 to 256
  pixels) and `deployment/purivox.icns` (ten entries from 16 to 1024) are both rendered from
  `src/resources/purivox.svg`; changing the icon means updating all three. An icon that is not
  already `.icns` goes to imageio, which is neither installed nor able to read SVG.
- A macOS bundle takes its name and its Info.plist from the entry point, which is
  `deployment/main.py`, so an untouched build produces a `main.app` calling itself main in the dock
  and the menu bar. The derived spec therefore adds `--output-folder-name`, `--output-filename`,
  `--macos-app-name`, `--macos-signed-app-name` (the project homepage domain reversed,
  `top.wwchun.purivox`) and `--macos-app-version` (read from `src/app/version.py`).
- Nuitka signs the bundle ad-hoc, and the seal covers the symlinks it made for
  `Contents/Frameworks`; `pyside6-deploy`'s copy into `dist/` follows those symlinks, which stores
  every Qt framework twice and invalidates the seal. With `--output-folder-name` changed it finds
  nothing under the name it copies from (the log keeps one "executable not found" line), and
  `--keep-deployment-files` leaves Nuitka's own output in `deployment/deployment/` for the build
  job to move into `dist/` and check with `codesign --verify`.

`--assume-yes-for-downloads` in the shared specification is required on all three platforms:
onefile downloads the components its bootstrap needs and Nuitka downloads ccache on macOS, and
without the flag Nuitka stops on a confirmation prompt and hangs the runner.

`patchelf` was removed from the specification's `packages`: `pyside6-deploy` already installs it
itself on Linux, and on Windows and macOS it would try to install a package that only publishes
Linux wheels, and fail.

## Continuous Integration

The build steps are written once, in `.github/workflows/common.yml`: a `workflow_call` workflow
that takes no parameters, because what a release ships must not be built differently from what a
branch builds. Each trigger is a thin shell over it — `build.yml` on the `main` branch, pull
requests, and manual dispatch; `release.yml` on `v*` tags, with one `publish` job after the build.
A called workflow shares the run of its caller, so `publish` downloads the very artifacts that run
uploaded.

After the quality gates pass, `common.yml` builds the Linux, Windows, and macOS outputs in
parallel, then uploads:

- Pytest JUnit XML;
- Separate logs for quality-gate and build commands;
- The wheel, source distribution, and their SHA-256 checksum files;
- A tarball of the Linux executable, which preserves its executable bit, a `.deb`, an `.rpm`, and
  one SHA-256 checksum file covering them;
- The Windows executable plus its SHA-256 checksum;
- A tarball of the macOS application bundle, which preserves its executable bits and framework
  symlinks, plus its SHA-256 checksum.

`deployment/package-linux.sh` builds the `.deb` and the `.rpm` with fpm from one staged tree: the
executable lands at `/usr/bin/purivox` next to `deployment/purivox.desktop`, the icon, and the
licence. The onefile carries its own Python and Qt, so the packages declare only the two libraries
Qt still loads from the distribution (`libegl1` and `libpulse0` on deb, `mesa-libEGL` and
`pulseaudio-libs` on rpm). A onefile's payload is appended to the executable, so any strip pass
destroys it — which is why the packages are built this way rather than through a distribution's
own tooling.

The quality gates run on Ubuntu only: the Windows and macOS jobs produce the distributable
binaries and do not repeat the test suite.

Both quality and build jobs write a GitHub Job Summary listing gate results, cache-hit status,
logs, and artifact links. Even if an earlier step fails, the jobs write as much known information
as possible.

Artifacts are retained for 14 days. The uv dependency cache is invalidated by the contents of both
`uv.lock` and `pyproject.toml`, and also caches the Python 3.14 installation managed by uv; the
`.venv` directory itself is not cached. Linux standalone builds additionally use ccache,
invalidated by the lockfile, deployment specification, and Python source, with a 2 GiB limit; the
Windows and macOS jobs cache Nuitka's own cache directory under the same key scheme — a macOS
runner carries no ccache, so Nuitka downloads one in there, next to the compilation cache. A
new commit on the same branch cancels an older run (`build.yml` sets `cancel-in-progress`), while
tag builds are never cancelled — `release.yml` turns it off, that run being the only one that can
publish.

The Ubuntu runner explicitly installs `libegl1`, which Qt requires for loading. Every command step
uses Bash with `pipefail`, so piping output through `tee` does not hide the command's failure
status. JUnit XML is uploaded only when it was actually generated.

## Releasing

A release is driven by its tag; tagging is the only manual step:

1. Update `__version__` in `src/app/version.py`;
2. Add a section at the top of `CHANGELOG.md`, headed `## v<version> — <date>`;
3. Commit, then tag and push:

```bash
git tag -a v1.0.0 -m "Purivox v1.0.0"
git push origin main --follow-tags
```

Pushing the tag has `release.yml` run all of `common.yml` first, and its `publish` job then
publishes what that run built: the
Windows executable, the Linux tarball, `.deb` and `.rpm`, the macOS tarball, the wheel and source
distribution, and one flat `SHA256SUMS` regenerated over them (each per-job checksum file names
`dist/` paths that do not resolve on a release page, so they are not uploaded).

The first quality-gate step checks the tag against `src/app/version.py` on a tag build, so a
mismatch fails within minutes instead of after an hour of compiling. Release notes come from the
`CHANGELOG.md` section matching the tag — the same text the in-app update dialog shows — falling
back to GitHub's generated notes when no such section exists. A tag carrying a suffix
(`v1.1.0-rc1`) is published as a pre-release, which `releases/latest` does not answer with, so it
is never offered to users.

Re-running a tag build does not fail: an existing release has its assets replaced rather than a
second release created.
