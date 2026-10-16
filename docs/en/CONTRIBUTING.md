# Contributing

<p align="left">
  <a href="../CONTRIBUTING.md">简体中文</a> · <strong>English</strong>
</p>

This document outlines environment setup, architectural layering, code conventions, localization workflows, test verification, and CI/CD release procedures for the Purivox project.

## Development Environment Setup

Purivox uses [uv](https://docs.astral.sh/uv/) for Python packaging and virtual environment management. Synchronize dependencies from the repository root:

```bash
uv sync --locked
```

The required Python version is pinned in `.python-version`. `uv` automatically manages the isolated environment.

Verify local setup:

```bash
uv run --locked purivox                                        # Launch desktop GUI
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest   # Headless pipeline smoke test
```

Manage dependencies using `uv add <package>`, `uv add --dev <package>`, or `uv add --group deploy <package>`, committing updated `pyproject.toml` and `uv.lock` files together.

Do not install external Qt Fluent components that export the `qfluentwidgets` namespace into this environment to prevent import conflicts.

## Architectural Layering Rules

Dependencies must flow strictly top-to-bottom:
- `src/shared/` serves as shared infrastructure and must never import from `app`, `entrypoints`, or `features/`;
- Feature modules (`src/features/`) encapsulate pages, models, and domain pipelines; cross-feature imports are prohibited;
- Orchestration shells (`src/app/` and `src/web/`) must never import from `entrypoints/`;
- Shared algorithms, types, and constants must reside in `src/shared/`.

Import boundaries are enforced statically by `tests/test_architecture.py`.

## Code Conventions

### Python Conventions

- Modules declare `from __future__ import annotations` and include complete type annotations;
- Task and configuration models use frozen slotted dataclasses (`@dataclass(frozen=True, slots=True)`), using `StrEnum` for fixed string sets;
- Loggers are instantiated via `logging.getLogger(__name__)`; unhandled exceptions must not be suppressed silently;
- Static analysis adheres to Ruff configurations (100 character line length, enforcing E, F, I, UP, B, SIM, and RUF rules).

### Qt Desktop Conventions

- UI pages handle rendering and signal emission; background jobs are orchestrated via `app/job_presenter.py` and executed by `TaskRunner` in `shared/tasks.py`;
- Cross-thread signal slots must be decorated with explicit types using `@Slot(<type>)`;
- Prefer standard Qt components (e.g., `QAbstractTableModel` paired with Fluent `TableView`, `QNetworkAccessManager` for HTTP operations, `QSaveFile` for atomic disk writes);
- Self-contained UI controls should be modularized within their respective feature packages.

### Audio and Memory Management

- Long-audio processing must combine `create_pcm_audio` with streaming block loops (`shared.audio.BLOCK_FRAMES`), avoiding accumulating full-file arrays in system RAM;
- Compute loops must invoke `CancellationToken.raise_if_cancelled()` regularly;
- Audio outputs use `write_wav_atomic` for atomic disk persistence;
- Output formats strictly preserve input sampling rates and format bit depths (16-bit for 8/16-bit PCM; 24-bit for float, lossy, or wider formats). Artificial upsampling is prohibited.

### DSP Evolution Guidelines

- Cancellation outputs must reconstruct solely from original mix audio; reference waveforms or their inversions must never be written directly to output files;
- Algorithm changes require quantitative verification using `tools/eval_cancellation.py`, paired with comparative listening on live audio recordings.

## Localization (i18n)

Interface strings are maintained in Qt Linguist XML catalogs (`src/resources/i18n/*.ts`), compiled to binary `*.qm` files:

```text
src/resources/i18n/zh_cn.ts   src/resources/i18n/zh_cn.qm
src/resources/i18n/zh_tw.ts   src/resources/i18n/zh_tw.qm
src/resources/i18n/en_us.ts   src/resources/i18n/en_us.qm
src/resources/i18n/ja_jp.ts   src/resources/i18n/ja_jp.qm
src/resources/i18n/ko_kr.ts   src/resources/i18n/ko_kr.qm
```

1. **Key Organization**: Catalogs index strings by semantic context keys. Reuse existing keys whenever possible.
2. **Traditional Chinese Usage**: `zh_tw` strictly follows Taiwanese technological conventions (e.g., 檔案, 取樣率, 辨識, 快取).
3. **Compilation**: After editing any `.ts` file, recompile `.qm` files and commit both formats:

```bash
for locale in zh_cn zh_tw en_us ja_jp ko_kr; do
  uv run --locked pyside6-lrelease "src/resources/i18n/$locale.ts" \
    -qm "src/resources/i18n/$locale.qm"
done
```

4. **Catalog Parity**: Test suites verify that all five language catalogs maintain identical key sets and current `.qm` binaries.

## Packaging Declarations (Three-Point Synchronization)

When introducing new source modules or directories, update all three packaging manifests:
1. `pyproject.toml` wheel packages list (`[tool.hatch.build.targets.wheel]`);
2. `pyproject.toml` pyside6 project files (`[tool.pyside6-project].files`);
3. `pysidedeploy.spec` include package entries (`include-package`).

`tests/test_packaging.py` validates repository paths against these manifests.

## Local Verification Workflow

Run all automated checks before submitting pull requests (Qt tests require an offscreen platform):

```bash
uv run --locked ruff check src tests
uv run --locked ruff format --check src tests
QT_QPA_PLATFORM=offscreen uv run --locked pytest
QT_QPA_PLATFORM=offscreen uv run --locked purivox --selftest
uv build
```

To run the intensive 15-minute benchmark checking long-audio memory retention and seam continuity:

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/benchmarks --runslow
```

When modifying documentation, ensure all links and bilingual translation pairings validate:

```bash
QT_QPA_PLATFORM=offscreen uv run --locked pytest tests/test_documentation.py
```

## Commit Conventions

- **Commit Subject**: Format as `type(scope): description` in lowercase imperative prose without trailing periods. Standard types: `feat`, `fix`, `perf`, `refactor`, `docs`, `ci`, `build`, `chore`.
- **Commit Body**: Explain the motivation, technical constraints, and alternative approaches considered, wrapped at 80 characters.
- **Changelog**: User-facing improvements must be documented in both English and Chinese under the current version section in `CHANGELOG.md`.

## Release Procedures (Maintainers)

1. Update `__version__` in `src/app/version.py`;
2. Add a new release section at the top of `CHANGELOG.md`: `## v<version> — <date>`;
3. Commit and push an annotated git tag:

```bash
git tag -a v1.0.0 -m "Purivox v1.0.0"
git push origin main --follow-tags
```

GitHub Actions executes the release workflow in `release.yml`, running quality checks, compiling cross-platform standalone binaries (Linux, Windows, macOS arm64/x86_64), and publishing release artifacts with SHA256 sums. AUR packages (`deployment/aur/`) are updated and published manually via `deployment/aur/publish.sh` following release publication.
