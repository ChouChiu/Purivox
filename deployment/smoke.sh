#!/usr/bin/env bash
# Run a standalone build the way a user would: start the GUI, then cancel a
# short synthetic song out of a synthetic stage through the CLI.
#
# PyInstaller only bundles what import analysis can see, and a module it missed
# fails when the frozen program first reaches it, not when it is built: the
# pages the GUI imports inside slots, the array-API shim scipy loads through
# importlib.  Running both paths once is what turns that into a failed build.
set -euo pipefail

binary="${1:?usage: smoke.sh <standalone executable>}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export QT_QPA_PLATFORM=offscreen

"$binary" --selftest

uv run --locked --no-dev python - "$work" <<'PYTHON'
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

rate = 44_100
time = np.arange(rate * 6) / rate
song = np.stack([0.2 * np.sin(2 * np.pi * 110 * time), 0.2 * np.sin(2 * np.pi * 165 * time)])
voice = 0.15 * np.sin(2 * np.pi * 440 * time)
stage = np.stack([0.8 * song[0] + 0.2 * song[1], 0.1 * song[0] + 0.85 * song[1]]) + voice
work = Path(sys.argv[1])
sf.write(work / "stage.wav", stage.T.astype(np.float32), rate, subtype="PCM_16")
sf.write(work / "song.wav", song.T.astype(np.float32), rate, subtype="PCM_16")
PYTHON

"$binary" mr "$work/stage.wav" "$work/song.wav" "$work/vocal.wav" --strength 75 --sigma 3 --align
test -s "$work/vocal.wav"
echo "smoke test passed: $binary"
