# AUR package

`purivox-bin` installs the Linux `.deb` this repository publishes with every tag: the Nuitka
onefile on `PATH` as `purivox`, plus the desktop entry, the icon and the licence. Nothing is
compiled on the user's machine, and the executable is never stripped — its payload is appended to
it, and stripping would remove the program.

Publishing is manual and deliberately outside CI: a release workflow that pushed to the AUR would
publish a package nobody had installed once.

## Releasing a version

```bash
deployment/aur/publish.sh                 # the version in src/app/version.py
deployment/aur/publish.sh 1.1.0 --dry-run # everything except the push
```

The script reads the version, takes the `.deb` checksum from the release's own `SHA256SUMS`,
rewrites `pkgver`, `pkgrel` and `sha256sums`, regenerates `.SRCINFO`, builds the package as a
check that the release actually installs, and pushes those two files — the only ones the AUR
keeps — to `ssh://aur@aur.archlinux.org/purivox-bin.git`. `--skip-build` drops the check;
`--dry-run` leaves the local files updated and stops before the push.

It needs an AUR account with an SSH key registered, and `base-devel` for `makepkg`. The first push
to a name that does not exist yet is what creates the package.

A packaging fix against a release that is already published is the one case to do by hand: raise
`pkgrel`, run `makepkg --printsrcinfo > .SRCINFO`, and push. The script resets `pkgrel` to 1,
because it assumes a new upstream version.
