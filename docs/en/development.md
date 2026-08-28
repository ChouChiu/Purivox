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
- Qt background tasks are coordinated by `app/job_presenter.py`, which manages page state, and
  then passed to `app/job_runner.py` for thread ownership. Pages and processing pipelines must not
  create their own threads.
- Independent interactive widgets on a page should live in a small module inside the same feature
  package. The preview-seek widget, for example, is in `reference_removal/preview.py`.
- Use `create_pcm_audio` and chunked loops for long audio; do not copy an entire file into an
  ordinary in-memory array.
- Cancellable loops must call `CancellationToken.raise_if_cancelled()` periodically and must not
  swallow cancellation exceptions.
- Use `write_wav_atomic` for output instead of overwriting the destination directly.
- Every product pipeline uses `prepare_hi_res_output` before writing, ensuring PCM WAV output at
  96 kHz / 24-bit or higher. Upsampling must never be described as creating new audio detail.
- Log through `logging.getLogger(__name__)`; a local failure may be ignored only on an explicitly
  documented fallback path.

Ruff uses a line length of 100 and enables E, F, I, UP, B, SIM, and RUF rules. E501 is left to
formatting and review.

## Translation and Configuration

Interface strings are stored in:

```text
src/resources/i18n/zh_cn.json
src/resources/i18n/en_us.json
src/resources/i18n/ja_jp.json
src/resources/i18n/ko_kr.json
```

Adding, removing, or renaming a translation key requires updating all four files; tests enforce
identical key sets. Calls to `tr(language, key, **values)` must not depend on the fallback that
returns an unknown key unchanged.

Configuration is managed by the `QConfig` singleton in `src/shared/config.py`. When changing a
persistent option, account for its default value, validator, page retranslation, and tests.

Reference-guided vocal isolation uses reference-mask cancellation. Every user-selectable path must
reconstruct output from the original stage mix and must never write source-only content or its
inverted polarity into the result. DSP changes cannot be judged from synthetic metrics alone:
first pass the automated gates, then export directly listenable comparisons from fixed real-world
material. Technical checks must not be reported as confirmation of listening quality.

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
- The 96 kHz / 24-bit-or-higher Hi-Res export contract across all three product pipelines;
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

Onefile unpacks into a temporary directory on every run, so it needs matching scratch space. The
startup cost is modest in practice: the 126 MB Linux build completes a full `--selftest` run in
about 3.1 seconds, with no meaningful difference between a cold and a warm start. In addition to
automated testing, launch the executable before release and verify page navigation, model lookup,
audio decoding, task cancellation, and output preview — in particular that resource files are
still found under the unpacked path.

The Windows build reuses the same `pysidedeploy.spec`, but the icon has to be rewritten, so CI
derives a `pysidedeploy-windows.spec` from it (that file is not committed):

- `pyside6-deploy` carries a single `icon` key and hands it to Nuitka as
  `--windows-icon-from-ico` on Windows, which will not accept the SVG the Linux build uses. The
  committed `deployment/purivox.ico` is rendered from `src/resources/purivox.svg` at seven sizes
  from 16 to 256 pixels; changing the icon means updating both.

`--assume-yes-for-downloads` in the shared specification is required on both platforms: onefile
downloads the components its bootstrap needs, and without the flag Nuitka stops on a confirmation
prompt and hangs the runner.

`patchelf` was removed from the specification's `packages`: `pyside6-deploy` already installs it
itself on Linux, and on Windows it would try to install a package that only publishes Linux
wheels, and fail.

## Continuous Integration

`.github/workflows/build.yml` runs on the `main` branch, `v*` tags, pull requests, and manual
dispatch. After the quality gates pass, the workflow builds the Linux and Windows outputs in
parallel, then uploads:

- Pytest JUnit XML;
- Separate logs for quality-gate and build commands;
- The wheel, source distribution, and their SHA-256 checksum files;
- A tarball of the Linux executable, which preserves its executable bit, plus its SHA-256
  checksum;
- The Windows executable plus its SHA-256 checksum.

The quality gates run on Ubuntu only: the Windows job produces the distributable binary and does
not repeat the test suite.

Both quality and build jobs write a GitHub Job Summary listing gate results, cache-hit status,
logs, and artifact links. Even if an earlier step fails, the jobs write as much known information
as possible.

Artifacts are retained for 14 days. The uv dependency cache is invalidated by the contents of both
`uv.lock` and `pyproject.toml`, and also caches the Python 3.14 installation managed by uv; the
`.venv` directory itself is not cached. Linux standalone builds additionally use ccache,
invalidated by the lockfile, deployment specification, and Python source, with a 2 GiB limit; the
Windows job caches Nuitka's own compiler cache directory under the same key scheme. A
new commit on the same branch cancels an older run, while tag builds are never cancelled.

The Ubuntu runner explicitly installs `libegl1`, which Qt requires for loading. Every command step
uses Bash with `pipefail`, so piping output through `tee` does not hide the command's failure
status. JUnit XML is uploaded only when it was actually generated.
