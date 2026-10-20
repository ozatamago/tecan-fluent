"""The XML of the ODTC macros (SiLA-ODTC legacy driver macros), identical to what ran on the device in the
2026-10-09 qPCR water demo (odtc() in qpcr_water_demo.py)."""

from ..fluentcontrol.errors import BackendError

# Only allow macros that have been proven on the ODTC device.
# Left out: SetParameters crashes the device (confirmed device-side bug); StopMethod is rejected as unknown.
ALLOWED_MACROS = {
    "SiLA-ODTC_OpenDoor",
    "SiLA-ODTC_CloseDoor",
    "SiLA-ODTC_ExecuteMethod",
    "SiLA-ODTC_ReadActualTemperature",
}


# Macros that require an argument (the method name for ExecuteMethod)
MACROS_WITH_SETTINGS = {"SiLA-ODTC_ExecuteMethod"}


def odtc_macro_xml(name: str, settings: str | None = None) -> str:
    """Turn one ODTC legacy driver macro line into a FluentControl script fragment (ScriptGroup).

    settings is the value for ExecutionSettings (the method name for ExecuteMethod). It is XML-escaped once.
    """
    if name not in ALLOWED_MACROS:
        raise BackendError(f"{name} is not an allowed macro")
    if (name in MACROS_WITH_SETTINGS) != (settings is not None):
        raise BackendError(f"Invalid arguments for {name}")
    if settings is None:
        body = "        <ExecutionSettings />\n"
    else:
        esc = settings.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        body = f"        <ExecutionSettings>{esc}</ExecutionSettings>\n"
    return (
        "<ScriptGroup>\n"
        "  <Objects>\n"
        '    <Object Type="Tecan.VisionX.ApplicationDriver.LegacyDriverMacro">\n'
        f'      <LegacyDriverMacro Version="1" Name="{name}" ModuleName="SiLA-ODTC" ExecutionTime="PT2S" '
        'IsBreakpoint="false" IsDisabledForExecution="false" LineNumber="0">\n' + body + "      </LegacyDriverMacro>\n"
        "    </Object>\n"
        "  </Objects>\n"
        "  <Name></Name>\n"
        "  <IsBreakpoint>False</IsBreakpoint>\n"
        "  <IsDisabledForExecution>False</IsDisabledForExecution>\n"
        "  <LineNumber>0</LineNumber>\n"
        "</ScriptGroup>"
    )
