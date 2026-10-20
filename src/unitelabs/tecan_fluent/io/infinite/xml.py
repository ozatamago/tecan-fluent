"""Build the XML sent to FluentControl for the Infinite 200 PRO in the Fluent 780.

Each matches XML that succeeded on the device (compared character by character in tests/).
- Magellan_Open / Magellan_Close / Magellan_Measure: succeeded via GenericCommand on 2026-08-13, sent in the
  same form again on 10-09

The RGA statements that bring a plate in and out (RGA1_TransferLabware, AddLabware / RemoveLabware) are in
io/fluent/gripper/statements.py.
"""

from __future__ import annotations

from ..fluentcontrol.errors import BackendError
from ..fluentcontrol.statements import _esc, wrap

MAGELLAN_MACROS = {"Magellan_Open", "Magellan_Close", "Magellan_Measure"}


def magellan_xml(name: str, settings: str | None = None) -> str:
    """A Magellan macro. Measure settings are "<output path>,<method>.mth,0,0,0"."""
    if name not in MAGELLAN_MACROS:
        raise BackendError(f"{name} is not an allowed Magellan macro")
    if (name == "Magellan_Measure") != (settings is not None):
        raise BackendError(f"Invalid arguments for {name}")
    if settings is not None and ("<" in settings or ">" in settings):
        # 2026-08-13: a <YYMMDD-NNN> sequence pattern broke GenericCommand
        raise BackendError("Magellan_Measure arguments must not contain < > (use a fixed file name)")
    es = "<ExecutionSettings />" if settings is None else f"<ExecutionSettings>{_esc(settings)}</ExecutionSettings>"
    return wrap(
        '<Object Type="Tecan.VisionX.ApplicationDriver.LegacyDriverMacro">\n'
        f'  <LegacyDriverMacro Version="1" Name="{name}" ModuleName="Magellan"'
        ' ExecutionTime="PT2S" IsBreakpoint="false"'
        ' IsDisabledForExecution="false" LineNumber="0">\n'
        f"    {es}\n"
        "  </LegacyDriverMacro>\n"
        "</Object>"
    )
