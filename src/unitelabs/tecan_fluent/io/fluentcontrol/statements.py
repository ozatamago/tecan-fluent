"""Pieces shared by the FluentControl statements this connector sends: escaping, the ScriptGroup around one
statement, and the legacy driver macro line used by the devices driven through a driver (BioShake, Inheco
incubator, inhecoMTC, Incubator1)."""

import pathlib

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
"""The statement templates (package data)."""


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap(obj_xml: str) -> str:
    """Wrap one FluentControl statement in a ScriptGroup (same as build_liha_xml.wrap)."""
    body = "\n".join("    " + ln for ln in obj_xml.strip().split("\n"))
    return (
        "<ScriptGroup>\n  <Objects>\n" + body + "\n  </Objects>\n"
        "  <Name></Name>\n"
        "  <IsBreakpoint>False</IsBreakpoint>\n"
        "  <IsDisabledForExecution>False</IsDisabledForExecution>\n"
        "  <LineNumber>0</LineNumber>\n</ScriptGroup>"
    )


def legacy_macro_xml(module: str, name: str, settings: str | None = None, execution_time: str = "PT2S") -> str:
    """One legacy driver macro line (same form as for the ODTC and Magellan).

    execution_time is only the duration estimate shown in the GUI; execution does not wait for it (the ODTC PreMethod
    completed in 466 s with PT2S). In the GUI scripts most use PT2S, BioShake_TempOff uses PT0S, and the
    InhecoIncubator_SetTemp in Sub_Cleanup uses PT1M40S.
    """
    es = "<ExecutionSettings />" if settings is None else f"<ExecutionSettings>{_esc(settings)}</ExecutionSettings>"
    return wrap(
        '<Object Type="Tecan.VisionX.ApplicationDriver.LegacyDriverMacro">\n'
        f'  <LegacyDriverMacro Version="1" Name="{name}" ModuleName="{module}"'
        f' ExecutionTime="{execution_time}" IsBreakpoint="false"'
        ' IsDisabledForExecution="false" LineNumber="0">\n'
        f"    {es}\n"
        "  </LegacyDriverMacro>\n"
        "</Object>"
    )


def _num(value: float, decimals: int | None = None) -> str:
    return f"{value:.{decimals}f}" if decimals is not None else f"{value:g}"
