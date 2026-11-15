# SPDX-License-Identifier: GPL-3.0-or-later
"""Container HEALTHCHECK: ``/api/v1/health?ready=1`` (includes a Mongo ping) must answer 200.

Django validates the Host header, so send one that ``PANIC_ALLOWED_HOSTS`` accepts: its first entry
(a leading-dot domain becomes a subdomain of it; ``*`` or unset becomes ``localhost``).
"""

import os
import sys
import urllib.request

port = os.environ.get("PANIC_SERVER_BIND", "0.0.0.0:8210").rsplit(":", 1)[1]
first = (os.environ.get("PANIC_ALLOWED_HOSTS", "") or "localhost").split(",")[0].strip()
host = "localhost" if first in ("", "*") else ("healthcheck" + first if first.startswith(".") else first)
req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v1/health?ready=1", headers={"Host": host})
try:
    with urllib.request.urlopen(req, timeout=4) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:  # noqa: BLE001 - any failure is "unhealthy"
    sys.exit(1)
