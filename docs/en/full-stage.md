# Full Stage Processing

<p align="left">
  <a href="../full-stage.md">简体中文</a> · <strong>English</strong>
</p>

## Goals and Boundaries

Full Stage automatically places multiple song sources within one continuous stage
recording, then applies reference cancellation only to matched ranges. Sources do not need to be
ordered in advance. A source that briefly repeats in an intro, advertisement, or outro can also
produce additional fragments.

Automatic analysis does not modify audio directly. It first generates an editable timeline and
renders only after user confirmation; unmatched ranges are always copied from the original full
recording.

```mermaid
flowchart TB
    stage["Full Stage recording"] --> feature["Extract multi-band onset features"]
    sources["Song sources"] --> speed["Per-source tempo estimate"]
    speed --> stretch["Pitch-preserving WSOLA stretch"]
    stretch --> feature
    feature --> match["Normalized cross-correlation<br/>and candidate clustering"]
    match --> song["Full songs"]
    match --> fragment["Repeated short fragments"]
    match --> unmatched["Unmatched ranges"]
    song --> timeline["Editable timeline"]
    fragment --> timeline
    unmatched --> timeline
    manual["Hand-entered segments"] --> timeline
    timeline --> review["Manual review and correction"]
    review --> render{"Entry enabled and matched?"}
    render -->|yes| rescale["Stretch the source slice<br/>by the entry's tempo"]
    rescale --> cancel["Local alignment<br/>and reference cancellation"]
    render -->|no| original["Preserve original recording"]
    cancel --> blend["Boundary fade up to 50 ms"]
    original --> output["Assemble Full Stage output"]
    blend --> output
```

## Global Tempo

A full recording may have been re-uploaded with its tempo shifted as a whole: the pitch stays put and
the speed moves by a few percent. The anchor search slides a fixed-width window, so a source at a
different tempo lines up nowhere - measured on real material, two songs were matched to each other's
positions. Every source therefore gets one global scale search before matching: its onset features
are linearly interpolated along time at each trial ratio and normalized-correlated against the whole
stage proxy with the same spectral-flux features, taking the peak over every lag, scanning 0.88 to
1.15 in 0.004 steps and refining around the peak in 0.0005 steps.

An estimate is accepted only when its peak scores at least 0.25, beats the best ratio outside its own
neighbourhood by 10%, beats the ratio-one score by 0.04, and moves the tempo by at least 0.2%. The
last condition keeps material that is already aligned on its existing path. The estimator and the
stretch both live in `shared/dsp/rate.py` and `shared/dsp/stretch.py`, shared by Full Stage and
single-song MR.

An accepted ratio stretches the source proxy with WSOLA before the existing anchor search runs, so
the matcher itself is unchanged. The ratio travels with the timeline entry, and rendering stretches
the source slice by it - the source range in the timeline always stays on the source file's own
clock.

## Feature Extraction

The full recording and every source are first converted to 4 kHz mono proxy signals. A short-time
Fourier transform is then calculated with a frame step of approximately 40 ms. Magnitudes are
compressed with `log1p`, positive spectral flux is retained, and the result is aggregated into 12
geometrically spaced frequency bands.

Each band has its median removed, is normalized by median absolute magnitude, and is clipped to
$[-8,8]$. Matching therefore focuses on onset changes rather than mastering loudness.

The feature itself lives in `shared.dsp.log_flux_bands()`. Coarse alignment in reference removal
needs the same onset description and the two feature packages must not import each other, so the
band layout, normalization and clipping exist once; full-stage matching and coarse alignment differ
only in window length and rejection threshold.

## Full-Song Candidates

Each source contributes up to seven distributed anchors. Anchor duration adapts to source length
within a range of approximately 6–20 seconds. Every anchor is matched against the Full Stage
features using normalized cross-correlation:

$$
s(k)=\frac{\langle \mathbf S_k,\mathbf Q\rangle}
{\|\mathbf S_k\|_2\,\|\mathbf Q\|_2+\varepsilon}
$$

An anchor hit is converted to the predicted Full Stage position of source time zero. Hits within
0.8 seconds are grouped into one candidate; votes from distinct anchors and their average score
together form the confidence. A candidate needs support from multiple anchors or a sufficiently
high individual score.

After all sources are searched independently, candidates are sorted by votes and confidence. At
most one full-song position is selected for each source, and a candidate overlapping an
already selected song by more than two seconds is rejected. The final timeline is ordered by
stage start time.

## Repeated Short Fragments

To identify short quotations in intros, outros, or advertisements, the algorithm additionally
scans each source with a ten-second window and five-second step, paying particular attention to
approximately the first and last 75 seconds of the full recording. In addition to the multi-anchor
and confidence thresholds, a candidate is verified by secondary cross-correlation over the first
difference of the 4 kHz waveforms.

A short fragment must be at least approximately five seconds long and must not overlap a detected
full song or another fragment substantially. The user can decide whether to include these
fragments before rendering.

## Timeline Model

