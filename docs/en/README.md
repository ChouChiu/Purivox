# Purivox Technical Documentation

<p align="left">
  <a href="../README.md">简体中文</a> · <strong>English</strong>
</p>

This directory contains technical specifications, digital signal processing (DSP) algorithms, and development guidelines for Purivox. For end-user installation and basic usage instructions, see the [project README](../../README_EN.md).

## Documentation Index

| Document | Key Topics |
|---|---|
| [Architecture and Data Flow](architecture.md) | Architectural layering, task execution model, chunked memory management, responsive UI, and error handling |
| [Reference Cancellation](reference-removal.md) | Global tempo and time alignment, complex transfer estimation, residual masking, and backing track generation |
| [Source Matching, the Timeline, and Segmented Rendering](matching.md) | Multi-source log-flux features, candidate clustering, timeline models, and segmented rendering pipelines |
| [Browser Build (WebAssembly)](web.md) | Pyodide runtime integration, Qt-free / single-thread constraints, heap memory budgeting, and lifecycle management |
| [Contributing](CONTRIBUTING.md) | Environment setup, code and i18n conventions, testing matrix, CI/CD pipelines, and release procedures |

## Reading Guide

- **System Architecture and Concurrency**: Review [Architecture and Data Flow](architecture.md) to understand how the GUI, CLI, worker threads, and core processing pipelines interact.
- **Cancellation Algorithms and Tuning**: Review [Reference Cancellation](reference-removal.md) for frequency-domain complex subtraction, adaptive regularization, and leakage regression models.
- **Multi-Source Detection**: Review [Source Matching, the Timeline, and Segmented Rendering](matching.md) for acoustic fingerprinting, cross-correlation searches, and engine selection heuristics.
- **WebAssembly Deployment**: Review [Browser Build (WebAssembly)](web.md) for Emscripten memory layout and client-side execution constraints.
- **Development and Verification**: Review [Contributing](CONTRIBUTING.md) for architectural linting rules, testing requirements, and commit conventions.

> Technical documentation reflects the current codebase implementation. Synthetic benchmark metrics referenced throughout are used for regression testing; real-world performance should always be evaluated through comparative listening on live audio recordings.
