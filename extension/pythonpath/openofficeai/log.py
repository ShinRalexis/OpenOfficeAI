# -*- coding: utf-8 -*-
# Small diagnostic log (openofficeai.log next to the settings file).
# Never logs API keys or document text, only what happened and errors.
from __future__ import unicode_literals

import io
import os
import time

_path = [None]
MAX_BYTES = 200 * 1024


def set_path(path):
    _path[0] = path


def write(message):
    path = _path[0]
    if not path:
        return
    try:
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            os.remove(path)
        line = "{0} {1}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), message)
        with io.open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