Timeline entries have these kinds:

| Kind | Meaning | Default processing |
|---|---|---|
| Full song | The primary full-length match for a source | Reference cancellation enabled |
| Short fragment | A local reuse of the same source | User-selectable |
| Unmatched | A gap without reliable source coverage | Preserve original audio |
| Manual | A segment the user entered; the confidence column reads "Manual" | Treated as a full song |

Each matched entry records the stage start/end times, source file, source start/end times, tempo,
confidence, and enabled state. The model rejects negative times, zero-length ranges, matched
entries without a source, and out-of-range confidence.

The tempo column shows the factor the entry's source is stretched by (stage duration divided by
source duration), and reads "-" when no correction was applied. It is read-only: the analysis
measured it, and editing it would have to recompute the source range too, so a wrong estimate is
skipped by unchecking the entry instead. Manual entries are fixed at 1; process a spliced backing
track through single-song mode to correct its speed first.

After detected occupied ranges are merged, any gap of at least 0.25 seconds produces an unmatched
entry. Sources that were not detected are listed separately for manual review.

The interface presents this table through Qt's model/view classes: `TimelineModel`
(a `QAbstractTableModel` in `features/full_stage/timeline_model.py`) treats the analysis as its
single source of truth, and `TableView` only displays it. Cell text, alignment, check state, and
editability come from `data()` and `flags()`; user edits are parsed and validated in `setData()`
before they reach the analysis, and an invalid entry returns `False` and emits `edit_rejected`, so
the view restores the previous value on its own. There is no whole-table repaint and no code that
blocks signals raised by its own repainting; a language change simply makes the model emit
`dataChanged`.

### Manual Segments and Spliced Backing Tracks

The analysis places at most one full-song position per source, and the fragment scan is weighted
toward the first and last 75 seconds of the stage. A **spliced backing track** — the same song cut
into pieces and replayed in an order the performance calls for — is outside what that search can
reconstruct.

The timeline therefore accepts hand-entered rows through "Add segment". A new row lands at the
start of the first unidentified range, and the editable stage-time and source-range columns move
it to its real position. Manual segments are full songs rather than fragments: rendering gates
fragments behind a switch, and an entry the user typed in should not be silently skipped by it.
The confidence column reads "Manual" rather than inventing a detection score.

Only manual segments can be removed. Detected entries are skipped by clearing their checkbox and
stay in the list for review.

A spliced backing track can also be handled without the full-stage feature: cut the source into
the performance's order first, then run it through single mode as one continuous song. That
returns it to a single continuous alignment problem, but the splice points have to be accurate to
within tens of milliseconds — local delay tracking corrects at most 2 ms per 0.1 s, so a half
second of error takes about 25 seconds to recover from, and cancellation fails for that whole
time.

## Segmented Rendering

Rendering first creates a floating-point buffer with the same duration and sample rate as the full
recording and copies the original audio in full. It then processes each enabled full song and
optional short fragment:

1. Read the source and resample it to the Full Stage sample rate.
2. Slice the stage and source ranges specified by the timeline.
3. Stretch the source slice by the entry's tempo when it is not 1, preserving pitch.
4. Optionally perform local drift alignment.
5. Measure how well both the original timeline position and drift-aligned result explain the stage
   audio; use drift alignment only when the new result is no worse.
6. Process the segment with reference cancellation. Reconstruction uses only the original
   stage mix and never mixes the source waveform into the result.
7. Blend the result into the full-recording copy with fades of up to 50 ms at both boundaries.

After all segments are complete, the Full Stage result is written atomically as PCM WAV at the
stage recording's own sample rate and bit depth. Unmatched ranges are already a bit-exact copy of
the original, so raising the export to a fixed floor would only enlarge the file without adding
spectral detail absent from the original recording.

When the backing track is also requested, the stage recording less the render is written as a
second file once the vocal is on disk, subtracted in place. The render buffer started as a copy of
the stage and had each segment blended over it, so the difference is exactly what was cancelled:
across unmatched ranges the two are identical and the backing is silent there - nothing was
cancelled out of them. The 50 ms fades at the segment boundaries stay consistent too, with the
backing fading under the same weights.

Explanatory power is calculated by fitting small $2\times2$ direct models in multiple windows,
measuring their residual ratios, and taking the median, so that one abnormal window cannot
dominate the decision. This selection gate prevents an already correct timeline position from
being damaged by an unreliable local-delay trajectory.

## Failure Strategy

- Rendering is rejected when there are no usable matches, rather than producing an input-identical
  file that appears successful.
- An unreliable tempo estimate, too small an improvement, or a change below 0.2% is treated as 1:1,
  exactly as before the feature existed.
- The output cannot overwrite the full recording or any source, and the full recording cannot also
  be used as a song source.
- Temporary audio for each segment is cleaned immediately after processing; mapped storage keeps
  memory use under control for the full output.
- Disabled or unmatched ranges are never replaced with silence, removed from the timeline, or
  allowed to change the original duration.
