# Stem Split

<p align="left">
  <a href="../stem-split.md">简体中文</a> · <strong>English</strong>
</p>

## Goals and Boundaries

This is the project's second workflow, and the only one that needs no song source: give it one
audio file and it separates that file into stems along the relationships between its channels. The
entry point is `run_stem_split_job(job, token, progress)`, which the GUI's stem page and
`purivox split` both call.

What it does not do: there is no reference here, no matching and no timeline. Removing the backing
track from a live recording is the pipeline in [reference cancellation](reference-removal.md) and
[source matching](matching.md), not this one. There is no neural network either — this pipeline is
matrices and filters, for the same reason neural separation was removed: 58 MB of runtime is not
worth carrying for a workflow that needs no model.

**The channel count decides which stems come out**, because the channel count is what decides what
can honestly be separated: a surround master carries its centre channel, a stereo master only
implies one.

| Channels | Path | Stems |
|---|---|---|
| ≥ 6 | discrete decode (`_surround_stems`) | 8 |
| 2 (3–5 folded to the front pair) | panning-adaptive + complementary crossover (`_stereo_stems`) | 6 |
| 1 | complementary crossover (`_mono_stems`) | 3 |

Three to five channels is a layout with no decode matrix here, so it is folded to its first two
channels and split as stereo rather than guessed at.

Whether six channels actually arrive depends on the decoder: containers libsndfile can open (WAV,
FLAC) hand over every channel as it is; a compressed container that falls through to the Qt
Multimedia decoder in `shared/audio/io.py` gets whatever Qt's backend gives it. The project adds no
extra decoding dependency for this.

## The Stems

Files are named `<recording name>_<marker>.wav`. Markers stay English in every locale — a file that
renamed itself with the interface language would become a different file on the next switch.

**Stereo (6 stems)**

| marker | Channels | Content |
|---|---|---|
| `center` | mono | panning-adaptive centre: the lead and centred instruments |
| `instrumental` | stereo | the mix with the centre taken out |
| `side` | mono | M/S side, $(L-R)/2$ |
| `mid` | mono | M/S mid, $(L+R)/2$ |
| `low` | stereo | LR4 low-pass, below the crossover |
| `high` | stereo | complementary high-pass, $x - \text{low}$ |

**Surround (8 stems)**: `surround` (SL+SR), `center` (FC), `lfe`, `front` (FL/FR),
`front_no_center`, `downmix` (ITU-R BS.775 fold-down), `low` and `high`, the last two taken from
the fold-down.

**Mono (3 stems)**: `low`, `mid_band` and `high`, which add back up to the recording exactly.

## The Complementary Crossover

The low-pass is a Linkwitz-Riley (two cascaded second-order Butterworth sections, `STAGE_ORDER =
2`), and **the high band is not a second filter but $x - \text{low}$**.

That is not a shortcut, it is the only way the two band stems add back up. An independent
Butterworth low-pass beside an independent Butterworth high-pass leaves both a magnitude dip and a
phase error around the corner, and the two do not sum to what they were split from. A difference
cannot have that problem.

The price is that the high band carries the complementary phase, and the low band carries the shift
a single forward `sosfilt` pass introduces. Zero-phase `sosfiltfilt` was not used because it means
walking a mapped recording backwards a second time; on a long recording that costs more than exact
reconstruction is worth giving up.

The filtering runs in blocks with the `zi` state carried across `BLOCK_FRAMES`, so the result is
identical to filtering the whole file in one call — which is what
`tests/features/stem_split/test_crossover.py` holds it to.

## Panning-Adaptive Separation

A stereo master has no centre channel, only a relationship between two channels. Per spectral cell
$(f, t)$, after smoothing the short-time auto- and cross-spectra over time:

$$\psi = \frac{2\,|\Phi_{LR}|}{\Phi_{LL} + \Phi_{RR}},\qquad
\tau = \frac{\Phi_{LL} - \Phi_{RR}}{\Phi_{LL} + \Phi_{RR}}$$

$\psi$ is how alike the two channels are in that cell — one panned source scores near 1, a reverb
tail or a cymbal wash near 0 — and $\tau$ is where between them it sits, 0 being centred. The
centre weight is their product:

$$w = \psi \cdot \exp\!\left(-\frac{\tau^2}{2\sigma_{\text{pan}}^2}\right) \cdot g(f)$$

