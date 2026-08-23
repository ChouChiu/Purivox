# Audio Station Technical Documentation

<p align="center">
  <a href="../README.md">简体中文</a> · <strong>English</strong>
</p>

This directory documents Audio Station's internal design, signal-processing methods, and
development workflow. For installation and usage instructions intended for general users, see
the [project README](../../README_EN.md). Mermaid diagrams describe flows and dependencies, while
LaTeX is used for mathematical models.

## Documentation Index

| Document | Contents |
|---|---|
| [Architecture and Data Flow](architecture.md) | Layer boundaries, task orchestration, audio storage, cancellation, and error handling |
| [Reference-Guided Vocal Isolation](reference-removal.md) | Time alignment, reference-mask cancellation, chunk blending, and center-focused processing |
| [Full Stage Processing](full-stage.md) | Multi-source fingerprints, candidate clustering, timeline generation, segmented rendering, and boundary protection |
| [AI Track Separation](neural-separation.md) | Model locations, verification, MDX-Net input/output, and overlap-add inference |
| [Development, Testing, and Release](development.md) | Environment setup, code conventions, quality gates, packaging, and standalone builds |

## Suggested Reading

- To understand how a task moves through the GUI, background thread, and processing pipeline,
  start with **Architecture and Data Flow**.
- To adjust reference-guided isolation, read **Reference-Guided Vocal Isolation** and verify
  alignment before increasing the strength.
- To change Full Stage automatic placement, read both **Full Stage Processing** and the
  cross-feature orchestration boundaries in the architecture document.
- To add a model or modify inference, read **AI Track Separation**.
- Before submitting code or building a release, read **Development, Testing, and Release**.

These documents describe the current Python implementation. Synthetic regression results are not
claims about quality on real music.
