#!/usr/bin/env bash
# Point the AUR package at a published release and push it.
#
# The PKGBUILD tracks one released `.deb`, so a new version is three mechanical
# edits - the version, its checksum, and the regenerated `.SRCINFO` - followed
# by a push to a repository that holds only those two files. Doing it by hand is
# how a package ends up published with last release's checksum.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
repository="https://github.com/ChouChiu/Purivox"
aur_remote="ssh://aur@aur.archlinux.org/purivox-bin.git"

version=""
build=1
push=1
for argument in "$@"; do
  case "$argument" in
    --skip-build) build=0 ;;
    --dry-run) push=0 ;;
    -h|--help)
      echo "usage: ${BASH_SOURCE[0]##*/} [<version>] [--skip-build] [--dry-run]"
      exit 0
      ;;
    -*) echo "unknown option: $argument" >&2; exit 2 ;;
    *) version="$argument" ;;
  esac
done

# The tag, the packaged version and the update check all read this one file, so
# the release to publish is whatever it says unless a version is named.
if [[ -z "$version" ]]; then
  version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$root/src/app/version.py")"
fi
if [[ -z "$version" ]]; then
  echo "could not read __version__ from src/app/version.py" >&2
  exit 1
fi

iteration="$(sed -n 's/^_iteration=\(.*\)$/\1/p' "$here/PKGBUILD")"
package="purivox_${version}-${iteration}_amd64.deb"
echo "==> release v${version}, package ${package}"

# The release publishes one flat SHA256SUMS over its assets; taking the checksum
# from there costs one request instead of a 122 MB download.
sums="$(curl -fsSL "${repository}/releases/download/v${version}/SHA256SUMS")"
checksum="$(awk -v name="$package" '$2 == name { print $1 }' <<<"$sums")"
if [[ -z "$checksum" ]]; then
  echo "v${version} publishes no ${package}; is the release finished?" >&2
  exit 1
fi
echo "==> sha256 ${checksum}"

# pkgrel counts packaging fixes against one upstream version, so a new version
# starts it over.
sed -i \
  -e "s/^pkgver=.*/pkgver=${version}/" \
  -e "s/^pkgrel=.*/pkgrel=1/" \
  -e "s/^sha256sums=.*/sha256sums=('${checksum}')/" \
  "$here/PKGBUILD"
(cd "$here" && makepkg --printsrcinfo > .SRCINFO)
echo "==> PKGBUILD and .SRCINFO updated"

# Building here downloads and repacks the same file the AUR user would, which is
# the only check that the release actually installs.
if (( build )); then
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  cp "$here/PKGBUILD" "$work/"
  (cd "$work" && makepkg -f)
  echo "==> built $(cd "$work" && echo purivox-bin-*.pkg.tar.*)"
fi

if (( ! push )); then
  echo "==> dry run: not pushing"
  exit 0
fi

# The AUR repository carries the two files and nothing else, so it is cloned
# fresh rather than kept as a second remote of this one.
clone="$(mktemp -d)"
trap 'rm -rf "${work:-}" "$clone"' EXIT
git clone --quiet "$aur_remote" "$clone"
cp "$here/PKGBUILD" "$here/.SRCINFO" "$clone/"
# The first push to a name the AUR does not know yet clones an empty repository,
# where the two files are untracked rather than modified: staging first is what
# makes "nothing changed" mean the same thing in both cases.
git -C "$clone" add PKGBUILD .SRCINFO
if [[ -z "$(git -C "$clone" status --porcelain)" ]]; then
  echo "==> AUR already has ${version}-1"
  exit 0
fi
git -C "$clone" commit --quiet -m "purivox-bin ${version}-1"
# The AUR accepts `master` and declines every other branch, while a clone of a
# repository that does not exist yet leaves HEAD on whatever this machine calls
# its default branch. Naming the remote branch keeps that local setting out of
# it.
git -C "$clone" push --quiet origin HEAD:master
echo "==> pushed purivox-bin ${version}-1"
