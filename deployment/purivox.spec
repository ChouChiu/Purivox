# PyInstaller spec for the standalone builds, run from the repository root:
#
#     uv run --locked --group deploy pyinstaller deployment/purivox.spec --noconfirm
#
# Linux and Windows get one self-extracting executable, dist/Purivox.bin and
# dist/Purivox.exe; macOS gets dist/Purivox.app, because a bundle is what Finder
# and the dock expect and onefile is not one.
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH, Analysis, PYZ, EXE, COLLECT and BUNDLE are globals PyInstaller defines.
ROOT = Path(SPECPATH).parent
SOURCE = ROOT / "src"
VERSION = re.search(
    r'^__version__ = "(.*)"$', (SOURCE / "app/version.py").read_text(encoding="utf-8"), re.M
).group(1)

# Every top-level package under src/ ships whole, found rather than listed so a
# new one cannot be left out.  Import analysis alone would miss code the GUI
# imports inside slots - the pages, the download dialog, yt-dlp behind it.
sys.path.insert(0, str(SOURCE))
PACKAGES = sorted(path.parent.name for path in SOURCE.glob("*/__init__.py"))
hiddenimports = [module for package in PACKAGES for module in collect_submodules(package)]
# scipy reaches its array-API shim through importlib, which analysis cannot see.
hiddenimports.append("scipy._external.array_api_compat.numpy")

a = Analysis(
    [str(ROOT / "deployment/main.py")],
    pathex=[str(SOURCE)],
    # The application loads compiled catalogues; the .ts sources stay behind.
    datas=collect_data_files("resources", excludes=["**/*.ts"]),
    hiddenimports=hiddenimports,
    excludes=["tkinter"],
    # Only the Linux bootloader rewrites the library path children inherit.
    runtime_hooks=(
        [str(ROOT / "deployment/runtime_library_path.py")]
        if sys.platform.startswith("linux")
        else []
    ),
    # -OO, as the builds have always run: no asserts, no docstrings.
    optimize=2,
)

# This application installs only its own translator, so Qt's catalogues would
# ship unread.  Image formats are trimmed to what the UI draws: nothing here
# opens PDF, TIFF, WebP, TGA, WBMP, ICNS or GIF.  Nor does it take input
# through Qt's virtual keyboard or raw evdev devices, or ask Qt whether the
# network is reachable.
_UNUSED = re.compile(
    r"(^|[/\\])PySide6[/\\](Qt[/\\])?translations[/\\]"
    r"|imageformats[/\\][^/\\]*q(pdf|tiff|webp|tga|wbmp|icns|gif)\b"
    r"|Qt6?Pdf|Qt6?VirtualKeyboard|qtvirtualkeyboardplugin"
    r"|plugins[/\\](generic|networkinformation)[/\\]"
)
a.datas = [entry for entry in a.datas if not _UNUSED.search(entry[0])]
a.binaries = [entry for entry in a.binaries if not _UNUSED.search(entry[0])]


def _from_the_build_machine(source: str) -> bool:
    """Whether a library is the build host's own rather than the environment's."""
    path = Path(source).resolve()
    if "site-packages" in path.parts or path.name.startswith("libpython"):
        return False
    # The interpreter's own extension modules, wherever it is installed.
    standard_library = Path(sys.base_prefix, "lib", f"python{sys.version_info[0]}.{sys.version_info[1]}")
    if path.is_relative_to(standard_library.resolve()):
        return False
    return path.is_relative_to("/usr") or path.is_relative_to("/lib")


if sys.platform.startswith("linux"):
    # A Linux desktop brings its own display, font, theme and audio stack:
    # X11, xcb and Wayland, fontconfig, GLib and DBus, GTK for the platform
    # theme, PulseAudio.  The build machine's copies would be loaded in place
    # of the user's and drift from the configuration they read, so they stay
    # behind as they did in every release before.  Qt's TLS backend is the one
    # exception: it loads OpenSSL by name, and a desktop is not guaranteed to
    # carry the major version this Qt asks for.
    a.binaries = [
        entry
        for entry in a.binaries
        if not _from_the_build_machine(entry[1])
        or re.match(r"lib(ssl|crypto)\.so", Path(entry[0]).name)
    ]

pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="Purivox",
        console=False,
        upx=False,
    )
    collected = COLLECT(exe, a.binaries, a.datas, name="Purivox", upx=False)
    app = BUNDLE(
        collected,
        name="Purivox.app",
        icon=str(ROOT / "deployment/purivox.icns"),
        # The identifier follows the project homepage, purivox.wwchun.top.
        bundle_identifier="top.wwchun.purivox",
        version=VERSION,
        info_plist={
            "CFBundleName": "Purivox",
            "CFBundleDisplayName": "Purivox",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        # The .bin suffix is what the Linux packaging and the release assets name.
        name="Purivox.bin" if sys.platform.startswith("linux") else "Purivox",
        # The same executable is the CLI, so it keeps the console it is run from.
        console=True,
        icon=str(ROOT / "deployment/purivox.ico") if sys.platform == "win32" else None,
        upx=False,
    )
