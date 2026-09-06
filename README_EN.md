# Purivox

<p align="left">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

**[▶ Use it in your browser](https://purivox.wwchun.top/)** — nothing to install, and the audio
never leaves your own tab.

Purivox is a vocal isolation tool for stage and live recordings, available as a desktop
application and in the browser, built with Python, PySide6, and PySide6-Fluent-Widgets. Its core
MR Remove feature provides two workflows:

- **Single**: provide a stage/live recording and the corresponding song source. Purivox
  automatically synchronizes them and isolates the live vocals.
- **Full Stage**: provide a continuous stage/live recording and multiple song sources. Purivox
  identifies where each song occurs and isolates the live vocals in each matched segment.

Vocal Isolation removes only content that can be explained by the song source. It is therefore
designed to preserve live vocals, speech, cheering, and ambient sound that are absent from that
source. An accurate song source is essential: clipping, heavy reverberation, a different
arrangement, or the wrong source can all reduce the quality of the result.

For two-track separation without a song source, reach for a dedicated tool such as
[Ultimate Vocal Remover](https://github.com/Anjok07/ultimatevocalremovergui); Purivox only does
reference cancellation.

## Features

- Fluent Design desktop interface with light, dark, and system themes
- Instant switching among Chinese, English, Japanese, and Korean interfaces
- Global time alignment, local clock-drift tracking, and coherent reference cancellation
- Song identification, repeated-segment detection, and editable processing ranges for full-stage
  recordings
- Chunked long-audio processing, task cancellation, and atomic output writes
- Exports keep the input file's sample rate and bit depth, never upsampled to hit a format
- In-app result preview and audio statistics
- The settings page checks for new releases: an update opens one dialog
  with its changelog and a link to the release page — nothing updates itself
- Every run appends to a log file named after the date; an unhandled exception opens
  that day's log and offers the issue form
- The common actions have shortcuts: `Ctrl+O` to choose an input, `Ctrl+Return` to
  start, `F5` to identify songs, `Esc` to cancel, `Ctrl+P` to play/pause the preview
- GUI and CLI reuse the same MR Remove task pipelines

## Installation

If you would rather not install anything, the [browser build](https://purivox.wwchun.top/)
runs the same pipelines. A long enough
stage recording is refused there because a browser tab has a memory ceiling. See
[Browser Build (WebAssembly)](docs/en/web.md) for the details.

The desktop application can be downloaded from the
[latest release](https://github.com/ChouChiu/Purivox/releases/latest): `Purivox.exe` on Windows,
a `.deb`, an `.rpm` or the self-contained `purivox-linux-x86_64.tar.gz` on Linux, and
`purivox-macos-arm64.tar.gz` on Apple Silicon macOS. Every release ships a `SHA256SUMS` alongside
them.

The macOS archive unpacks to `Purivox.app`, which belongs in Applications. It is signed ad-hoc
rather than with an Apple developer identity, so the first launch has to go through Finder's
right-click "Open".

To run from source, [uv](https://docs.astral.sh/uv/) is
required. The project uses `.python-version` to select Python
automatically and manages an isolated environment inside the repository. Do not install another
Qt Fluent component that also exports `qfluentwidgets` into this environment.

```bash
uv sync --locked
```

Start the graphical interface:

```bash
uv run --locked purivox
```

## Using the Graphical Interface

### Single

1. Open **Vocal Isolation** and select **Single**.
2. Select the stage/live audio to process and the corresponding song source.
3. Alignment runs automatically. Start with the default removal strength of 75%; the graphical
   interface uses a fixed statistical window.
4. Under **Export**, choose which stems to save: the vocal only, the backing track only, or
   both. The backing track is the stage/live audio minus the vocal, so it carries the level the
   accompaniment actually had on stage, and the two stems add back up to the original recording.
5. Preview the result before adjusting the strength. If you hear obvious pumping or thinning of
   the live vocal, reduce the strength or confirm that the song source is correct.

Use a song source that matches the version played at the venue as closely as possible. Different
masters, edits, speeds, keys, or extra content will reduce removal quality.

### Full Stage

1. Select **Full Stage** under **Vocal Isolation**, then load the continuous stage/live
   recording.
2. Add song sources that may occur in the recording. Their file order does not affect matching.
3. Click **Find songs**, then inspect full songs, short segments, unidentified ranges,
   and match confidence.
4. If necessary, double-click to edit recording times or source ranges, or clear the checkbox for
   a segment that should not be processed.
5. Confirm the output location, the export choice, and the processing options, then process
   the full recording.

Unidentified ranges retain their original content and duration. Inter-song speech, audience
interaction, advertisements, and empty-stage audio are not removed automatically. Full-stage
processing is currently available only in the graphical interface.

## Command-Line Usage

Display the version and help:

```bash
uv run --locked purivox --version
uv run --locked purivox --help
uv run --locked purivox mr --help
```

Run reference cancellation with the default settings:

```bash
uv run --locked purivox mr "live-recording.wav" "song-source.wav" "live-vocal.wav"
```

The CLI also lets you set the removal strength and statistical window:

```bash
uv run --locked purivox mr "live-recording.wav" "song-source.wav" "live-vocal.wav" \
  --strength 75 --sigma 8 --align
```

Common reference-cancellation options:

| Option | Value | Description |
|---|---:|---|
| `--strength` | `0`–`100` | Vocal isolation strength; default: `75` |
| `--sigma` | `1`, `3`, `8`, `16` | Statistical window in seconds (advanced option); default: `3`; the GUI always uses `3` |
| `--align` / `--no-align` | on / off | Automatic alignment; enabled by default |
| `--tracks` | `vocal`, `backing`, `both` | Which stems to export; default: `vocal` |
| `--lang` | `zh_cn`, `en_us`, `ja_jp`, `ko_kr` | Language used for progress messages |

## Input, Output, and Important Notes

- libsndfile natively supports formats including WAV, FLAC, and OGG. Other formats supported by
  the system decoder are read through Qt Multimedia when possible.
- MR Remove and Full Stage process at the stage/live audio's original sample rate throughout, and
  export at that same rate.
- Every exported PCM WAV keeps the input file's sample rate and bit depth: an 8- or 16-bit PCM
  input is written at 16 bits, and wider 24-/32-bit PCM, float and every lossy format at 24.
  Upsampling cannot create spectral detail absent from the input and only enlarges the file, so
  the pipelines do not do it.
- An output path cannot overwrite an input file. Press `Ctrl+C` to cancel a CLI task.
- Synthetic tests only indicate that the implementation has no obvious regression. Judge final
  quality by listening to the same excerpt before and after processing.

## Technical Documentation

Architecture, algorithms, testing, and release information are available in
[the technical documentation](docs/en/README.md):

- [Architecture and Data Flow](docs/en/architecture.md)
- [Reference Cancellation](docs/en/reference-removal.md)
- [Full Stage Processing](docs/en/full-stage.md)
- [Browser Build (WebAssembly)](docs/en/web.md)
- [Contributing](docs/en/CONTRIBUTING.md)

## Acknowledgements and License

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor): inspiration for frequency-domain
  vocal extraction.
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui): neural
  separation for when no song source exists.

This project is released under [AGPL-3.0-or-later](LICENSE). The open-source edition of
PySide6-Fluent-Widgets uses GPLv3; confirm its upstream license before commercial use.
