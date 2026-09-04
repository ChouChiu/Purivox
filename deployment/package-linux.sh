#!/usr/bin/env bash
# Wrap the onefile executable in a .deb and an .rpm.
#
# The onefile already carries its own Python, Qt and DSP dependencies, so a
# package adds only what a desktop needs to find it: the launcher on PATH, a
# desktop entry, an icon, and the licence. `fpm` builds both formats from the
# same staged tree - it owns the metadata each one expects, down to not
# stripping an executable whose payload is appended to it.
set -euo pipefail

binary="${1:-dist/Purivox.bin}"
output="${2:-dist}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$root/src/app/version.py")"
if [[ -z "$version" ]]; then
  echo "could not read __version__ from src/app/version.py" >&2
  exit 1
fi

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
# The staging root is the package's own `/`, and mktemp hands out 0700: a
# package carrying that mode would apply it to the root of the machine that
# installs it.
chmod 755 "$stage"

# The executable is self-contained, so it goes on PATH under the name the CLI
# is invoked by rather than into a private directory with a wrapper.
install -Dm755 "$binary" "$stage/usr/bin/purivox"
install -Dm644 "$root/deployment/purivox.desktop" \
  "$stage/usr/share/applications/purivox.desktop"
install -Dm644 "$root/src/resources/purivox.svg" \
  "$stage/usr/share/icons/hicolor/scalable/apps/purivox.svg"
# Each format looks for the licence in its own place.
install -Dm644 "$root/LICENSE" "$stage/usr/share/doc/purivox/copyright"
install -Dm644 "$root/LICENSE" "$stage/usr/share/licenses/purivox/LICENSE"

mkdir -p "$output"

common=(
  --input-type dir
  --chdir "$stage"
  --package "$output"
  --name purivox
  --version "$version"
  --iteration 1
  --architecture native
  --category sound
  --license "AGPL-3.0-or-later"
  --maintainer "Purivox contributors"
  --url "https://github.com/ChouChiu/Purivox"
  --description "Reference-guided and neural vocal separation
Purivox cancels a known backing track out of a stage or live recording, and
can separate vocals with UVR MDX-Net models when no source is available."
  --force
)

# Qt still loads these two from the distribution; everything else the
# executable brings with it.
fpm "${common[@]}" --output-type deb \
  --depends libegl1 --depends libpulse0 .
fpm "${common[@]}" --output-type rpm \
  --depends mesa-libEGL --depends pulseaudio-libs .

ls -1 "$output"/purivox*.deb "$output"/purivox*.rpm
