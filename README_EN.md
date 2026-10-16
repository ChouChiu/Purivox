# Purivox

<p align="left">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

**[▶ Use it in your browser](https://purivox.wwchun.top/)** (WebAssembly build, 100% local processing, audio never leaves your browser)

Purivox is a reference-guided vocal isolation and backing cancellation tool designed for stage and live recordings. It is available as both a desktop application and a client-side WebAssembly web application, built with Python, PySide6, and PySide6-Fluent-Widgets. The core reference cancellation workflow takes a stage or live recording along with one or more reference song audio tracks:

- **Single Reference**: Automatically aligns and cancels the reference track. When the reference track and recording have comparable durations, global tempo and clock-drift corrections are applied over the full file; when the reference covers only a section, cancellation is performed within the matched segment.
- **Multiple References**: Automatically identifies and locates candidate songs within the recording, rendering cancellation separately for each matched segment. Input file order does not affect matching.

Reference cancellation subtracts only the playback components that can be explained by the reference audio. It preserves live vocals, stage speech, audience reactions, and room acoustics that are absent from the studio reference. Performance depends on reference quality: severe clipping, heavy venue reverberation, differing musical arrangements, or mismatched song versions will degrade cancellation depth.

For blind two-track separation without reference audio, consider dedicated neural-network tools such as [Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui). Purivox focuses on coherent reference cancellation.

## Key Features

- **Fluent UI**: Desktop interface built with PySide6-Fluent-Widgets supporting light, dark, and system themes.
- **Internationalization**: Runtime switching across Simplified Chinese, Traditional Chinese, English, Japanese, and Korean.
- **DSP Engine**: Global tempo estimation and pitch-preserving time stretching (WSOLA), sub-millisecond coarse alignment, local clock-drift tracking, and complex coherent transfer estimation.
- **Timeline Management**: Multi-source fingerprint matching, candidate clustering, and interactive timeline segment editing.
- **Memory Efficiency**: Chunked streaming processing (`BLOCK_FRAMES`), cooperative task cancellation, and atomic file replacements.
- **Format Integrity**: Output files strictly retain the original sampling rate and format-appropriate bit depth, avoiding artificial upsampling.
- **Review Tools**: In-app player for instant preview and comprehensive audio statistics.
- **Release Checks**: Settings page checks GitHub Releases and displays changelogs without automated background updates.
- **Crash Reporting**: Daily rotating log files; unhandled exceptions provide structured diagnostics and a preformatted issue submission workflow.
- **Keyboard Shortcuts**: `Ctrl+O` to open files, `Ctrl+Return` to start, `F5` to identify songs, `Esc` to cancel, and `Ctrl+P` to toggle preview playback.
- **Link Fetching**: Built-in downloader for YouTube and YouTube Music URLs with local deduplication caching.
- **Isomorphic Core**: The desktop GUI, CLI, and WebAssembly browser build share the identical signal-processing pipeline.

## Installation

### WebAssembly Browser Version

To use Purivox without local installation, visit the [WebAssembly browser build](https://purivox.wwchun.top/). It runs the same processing pipeline directly in your browser. Due to browser memory limits, it is best suited for short- to medium-length recordings; see [Browser Build (WebAssembly)](docs/en/web.md) for details.

### Desktop Binaries

Prebuilt binaries are available on the [GitHub Releases page](https://github.com/ChouChiu/Purivox/releases/latest):
- **Windows**: `Purivox.exe`
- **Linux**: `.deb`, `.rpm`, or standalone archive `purivox-linux-x86_64.tar.gz`
- **macOS**: `purivox-macos-arm64.tar.gz` (Apple Silicon) or `purivox-macos-x86_64.tar.gz` (Intel)

All releases include `SHA256SUMS` checksum files. For macOS builds without an Apple developer signature, right-click `Purivox.app` in Finder and select "Open" on first launch.

### Running from Source

Running from source requires [uv](https://docs.astral.sh/uv/). Python versions and dependencies are locked via `.python-version` and `uv.lock`:

```bash
uv sync --locked
```

Launch the desktop interface:

```bash
uv run --locked purivox
```

## Desktop Usage

### Vocal Isolation

1. Open the **Vocal Isolation** page and select the stage or live recording.
2. Add reference song tracks. A single track can be processed directly; multiple tracks are automatically matched across the recording.
3. For multiple tracks, click **Find songs** to inspect detected full songs, short segments, unassigned regions, and confidence scores.
4. Verify the timeline. Double-click entries to adjust timestamps or source ranges, or uncheck clips to skip them.
5. In **Export Options**, choose which stems to output: isolated live vocal, backing track, or both. The backing track is rendered from the reference track through the estimated transfer function, preserving studio reference quality while reflecting stage frequency response and levels.
6. Adjust the removal strength and start processing. If live vocals sound thin or show audible pumping, reduce the strength setting or verify the reference track match.

> **Note**: Use reference tracks that match the live arrangement as closely as possible. Pitch shifts, tempo variations, or modified edits reduce cancellation performance. Unmatched intervals retain the original live audio without truncation.

### Fetching Reference Audio from URLs

The stage file row and reference track list include a **Fetch** button:

1. Paste a YouTube or YouTube Music URL, or search YouTube by keywords.
2. Downloaded tracks are cached in the downloads list to prevent duplicate transfers.
3. URLs with playlist parameters download only the target video, not the entire playlist.
4. Select items and click **Use Selected** to populate the input fields.

If FFmpeg is present, downloads are converted to WAV; otherwise, original containers are preserved and read through the Qt Multimedia fallback decoder. Files are stored under `downloads/` in the application data directory.

## Command-Line Usage

### Help and Version

```bash
uv run --locked purivox --version
uv run --locked purivox --help
uv run --locked purivox mr --help
```

### Reference Cancellation

Run standard reference cancellation with defaults:

```bash
uv run --locked purivox mr "stage.wav" "reference.wav" "output_vocal.wav"
```

Specify cancellation strength, analysis window, and enable alignment:

```bash
uv run --locked purivox mr "stage.wav" "reference.wav" "output_vocal.wav" \
  --strength 75 --sigma 8 --align
```

Options:

| Option | Values | Description |
|---|---:|---|
| `--strength` | `0`–`100` | Cancellation strength (default: `75`) |
| `--sigma` | `1`, `3`, `8`, `16` | Smoothing window in seconds (default: `3`) |
| `--align` / `--no-align` | Flag | Automatic alignment and drift correction (default: enabled) |
| `--tracks` | `vocal`, `backing`, `both` | Tracks to export (default: `vocal`) |
| `--lang` | `zh_cn`, `zh_tw`, `en_us`, `ja_jp`, `ko_kr` | Output progress language |

### Reference Download

```bash
uv run --locked purivox fetch "https://www.youtube.com/watch?v=..."   # Direct download
uv run --locked purivox fetch "query" --limit 5                        # Search candidates
uv run --locked purivox fetch "query" --pick 2                         # Download candidate #2
uv run --locked purivox fetch --list                                  # List cached downloads
```

| Option | Values | Description |
|---|---:|---|
| `--out` | Path | Download cache directory (defaults to app data `downloads/`) |
| `--limit` | Integer | Maximum search results (default: `10`) |
| `--pick` | Integer | Pick result index to download (1-based) |
| `--list` | Flag | List cached downloads |

On success, the absolute path of the downloaded file is written to stdout for piping into `purivox mr`.

## Technical Notes

- **Format Support**: libsndfile handles uncompressed and standard audio containers (WAV, FLAC, OGG). Other system formats are decoded via Qt Multimedia fallback.
- **Sampling Rates and Bit Depths**: Processing runs entirely at the recording's native sample rate. Output PCM WAV files strictly preserve native sampling rate and appropriate bit depths (16-bit for 8-bit/16-bit inputs; 24-bit for 24-bit/32-bit float or lossy inputs) without artificial upsampling.
- **File Safety**: Output paths cannot overwrite input files. Writes use temporary files and atomic replacement (`os.replace`) to prevent file corruption upon cancellation or failure.
- **Cooperative Cancellation**: Tasks can be interrupted cleanly via `Ctrl+C` (CLI) or interface controls.

## Technical Documentation

Detailed architecture, DSP algorithms, and development references are documented in [docs/](docs/en/README.md):

- [Architecture and Data Flow](docs/en/architecture.md)
- [Reference Cancellation](docs/en/reference-removal.md)
- [Source Matching, the Timeline, and Segmented Rendering](docs/en/matching.md)
- [Browser Build (WebAssembly)](docs/en/web.md)
- [Contributing](docs/en/CONTRIBUTING.md)

## License and Acknowledgements

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor): Conceptual inspiration for frequency-domain vocal cancellation.
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui): Benchmark tool for reference-free neural separation.

Purivox is licensed under [AGPL-3.0-or-later](LICENSE). PySide6-Fluent-Widgets is licensed under GPLv3; verify upstream licensing requirements for commercial deployments.
