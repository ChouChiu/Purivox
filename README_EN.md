# Purivox

<p align="left">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

**[▶ Use it in your browser](https://purivox.wwchun.top/)** - nothing to install, and the audio never leaves your own
tab.

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

The project also includes a separate **AI Track Separation** tool. It uses UVR MDX-Net ONNX
models to predict vocal and background tracks from ordinary audio. AI separation does not use a
song source and does not perform MR Remove's source matching, alignment, or source-guided removal.
The two tools have different goals and output meanings: AI separation is not a substitute for
Vocal Isolation, and their results should not be compared directly.

## Features

- Fluent Design desktop interface with light, dark, and system themes
- Instant switching among Chinese, English, Japanese, and Korean interfaces
- Global time alignment, local clock-drift tracking, and coherent reference cancellation
- Song identification, repeated-segment detection, and editable processing ranges for full-stage
  recordings
- Four optional MDX-Net separation models, downloaded on demand and verified with SHA-256
- Chunked long-audio processing, task cancellation, and atomic output writes
- Exports keep the input file's sample rate and bit depth, never upsampled to hit a format
- In-app result preview and audio statistics
- The settings page checks for new releases: an update opens one dialog with its changelog and a link to the release page — nothing updates itself
- The common actions have shortcuts: `Ctrl+O` to choose an input, `Ctrl+Return` to start, `F5` to identify songs, `Esc` to cancel, `Ctrl+P` to play/pause the preview
- GUI and CLI reuse the corresponding MR Remove and AI separation task pipelines

## Installation

If you would rather not install anything, the [browser build](https://purivox.wwchun.top/) runs the same pipelines. It
leaves out AI track separation, whose ONNX runtime has no WebAssembly build, and a long enough
stage recording is refused because a browser tab has a memory ceiling. See
[Browser Build (WebAssembly)](docs/en/web.md) for the details.

For the desktop application, [uv](https://docs.astral.sh/uv/) is required. The project uses `.python-version` to select Python
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
4. Preview the result before adjusting the strength. If you hear obvious pumping or thinning of
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
5. Confirm the output location and processing options, then process the full recording.

Unidentified ranges retain their original content and duration. Inter-song speech, audience
interaction, advertisements, and empty-stage audio are not removed automatically. Full-stage
processing is currently available only in the graphical interface.

### Separate Tool: AI Track Separation

AI Track Separation is intended for ordinary two-track separation. It does not use a song source
and is not a fallback mode for MR Remove.

1. Open **AI Track Separation**, then select the input audio and a model.
2. Click **Start Separation**.
3. When a model is used for the first time, the application downloads its weights automatically.
   Keep the network connected until verification finishes.

The tool creates:

- `<song-name>_vocal.wav`: vocals predicted by the model
- `<song-name>_background.wav`: the original mix minus the predicted vocals

## Command-Line Usage

Display the version and help:

```bash
uv run --locked purivox --version
uv run --locked purivox --help
uv run --locked purivox mr --help
uv run --locked purivox ai --help
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
| `--lang` | `zh_cn`, `en_us`, `ja_jp`, `ko_kr` | Language used for progress messages |

Run the AI separation tool independently:

```bash
uv run --locked purivox ai "song.wav" --output-dir "output" --model mdxnet_1
```

Available models are `mdxnet_1`, `mdxnet_main`, `kim_vocal`, and `kuielab_b`. Use `--models-dir`
to specify a weights directory, or set the `PURIVOX_MODELS` environment variable for a shared
model directory.

## Input, Output, and Important Notes

- libsndfile natively supports formats including WAV, FLAC, and OGG. Other formats supported by
  the system decoder are read through Qt Multimedia when possible.
- MR Remove and Full Stage process at the stage/live audio's original sample rate throughout, and
  export at that same rate.
- The separate AI tool still performs model inference at 44.1 kHz, then resamples back to the
  song's own rate before writing stereo WAV files. These outputs are not equivalent to an MR
  Remove result.
- Every exported PCM WAV keeps the input file's sample rate and bit depth: an 8- or 16-bit PCM
  input is written at 16 bits, and wider 24-/32-bit PCM, float and every lossy format at 24.
  Upsampling cannot create spectral detail absent from the input or model and only enlarges the
  file, so the pipelines do not do it.
- An output path cannot overwrite an input file. Press `Ctrl+C` to cancel a CLI task.
- Model weights are not included in the Python package or standalone application.
- Synthetic tests only indicate that the implementation has no obvious regression. Judge final
  quality by listening to the same excerpt before and after processing.

## Technical Documentation

Architecture, algorithms, testing, and release information are available in
[the technical documentation](docs/en/README.md):

- [Architecture and Data Flow](docs/en/architecture.md)
- [Reference-Guided Vocal Isolation](docs/en/reference-removal.md)
- [Full Stage Processing](docs/en/full-stage.md)
- [AI Track Separation](docs/en/neural-separation.md)
- [Browser Build (WebAssembly)](docs/en/web.md)
- [Development, Testing, and Release](docs/en/development.md)

## Acknowledgements and License

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor): inspiration for frequency-domain
  vocal extraction.
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui): its MDX-Net
  pipeline informed the AI processing workflow.
- [TRvlvr/model_repo](https://github.com/TRvlvr/model_repo): provides the MDX-Net model files;
  refer to each release page for its license and attribution requirements.

This project is released under [AGPL-3.0-or-later](LICENSE). The open-source edition of
PySide6-Fluent-Widgets uses GPLv3; confirm its upstream license before commercial use.
