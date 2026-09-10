# Purivox

<p align="left">
  <a href="README.md">简体中文</a> · <strong>English</strong>
</p>

**[▶ Use it in your browser](https://purivox.wwchun.top/)** — nothing to install, and the audio
never leaves your own tab.

Purivox is a vocal isolation tool for stage and live recordings, available as a desktop
application and in the browser, built with Python, PySide6, and PySide6-Fluent-Widgets. Its core
MR Remove feature is one workflow: provide a stage/live recording and add its song sources.

- **One source**: Purivox aligns and cancels that song directly. When the source is as long as
  the recording, it corrects a speed difference between the two over the whole length; when it
  covers only part of the recording, it works at the position it matched.
- **Several sources**: Purivox first locates each song in the recording, then cancels the live
  vocals in each matched segment. File order does not affect matching.

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
- Global tempo detection with pitch-preserving stretching, time alignment, local clock-drift
  tracking, and coherent reference cancellation
- Song identification for several sources, repeated-segment detection, and editable processing
  ranges
- Chunked long-audio processing, task cancellation, and atomic output writes
- Exports keep the input file's sample rate and bit depth, never upsampled to hit a format
- In-app result preview and audio statistics
- The settings page checks for new releases: an update opens one dialog
  with its changelog and a link to the release page — nothing updates itself
- Every run appends to a log file named after the date; an unhandled exception opens
  that day's log and offers the issue form
- The common actions have shortcuts: `Ctrl+O` to choose an input, `Ctrl+Return` to
  start, `F5` to identify songs, `Esc` to cancel, `Ctrl+P` to play/pause the preview
- Song sources can be fetched straight from a YouTube / YouTube Music link, and what was
  downloaded is remembered so it can be picked again
- GUI and CLI reuse the same MR Remove task pipelines

## Installation

If you would rather not install anything, the [browser build](https://purivox.wwchun.top/)
runs the same pipelines. A long enough
recording is refused there because a browser tab has a memory ceiling. See
[Browser Build (WebAssembly)](docs/en/web.md) for the details.

The desktop application can be downloaded from the
[latest release](https://github.com/ChouChiu/Purivox/releases/latest): `Purivox.exe` on Windows,
a `.deb`, an `.rpm` or the self-contained `purivox-linux-x86_64.tar.gz` on Linux, and
`purivox-macos-arm64.tar.gz` (Apple Silicon) or `purivox-macos-x86_64.tar.gz` (Intel) on macOS.
Every release ships a `SHA256SUMS` alongside them.

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

### Vocal Isolation

1. Open **Vocal Isolation** and select the stage/live recording to process.
2. Add the song sources the recording may contain: one source cancels that song, several are
   located in the recording first, and file order does not affect matching.
3. With several sources, click **Find songs**, then inspect full songs, short segments,
   unidentified ranges, and match confidence.
4. If necessary, double-click to edit recording times or source ranges, or clear the checkbox for
   a segment that should not be processed.
5. Under **Export**, choose which stems to save: the vocal only, the backing track only, or
   both. The backing track is not subtracted from the recording; it is the song source re-rendered
   through the transfer the cancellation estimated, so it keeps the source's own quality while
   carrying the level and response the backing actually had on stage.
6. Confirm the output location and the processing options, then start. Preview the result before
   adjusting the strength. If you hear obvious pumping or thinning of the live vocal, reduce the
   strength or confirm that the song source is correct.

Use a song source that matches the version played at the venue as closely as possible. Different
masters, edits, speeds, keys, or extra content will reduce removal quality.

Unidentified ranges retain their original content and duration. Inter-song speech, audience
interaction, advertisements, and empty-stage audio are not removed automatically. The command line
accepts one song source; use the graphical interface or the browser build to process several at
once.

### Fetching a Source from a Link

The stage-recording row and the source list carry a **Fetch** button:

1. Paste a YouTube or YouTube Music link to download it directly, or type keywords to search
   YouTube and double-click a result. YouTube Music is link-only: its search does not answer
   with downloadable songs.
2. What has been downloaded is listed under **Downloaded**, and stays available for later jobs.
   A track is never fetched twice: a link in another shape — the `&list=…` YouTube adds on its
   own, say — is still recognised as the same track.
3. A link carrying a playlist yields the one track it points at, not the whole list.
4. Select an entry and press **Use selected** to put the file in the field that asked for it.
   The source list accepts more than one at a time.

With ffmpeg installed the download is converted to WAV; without it the original container is
kept — usually WebM/Opus — and Qt Multimedia decodes it, so the pipelines read either one.
Files live under `downloads` in the application data directory; the dialog can **Open folder**
to show them or **Delete** to remove an entry together with its file.

Only download material you have the right to use.

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
| `--lang` | `zh_cn`, `zh_tw`, `en_us`, `ja_jp`, `ko_kr` | Language used for progress messages |

Fetch a source from a link:

```bash
uv run --locked purivox fetch "https://www.youtube.com/watch?v=..."   # download it
uv run --locked purivox fetch "some keywords" --limit 5               # list search results only
uv run --locked purivox fetch "some keywords" --pick 2                # download the 2nd result
uv run --locked purivox fetch --list                                  # list what was downloaded
```

| Option | Value | Description |
|---|---:|---|
| `--out` | directory | Where to save; defaults to `downloads` in the application data directory |
| `--limit` | integer | How many search results to list; default: `10` |
| `--pick` | integer | Download this result, counting from 1; without it the results are only listed |
| `--list` | flag | List what has been downloaded |

On success the file path is printed to standard output, ready to hand to `purivox mr`.

## Input, Output, and Important Notes

- libsndfile natively supports formats including WAV, FLAC, and OGG. Other formats supported by
  the system decoder are read through Qt Multimedia when possible.
- MR Remove processes at the stage/live audio's original sample rate throughout, and
  exports at that same rate.
- Every exported PCM WAV keeps the input file's sample rate and bit depth: an 8- or 16-bit PCM
  input is written at 16 bits, and wider 24-/32-bit PCM, float and every lossy format at 24.
  Upsampling cannot create spectral detail absent from the input and only enlarges the file, so
  the pipelines do not do it.
- An output path cannot overwrite an input file. Press `Ctrl+C` to cancel a CLI task.
- Downloading is yt-dlp's job. When a site changes, update the dependency before investigating;
  a link is fetched once, and asking again returns the file that is already there.
- Synthetic tests only indicate that the implementation has no obvious regression. Judge final
  quality by listening to the same excerpt before and after processing.

## Technical Documentation

Architecture, algorithms, testing, and release information are available in
[the technical documentation](docs/en/README.md):

- [Architecture and Data Flow](docs/en/architecture.md)
- [Reference Cancellation](docs/en/reference-removal.md)
- [Source Matching, the Timeline, and Segmented Rendering](docs/en/matching.md)
- [Browser Build (WebAssembly)](docs/en/web.md)
- [Contributing](docs/en/CONTRIBUTING.md)

## Acknowledgements and License

- [Vocal-Extractor](https://github.com/IamYei/Vocal-Extractor): inspiration for frequency-domain
  vocal extraction.
- [Ultimate Vocal Remover GUI](https://github.com/Anjok07/ultimatevocalremovergui): neural
  separation for when no song source exists.

This project is released under [AGPL-3.0-or-later](LICENSE). The open-source edition of
PySide6-Fluent-Widgets uses GPLv3; confirm its upstream license before commercial use.
