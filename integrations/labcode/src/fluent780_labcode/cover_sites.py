"""Where a lid goes onto (or comes off) a plate, tip rack or trough: the holder's cover site.

FluentControl names a cover site with two expressions, ``GetCoverSiteName("<holder>")`` and
``GetCoverSiteIndex("<holder>")``. The Tecan Fluent connector takes the location as a string (so the name expression
is passed through and FluentControl evaluates it), but the site as an integer, so the index has to be known before the
command is sent. The serial test script of 2026-11-19 read it with ``RuntimeController.ResolveExpression`` of the
UniteLabs FluentControl connector right before each command; this module does the same, or takes the value from a
fixed table in the run configuration.

Nothing here guesses: a holder that is neither in the table nor resolvable fails the operation before anything is
sent.
"""

from __future__ import annotations

import subprocess
from typing import Any

from .mission import MissionError

# The PowerShell that finds the port of the UniteLabs FluentControl connector on the Fluent PC (it listens on a port
# chosen at start-up). The same query as the 2026-11-18 test scripts (ct.py conn()).
_DISCOVER_PORT = (
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'repo\\\\tecan-fluentcontrol' -and "
    "$_.Name -eq 'python.exe' } | ForEach-Object { Get-NetTCPConnection -State Listen -OwningProcess $_.ProcessId "
    "-ErrorAction SilentlyContinue | ForEach-Object { $_.LocalPort } }"
)


def name_expression(holder: str) -> str:
    """The location string for the cover site of `holder` (evaluated by FluentControl)."""
    return f'GetCoverSiteName("{holder.replace(chr(34), "")}")'


def index_expression(holder: str) -> str:
    return f'GetCoverSiteIndex("{holder.replace(chr(34), "")}")'


def discover_connector_port() -> int:
    """The UniteLabs FluentControl connector's port, found the way the Fluent PC scripts find it (Windows only)."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", _DISCOVER_PORT], capture_output=True, text=True, check=False
    ).stdout.split()
    if not out:
        raise MissionError("the UniteLabs FluentControl connector was not found on this computer")
    return int(out[0])


class CoverSites:
    """Resolve cover-site indices as the mission says (``mission.json`` key ``cover_sites``).

    ``{"static": {"<holder>": <index>, ...}}`` takes the indices from the table;
    ``{"resolve": {"host": ..., "port": <int> | "auto", "insecure": true}}`` asks the UniteLabs FluentControl connector
    (``port: auto`` finds it on this computer, i.e. when labcode runs on the Fluent PC). Both may be given; the table
    wins. `connect` is injectable for tests.
    """

    def __init__(self, config: dict | None, connect: Any = None):
        self.config = config or {}
        self.connect = connect
        self._client = None

    def index(self, holder: str) -> int:
        static = self.config.get("static") or {}
        if holder in static:
            return int(static[holder])
        resolve = self.config.get("resolve")
        if not resolve:
            raise MissionError(
                f"the cover site index of {holder!r} is not known: add it to cover_sites.static in the run "
                "configuration, or configure cover_sites.resolve"
            )
        if self._client is None:
            port = resolve.get("port", "auto")
            port = discover_connector_port() if port == "auto" else int(port)
            connect = self.connect
            if connect is None:
                from sila2.client import SilaClient

                connect = SilaClient
            self._client = connect(resolve.get("host", "127.0.0.1"), port, insecure=resolve.get("insecure", True))
        result = self._client.RuntimeController.ResolveExpression(index_expression(holder)).Result
        try:
            return int(result)
        except (TypeError, ValueError):
            raise MissionError(f"{index_expression(holder)} resolved to {result!r}, not a site index") from None
