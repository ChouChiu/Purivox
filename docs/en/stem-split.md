# Acoustic Stem Split

<p align="left">
  <a href="../stem-split.md">简体中文</a> · <strong>English</strong>
</p>

## Scope and Applicable Scenarios

Acoustic Stem Split is Purivox's reference-free audio decomposition workflow, accessible via `run_stem_split_job(job, token, progress)` and exposed through both the GUI Stem page and the `purivox split` CLI subcommand.

### Technical Boundaries and Deep Learning Comparison

Acoustic stem splitting relies strictly on physical inter-channel spatial relationships and classical frequency-domain DSP (matrix algebra and linear filtering) without neural networks:

- **Applicable Scenarios**: Ideal for surround master discrete channel extraction, stereo panning analysis, M/S encoding, and mastering workflows where stems must sum back to the original waveform with mathematical exactness. It is lightweight, fast, free of neural synthesis artifacts, and requires minimal computational resources.
- **Physical Limitations**: The split is a **physical and spatial decomposition**, not a **semantic source separation**. It cannot differentiate distinct instruments that share the exact same spatial pan and frequency bands. In a stereo mix, centered solo instruments (e.g., saxophone, guitar leads), direct snare drum hits, and upper harmonics of centered kick drums will be extracted into the center stem alongside the lead vocal. Conversely, wide stereo reverb tails, stereo choruses, and hard-panned backing vocals remain in the accompaniment stem. For semantic blind source separation (isolating drums, bass, vocals, and instruments regardless of panning), dedicated deep learning tools are recommended.

### Adaptive Layout Dispatch

Stem splitting adapts strictly to the physical channel count of the input audio:

| Channel Count | Processing Path | Generated Stems |
|---|---|---|
| $\ge 6$ (Surround) | Discrete channel demux & leakage regression (`_surround_stems`) | 8 |
| 2 (Stereo) | Panning-adaptive center extraction & crossover (`_stereo_stems`) | 6 |
| 1 (Mono) | All-pass complementary crossover (`_mono_stems`) | 3 |

Audio with 3 to 5 channels lacks standard downmix matrices and is handled by slicing the first two channels (FL/FR) as stereo input; remaining channels are excluded.

## Stem Output Specifications

Output files follow the `<filename>_<marker>.wav` naming pattern, where markers are standardized English identifiers:

### Stereo (6 Stems)

| Marker | Channels | Definition & Content |
|---|---|---|
| `center` | Mono | Adaptive panning-extracted center: lead vocal and centered instruments |
| `instrumental` | Stereo | Stereo accompaniment with center components extracted (including wide instruments and stereo reverb) |
| `side` | Mono | M/S matrix side component: $(L - R) / 2$ |
| `mid` | Mono | M/S matrix mid component: $(L + R) / 2$ |
| `low` | Stereo | 4th-order Linkwitz-Riley low-pass output (below crossover frequency) |
| `high` | Stereo | Complementary high-pass output: $x - \text{low}$ |

### Surround (8 Stems)

Outputs `surround` (SL/SR), `center` (FC), `lfe`, `front` (FL/FR), `front_no_center` (front pair with center leakage removed), `downmix` (ITU-R BS.775 stereo downmix), and complementary `low` and `high` stems derived from the downmix.

### Mono (3 Stems)

Outputs three complementary band stems (`low`, `mid_band`, and `high`) that reconstruct the input signal exactly when summed.

## Complementary Crossover Formulation and Trade-Offs

The crossover network uses a complementary, distortionless reconstruction design:
- Low-frequency signals pass through a 4th-order Linkwitz-Riley filter (two cascaded 2nd-order Butterworth low-pass stages, `STAGE_ORDER = 2`);
- High-frequency signals are formed by subtracting the low-pass output from the original input: $\text{high} = x - \text{low}$.

### Advantages and Technical Costs

- **Advantages**: The subtraction identity $\text{low} + \text{high} \equiv x$ guarantees bit-exact time-domain reconstruction when summed, eliminating crossover region magnitude dips and phase cancellation common to independent filter pairs.
- **Costs and Trade-offs**: The low-pass filter introduces frequency-dependent group delay and phase rotation. High-pass stems inherit the complementary phase response and are not strictly linear-phase. Zero-phase filtering (`sosfiltfilt`) was avoided because bidirectional filtering requires non-causal forward-backward passes, preventing streaming block processing with simple initial state (`zi`) propagation. The architecture prioritizes exact waveform reconstruction and constant-memory streaming over linear phase on isolated band stems.

## Panning-Adaptive Center Extraction

Stereo center extraction analyzes inter-channel time-frequency correlation and energy distribution. For each bin $(f, t)$, smoothed auto- and cross-power spectral densities define:

$$
\psi = \frac{2\,|\Phi_{LR}|}{\Phi_{LL} + \Phi_{RR}},\qquad
\tau = \frac{\Phi_{LL} - \Phi_{RR}}{\Phi_{LL} + \Phi_{RR}}
$$