$\sigma_{\text{pan}} = 0.25$ (`PAN_WIDTH`) is the tolerance for "still centred": a lead that sits
slightly off centre, or is doubled, stays inside it; a hard-panned guitar does not.

$g(f)$ is the bass protection (`BASS_PROTECT_HZ = 100`, rising to 1 by `BASS_PROTECT_EDGE_HZ =
200`). The kick and the bass are centred by convention, not because they are the lead, and taking
them out with the lead is the complaint every phase-cancellation karaoke track attracts. The band
is kept narrow because a male lead's fundamental sits just above it: protecting further up would
leave part of the voice in the instrumental.

Two stems follow:

$$\text{center} = w\,M, \qquad
\text{instrumental}_{L} = L - w\,t_{L}\,M, \qquad
\text{instrumental}_{R} = R - w\,t_{R}\,M$$

where $M = (L+R)/2$ and $t_{L}, t_{R}$ are the shares each channel carries, from
$\sqrt{\Phi_{LL}}$ and $\sqrt{\Phi_{RR}}$ normalised by their mean. With $t$, an off-centre source
has the amount **its own panning puts in each channel** taken out of that channel, instead of half
of it taken out of both. Putting the centre stem back at the panning the estimate measured returns
the mix, so the two are still a decomposition.

The subtraction happens in the complex domain rather than as a level attenuation, so the phase
comes out with it.

A long recording runs in blocks of about 45 seconds overlapping by at least 2, crossfaded
$\cos^2/\sin^2$ between them. The spectrogram of a whole song is a hundred times the audio it
describes, and the browser build's memory ceiling applies to the same pipeline.

## Front Minus Centre, One Complex Ratio Per Bin

On a surround master the centre channel leaks into the front pair. Atome fits one real $\alpha$
over the whole recording by orthogonal projection; what a mastering chain actually leaves there is
a filter — delayed, shelved, different at every frequency — and a scalar cannot cancel it.

This takes two passes. The first accumulates $\sum F_L \overline{F_C}$ and $\sum |F_C|^2$ per bin,
which gives a **complex** $\alpha_L(f)$ over the whole recording; bins whose coherence
$|\Phi_{LC}|^2 / (\Phi_{LL}\Phi_{CC})$ falls below `COHERENCE_FLOOR` are set to zero, so content a
front channel does not share with the centre is left alone. The second pass writes
$\text{istft}(F_L - \alpha_L(f) F_C)$.

The estimate covers the whole recording rather than following it frame by frame: the leak from FC
into the front pair of a master is essentially static, and a whole-file estimate is the steadier
one.

## Level and Clipping

**Stems that add back up to one signal share one gain; everything else is written at unity.**

Atome normalises every stem to 0.999 on its own, which is the one thing that makes a set of stems
stop being a decomposition: each file comes back at a level of its own and adding them no longer
returns the mix. The rule here is `fit_group()`: a group is rendered in full first, the largest
peak in it is measured, and either the whole group is scaled by one factor or none of it is.

The groups are `center` with `instrumental`, the two band stems, the three mono band stems, and the
surround `downmix` with its two band stems. A stem that is nobody's summand — the discrete
channels, `side`, `mid`, `front_no_center` — is written at unity: the discrete channels and the M/S
components are bounded by the peak they came from and cannot pass it, and if one ever does, the
clipping warning already in `export_audio()` is behind it.

The surround fold-down has one more layer: summing three channels under ITU-R BS.775 can reach 2.41
times full scale, so `downmix_gain()` derives a factor from the measured per-channel peaks first,
and the grouping rule above applies on top of it.

## Measurement

Stem quality is measured with `tools/eval_stems.py`, used exactly like `eval_cancellation.py`:

```bash
uv run --locked python tools/eval_stems.py --save baseline.json
uv run --locked python tools/eval_stems.py --compare baseline.json
```

The scenes are synthetic and every part that went into them is known, so "the lead is so many
decibels down in the instrumental" is a projection onto a known signal rather than an impression of
the result. The metrics are `lead_removed_db` (how far the lead moved from the level it was mixed
in at, in the instrumental — more negative is better), `lead_kept_db` (what the centre stem kept of
it), `arrangement_kept_db` and `bass_kept_db` (what the instrumental kept, where closer to 0 is
better), `centre_leak_db` (the front-minus-centre suppression) and `band_rmse` (the band stems'
reconstruction error).

Synthetic metrics only find regressions. They do not claim real-music quality.
