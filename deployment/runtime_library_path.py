# PyInstaller runtime hook: hand child processes the library path they would
# have had without the bundle.
#
# The Linux bootloader starts the frozen program with LD_LIBRARY_PATH pointing
# into the extracted bundle, which is how it finds its own Qt.  The dynamic
# loader reads that once, at startup, so restoring it here changes nothing for
# this process; left alone, everything the app launches inherits it - the
# browser or file manager QDesktopServices opens - and a Qt desktop app that
# loads this Qt in place of its own does not start.  yt-dlp does the same for
# the ffmpeg it runs, reading the same variable this keeps.
import os

_original = os.environ.get("LD_LIBRARY_PATH_ORIG")
if _original is None:
    os.environ.pop("LD_LIBRARY_PATH", None)
else:
    os.environ["LD_LIBRARY_PATH"] = _original