Where $\psi \in [0, 1]$ measures normalized inter-channel coherence, and $\tau \in [-1, 1]$ represents the normalized stereo panning position ($\tau = 0$ corresponds to dead center).

The center extraction mask $w(f, t)$ is defined as:

$$
w = \frac{2\psi}{1 + \psi} \cdot \exp\!\left(-\frac{1}{2}\left|\frac{\tau}{\sigma_{\text{pan}}}\right|^{p}\right) \cdot g(f)
$$

1. **Coherence Gain Term**: $\frac{2\psi}{1 + \psi}$ adjusts for uncorrelated noise distribution in sum signal $M = (L+R)/2$, improving center energy extraction under diffuse acoustic fields;
2. **Generalized Gaussian Panning Window**: Parameterized by $\sigma_{\text{pan}} = 0.40$ (`PAN_WIDTH`) and order $p = 8$ (`PAN_ORDER`). The super-Gaussian window exhibits flat passband behavior with steep roll-offs, accommodating natural vocal position drifts ($\pm 15\%$) while rejecting hard-panned instruments;
3. **Bass Protection**: The frequency weighting $g(f)$ remains $0$ below $100\text{ Hz}$ (`BASS_PROTECT_HZ`) and transitions linearly to $1$ at $200\text{ Hz}$ (`BASS_PROTECT_EDGE_HZ`), preventing centered kick drum and bass fundamentals from being routed to the center stem. Note that while fundamental frequencies are preserved in the accompaniment, upper transients and click attacks of kick drums remain in the center extraction bandwidth.

Center and instrumental tracks are formed via complex subtraction:

$$
\text{center} = w\,M,\qquad
\text{instrumental}_{L} = L - w\,t_{L}\,M,\qquad
\text{instrumental}_{R} = R - w\,t_{R}\,M
$$

Where $t_L, t_R$ are energy-proportional weighting factors ensuring that each channel subtracts only its respective share of the center image.

Long recordings are chunked into $\approx 45\text{ s}$ blocks with $\ge 2\text{ s}$ overlap, blended using $\cos^2/\sin^2$ crossfades.

## Front-Channel Center Leakage Cancellation

In surround mixes, front channels (FL/FR) frequently contain acoustic or mixing leakage from the discrete center channel (FC). The engine estimates complex, frequency-dependent transfer coefficients $\alpha(f)$ across the recording:

$$
\alpha_L(f) = \frac{\sum_t F_L \overline{F_C}}{\sum_t |F_C|^2 + \lambda \max_f \sum_t |F_C|^2}
$$

A relative floor $\lambda = 10^{-6}$ (`TRANSFER_FLOOR`) scales against the peak spectral energy across all bins, preventing division instability.

- **Absence of Coherence Gating**: Front channels carry substantial independent stereo arrangement energy. Even when center leakage is perfectly coherent, normalized cross-power coherence is diluted by the front channels' independent power. Gating on coherence would fail to cancel leakage at bins crowded with accompaniment.
- **Time-Invariance Assumption**: Estimating a single complex scalar per bin assumes linear time-invariant (LTI) acoustic leakage. If a surround mix incorporates dynamic automated panning across the timeline, stationary transfer estimates cannot track time-varying trajectories.

## Grouped Gain Scaling and Clipping Protection

To maintain additive reconstruction equivalence, stems that sum to a parent signal share a single normalization scalar (`fit_group()`):

1. **Grouped Stems**: `center` and `instrumental`, complementary band stems (`low` and `high`), mono 3-band stems, and surround `downmix` along with its derived band stems.
2. **Group Normalization**: Stems are evaluated together after rendering. If the group maximum peak exceeds $1.0$, all stems in the group scale down uniformly; otherwise, native levels are preserved. This prevents independent normalization from altering relative inter-stem balances.
3. **Discrete Stems**: Independent channels (surround, LFE, side) export at native levels, guarded by clipping warnings in `export_audio()`.
4. **Surround Downmix Scaling**: Because ITU-R BS.775 downmixing can yield peak amplitudes up to $2.41\times$, a custom `downmix_gain()` is evaluated prior to group scaling.

## Evaluation Metrics and Limitations

Stem separation performance is monitored using reproducible synthetic evaluation scripts (`tools/eval_stems.py`):

```bash
uv run --locked python tools/eval_stems.py --save baseline.json
uv run --locked python tools/eval_stems.py --compare baseline.json
```

Core metrics include:
- `lead_removed_db`: Level reduction of the lead vocal in the instrumental track (more negative is better);
- `lead_kept_db`: Retention of the lead vocal in the center stem (close to $0\text{ dB}$ is optimal);
- `arrangement_kept_db` / `bass_kept_db`: Preservation of backing instruments and low frequencies in the accompaniment;
- `centre_leak_db`: Suppression depth of center channel bleed in front channels;
- `band_rmse`: Root-mean-square reconstruction error of complementary crossover summing.

Synthetic metrics measure projections against known signals to prevent algorithmic regressions; they should not be taken as absolute guarantees of quality on commercial multi-track releases.
