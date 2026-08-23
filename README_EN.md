# Audio Station

<p align="center">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

Audio Station is a desktop vocal isolation tool for stage and live recordings, built with
Python, PySide6, and PySide6-Fluent-Widgets. Its core MR Remove feature provides two workflows:

- **Single**: provide a stage/live recording and the corresponding song source. Audio Station
  automatically synchronizes them and isolates the live vocals.
- **Full Stage**: provide a continuous stage/live recording and multiple song sources. Audio
  Station identifies where each song occurs and isolates the live vocals in each matched segment.

Vocal Isolation only removes content that can be explained by the song source. It is therefore
designed to preserve live vocals, speech, cheering, and ambient sound that are absent from that
source. Accurate song sources are essential: clipping, heavy reverberation, different
arrangements, or an incorrect source can all reduce the quality of the result.

The project also includes a separate **AI Track Separation** tool. It uses UVR MDX-Net ONNX
models to predict vocal and background tracks from ordinary audio. AI separation does not use a
song source and does not perform MR Remove's source matching, alignment, or source-guided removal.
The two tools have different goals and output meanings: AI separation is not a substitute for
Vocal Isolation, and their results should not be compared directly.

## Features

- Fluent Design desktop interface with light, dark, and system themes
- Instant switching among Chinese, English, Japanese, and Korean interfaces
- Global time alignment, local clock-drift tracking, and reference-mask cancellation
- Optional **Emphasize live vocals** and **Protect quiet live vocals** processing
- Song identification, repeated-segment detection, and editable processing ranges for full-stage
  recordings
- Four optional MDX-Net separation models, downloaded on demand and verified with SHA-256
- Chunked long-audio processing, task cancellation, and atomic output writes
- In-app result preview and audio statistics
- GUI and CLI reuse the corresponding MR Remove and AI separation task pipelines

## Installation

[uv](https://docs.astral.sh/uv/) is required. The project uses `.python-version` to select Python
automatically and manages an isolated environment inside the repository. Do not install another
Qt Fluent component that exports `qfluentwidgets` into this environment.

```bash
uv sync --locked
```

Start the graphical interface:

```bash
uv run --locked audio-station
```

You can also start it from the source entry point:

```bash
uv run --locked python -m entrypoints
```

## Using the Graphical Interface

### Single

1. Open **Vocal Isolation** and select **Single**.
2. Select the stage/live audio to process and the corresponding song source.
3. Alignment runs automatically. Start with the default removal strength of 75%; the graphical
   interface uses a fixed statistical context.
4. Preview the result before adjusting the strength. If you hear obvious pumping or thinning of
   the live vocal, reduce the strength or confirm that the song source is correct.
5. **Emphasize live vocals** and **Protect quiet live vocals** are optional. The latter is
   available only when vocal emphasis is enabled.

Use a song source that matches the version played at the venue as closely as possible. Different
masters, edits, speeds, keys, or extra content will reduce removal quality.

### Full Stage

1. Select **Full Stage** under **Vocal Isolation**, then load the continuous stage/live
   recording.
2. Add song sources that may occur in the recording. Their file order does not affect matching.
3. Click **Find songs**, then inspect complete songs, short segments, unidentified ranges,
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
uv run --locked audio-station --version
uv run --locked audio-station --help
uv run --locked audio-station mr --help
uv run --locked audio-station ai --help
```

Run reference cancellation with the default settings:

```bash
uv run --locked audio-station mr "live-recording.wav" "song-source.wav" "live-vocal.wav"
```

The CLI also lets you set the removal strength and statistical window, or enable center-focused
processing:

```bash
uv run --locked audio-station mr "live-recording.wav" "song-source.wav" "live-vocal.wav" \
  --strength 75 --sigma 8 --align \
  --center-extraction --weak-vocal-protection
```

Common reference-cancellation options:

| Option | Value | Description |
|---|---:|---|
| `--strength` | `0`–`100` | Vocal isolation strength; default: `75` |
| `--sigma` | `1`, `3`, `8`, `16` | Advanced statistical window in seconds; default: `3`; the GUI always uses `3` |
| `--align` / `--no-align` | on / off | Automatic alignment; enabled by default |
| `--center-extraction` | flag | Further emphasize vocals located at the center of the stereo image |
| `--weak-vocal-protection` | flag | Reduce attenuation of weaker vocals; requires center-focused processing |
| `--lang` | `zh_cn`, `en_us`, `ja_jp`, `ko_kr` | Language used for progress messages |

Run the AI separation tool independently:

```bash
uv run --locked audio-station ai "song.wav" --output-dir "output" --model mdxnet_1
```

Available models are `mdxnet_1`, `mdxnet_main`, `kim_vocal`, and `kuielab_b`. Use `--models-dir`
to specify a weights directory, or set the `MR_REMOVER_MODELS` environment variable for a shared
model directory.

## Input, Output, and Important Notes

- libsndfile natively supports formats including WAV, FLAC, and OGG. Other formats supported by
  the system decoder are read through Qt Multimedia when possible.
- MR Remove writes a 24-bit WAV at the sample rate of the stage/live audio.
- The separate AI tool always writes 44.1 kHz, 16-bit stereo WAV files. These outputs are not
  equivalent to an MR Remove result.
- An output path cannot overwrite an input file. Press `Ctrl+C` to cancel a CLI task.
- Model weights are not included in the Python package or standalone application.
- Synthetic tests only indicate that the implementation has no obvious regression. Judge final
  quality by listening to the same excerpt before and after processing.

## Technical Documentation

Architecture, algorithms, testing, and release information are available in [docs/](docs/README.md).
The technical documentation is currently written in Chinese:

- [Architecture and Data Flow](docs/architecture.md)
- [Reference Cancellation](docs/reference-removal.md)
- [Full-Stage Processing](docs/full-stage.md)
- [AI Vocal Separation](docs/neural-separation.md)
- [Development, Testing, and Release](docs/development.md)

## Acknowledgements and License

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor): inspiration for frequency-domain
  vocal extraction.
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui): its MDX-Net
  pipeline informed the AI processing workflow.
- [TRvlvr/model_repo](https://github.com/TRvlvr/model_repo): provides the MDX-Net model files;
  refer to each release page for its license and attribution requirements.

This project is released under [AGPL-3.0-or-later](LICENSE). The open-source edition of
PySide6-Fluent-Widgets uses GPLv3; confirm its upstream license before commercial use.
