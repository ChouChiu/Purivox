# Purivox Technical Documentation

<p align="left">
  <a href="../README.md">简体中文</a> · <strong>English</strong>
</p>

This directory documents Purivox's internal design, signal-processing methods, and
development workflow. For installation and usage instructions intended for general users, see
the [project README](../../README_EN.md). Flows and dependencies are drawn with Mermaid, and
mathematical models use LaTeX.

## Documentation Index

| Document | Contents |
|---|---|
| [Architecture and Data Flow](architecture.md) | Layer boundaries, task orchestration, audio storage, cancellation, and error handling |
| [Reference Cancellation](reference-removal.md) | Time alignment, complex transfer estimation, residual masking, and chunk blending |
| [Full Stage Processing](full-stage.md) | Multi-source fingerprints, candidate clustering, timeline generation, segmented rendering, and boundary protection |
| [AI Track Separation](neural-separation.md) | Model locations, verification, MDX-Net input/output, and overlap-add inference |
| [Browser Build (WebAssembly)](web.md) | The Pyodide runtime, the changes for a Qt-free build, the memory ceiling, cancellation, and deployment |
| [Contributing](CONTRIBUTING.md) | Environment setup, code conventions, translations, verifying a change, commit conventions, and release |

## Suggested Reading

- To understand how a task moves through the GUI, background thread, and processing pipeline,
  start with **Architecture and Data Flow**.
- To adjust the removal quality, read **Reference Cancellation** and check the alignment before
  raising the strength.
- To change Full Stage automatic placement, read both **Full Stage Processing** and the
  cross-feature orchestration boundaries in the architecture document.
- To add a model or modify inference, read **AI Track Separation**.
- Before submitting code or building a release, read **Contributing**.

These documents describe the current Python implementation. Synthetic regression results are not
claims about quality on real music.
