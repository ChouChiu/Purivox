# AI Track Separation

<p align="center">
  <a href="../neural-separation.md">简体中文</a> · <strong>English</strong>
</p>

## Pipeline Overview

The AI workflow does not require a song source. The input is converted to stereo, resampled to
44.1 kHz, and passed to an MDX-Net ONNX model that predicts vocals:

$$
\widehat{\mathbf v}=f_{\theta}(\mathbf y)
$$

The background is calculated by direct subtraction:

$$
\widehat{\mathbf b}=\mathbf y-\widehat{\mathbf v}
$$

The pipeline writes two 16-bit stereo WAV files: `<song-name>_vocal.wav` and
`<song-name>_background.wav`.

```mermaid
flowchart LR
    input["Input audio"] --> stereo["Convert to stereo<br/>resample to 44.1 kHz"]
    stereo --> model{"Model found?"}
    model -->|no| download["Download temporary file<br/>verify size and SHA-256"]
    model -->|yes| infer["Chunked MDX-Net inference"]
    download --> infer
    infer --> vocal["Predicted vocals"]
    stereo --> subtract["Mix minus predicted vocals"]
    vocal --> subtract
    vocal --> vocalout["Vocal WAV"]
    subtract --> background["Background WAV"]
```

## Model Locations and Downloads

Models are searched in this order:

1. The directory supplied through the `--models-dir` job option;
2. The `MR_REMOVER_MODELS` environment variable;
3. The `models/` directory under the system application-data directory;
4. The `models/` directory at the development repository root.

If weights are not found, the application downloads them from TRvlvr's public UVR model releases
to the explicit directory or system application-data directory. A download is first written to a
`.part` file, then checked against both the registered file size and SHA-256 digest. Only a file
that passes both checks atomically replaces the final model path. Failure or cancellation removes
the temporary file.

The current catalog contains four model definitions:

| Model ID | Display name | Weights file |
|---|---|---|
| `mdxnet_1` | UVR-MDX-NET 1 | `UVR_MDXNET_1_9703.onnx` |
| `mdxnet_main` | UVR-MDX-NET Main | `UVR_MDXNET_Main.onnx` |
| `kim_vocal` | Kim Vocal 1 | `Kim_Vocal_1.onnx` |
| `kuielab_b` | kuielab B Vocals | `kuielab_b_vocals.onnx` |

Model weights are excluded from the wheel, source distribution, and standalone application.

## Model Specifications

The application looks up the model file's MD5 digest in `src/resources/model_data.json` to obtain
the FFT size, frequency dimension, time dimension, compensation factor, and primary-stem name.
The exact digests of all four built-in models are registered in that table; a model without a
matching record is rejected.

The ONNX input must be a four-dimensional tensor:

```text
[batch, 4, frequency dimension, time dimension]
```

The four planes are, in order, the real and imaginary parts of the left channel followed by the
real and imaginary parts of the right channel. Fixed dimensions must match the model
specification; the batch dimension may be symbolic in the exported model. ONNX Runtime currently
uses the CPU execution provider.

## Spectral Transform and Chunking

A short-time Fourier transform is applied to each channel. The required frequency range is
cropped and assembled into the input tensor. The lowest three frequency bins are cleared to match
the MDX-Net inference procedure. Real and imaginary model outputs are recombined into a complex
spectrum, unpredicted high-frequency bins are restored, and the inverse transform reconstructs the
waveform.

For long audio, the chunk size is calculated from the model's `hop`, `segment_size`, and `n_fft`.
Adjacent prediction chunks use Hann-windowed overlap-add:

$$
\widehat y[n]=\frac{\sum_k w_k[n],\widehat y_k[n]}
{\max\left(\sum_k w_k[n],\varepsilon\right)}
$$

The denominator is stored in separate temporary mapped audio so that overlap regions do not
change loudness. The compensation factor from the model specification is applied after merging.

## Resource and Quality Boundaries

- Inference input, output, and overlap dividers use `float32`; long-audio output is stored in
  mapped files.
- Both the inference loop and final normalization loop respond to cooperative cancellation.
- All models share one processing pipeline, but their training targets and timbral preferences
  differ. A model name does not imply a fixed ranking across all material.
- The background is the original mix minus the predicted vocals, not the output of a second
  independent model. Vocal-prediction errors therefore appear directly in the background.
