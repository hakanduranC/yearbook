"""Runs at interpreter start inside the sandbox image.

Seeds MPLCONFIGDIR from the font cache built at image build time, so a plot does not spend
seconds rebuilding it in the container's empty /tmp. Nothing else; keep it that way.
"""

import contextlib
import os
import shutil

_src = "/opt/mpl"
_dst = os.environ.get("MPLCONFIGDIR")
if _dst and os.path.isdir(_src) and not os.path.exists(_dst):
    with contextlib.suppress(OSError):
        shutil.copytree(_src, _dst)
