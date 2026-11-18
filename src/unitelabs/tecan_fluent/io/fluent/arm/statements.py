"""Build the XML of the Air FCA pipetting statements (GetTips, Aspirate, Dispense, Mix, DropTips, MoveArm) and of
Set Available Tips (Worktable).

The XML is the 1-channel form that ran on the instrument in August 2026 (tests/fixtures/liha_verified); only the
values change (labware, wells, volumes, liquid class, channels, tip type). The Smart statements are in
smart_xml.py."""

import re

from ...fluentcontrol.errors import BackendError
from ...fluentcontrol.statements import DATA, _esc, wrap

WASTE = "FCA Thru Deck Waste Chute_1"


TIP_SPACING = 9  # mm; every verified and GUI statement on 96-well plates and troughs uses 9
TIP_RACK_ROWS, TIP_RACK_COLUMNS = 8, 12
"""Every FCA SBS tip rack holds 96 tips in 8 rows and 12 columns."""


def _template(name: str) -> str:
    return (DATA / name).read_text(encoding="utf-8").strip()


def _set(xml: str, tag: str, value: str) -> str:
    new, n = re.subn(rf"<{tag}>[^<]*</{tag}>|<{tag} />", lambda _: f"<{tag}>{_esc(value)}</{tag}>", xml, count=1)
    if n != 1:
        raise BackendError(f"Template has no {tag}")
    return new


def _set_list(xml: str, tag: str, values: list, kind: str) -> str:
    """Replace the items of a list element (<Volumes>, <SelectedTipsIndexes>) keeping the template's item form."""
    elem = {"System.String": "string", "System.Int32": "int"}[kind]
    items = "".join(f'<Object Type="{kind}">\n<{elem}>{_esc(str(v))}</{elem}>\n</Object>\n' for v in values)
    new, n = re.subn(rf"<{tag}>.*?</{tag}>|<{tag} />", f"<{tag}>\n{items}</{tag}>", xml, count=1, flags=re.S)
    if n != 1:
        raise BackendError(f"Template has no {tag}")
    return new


def well_index(well: str, rows: int, columns: int) -> int:
    """Column-major index from 0, as FluentControl serializes it (A1 = 0, B1 = 1, ..., A2 = rows)."""
    m = re.fullmatch(r"([A-Za-z])(\d+)", well.strip())
    if not m:
        raise BackendError(f"Well '{well}' is not like A1")
    row, col = ord(m.group(1).upper()) - ord("A"), int(m.group(2)) - 1
    if not (0 <= row < rows and 0 <= col < columns):
        raise BackendError(f"Well {well} is outside the labware ({rows} rows x {columns} columns)")
    return col * rows + row


def wells_fields(wells: list[str], rows: int, columns: int) -> tuple[str, str]:
    """(SerializedWellIndexes, SelectedWellsString) in the forms the GUI scripts use."""
    idx = [well_index(w, rows, columns) for w in wells]
    names = [w.strip().upper() for w in wells]
    if len(set(idx)) == 1:
        return f"{idx[0]};" * len(idx), f"{len(idx)} * {names[0]}"
    if all(b - a == 1 for a, b in zip(idx, idx[1:], strict=False)):
        return f"{idx[0]}>1>{idx[-1]};", f"{names[0]} - {names[-1]}"
    return "".join(f"{i};" for i in idx), ", ".join(names)


def get_tips_xml(tip_type: str, channels: list[int], rack: str = "") -> str:
    xml = _template("liha_gettips_reference.xml")
    xml = _set_list(xml, "SelectedTipsIndexes", [c - 1 for c in channels], "System.Int32")
    xml = _set(xml, "LabwareName", rack)
    xml = re.sub(r"TOOLNAME:[^<]*<", f"TOOLNAME:{_esc(tip_type)}<", xml, count=1)
    return wrap(xml)


def set_next_tip_position_xml(rack: str, well: str, rows: int = TIP_RACK_ROWS, columns: int = TIP_RACK_COLUMNS) -> str:
    """FluentControl's "Set Available Tips (Worktable)" for one well: ONLY that well of the rack becomes available.

    It does not mean "start at this well": on 2026-11-18, after C1 alone was set, the next GetTips took C1 and the
    one after it raised FCA_RTE_004_001 ("Please replace 'FCA, 50ul SBS' on the worktable"). So it is sent before every
    GetTips that should take from the rack. A list of several wells has not been tried. Every run start registers the
    racks as full again. Refused by FluentControl ("Could not find labware '...' on worktable.") when the rack is not on
    the run's worktable. Form accepted by FluentControl 2026-11-18 inside an open run."""
    name = well.strip().upper()
    index = well_index(name, rows, columns)
    return wrap(
        '<Object Type="Tecan.Core.Scripting.Worktable.SetNextTipPositionStatement">\n'
        "<SetNextTipPositionStatement>\n"
        f"<LabwareName>{_esc(rack)}</LabwareName>\n"
        "<SelectedWellIndexes>\n"
        '<Object Type="System.Int32">\n'
        f"<int>{index}</int>\n"
        "</Object>\n"
        "</SelectedWellIndexes>\n"
        f"<SelectedWellsString>{name}</SelectedWellsString>\n"
        "<IsBreakpoint>False</IsBreakpoint>\n"
        "<IsDisabledForExecution>False</IsDisabledForExecution>\n"
        "<LineNumber>1</LineNumber>\n"
        "</SetNextTipPositionStatement>\n"
        "</Object>"
    )


def move_arm_xml(labware: str, well: str, channels: list[int], rows: int, columns: int) -> str:
    """Move the Air FCA arm at travel height to a well (FluentControl's Move Arm, "travel to labware"). The form is the
    one in FluentControl's own "AirFCA Leakage Test and cLLD Self Test" script; nothing is aspirated or dispensed."""
    xml = _template("liha_movearm_reference.xml")
    serialized, shown = wells_fields([well] * len(channels), rows, columns)
    xml = _set(xml, "SerializedWellIndexes", serialized)
    xml = _set(xml, "SelectedWellsString", shown)
    xml = _set_list(xml, "SelectedTipsIndexes", [c - 1 for c in channels], "System.Int32")
    return wrap(_set(xml, "LabwareName", labware))


def drop_tips_xml(channels: list[int]) -> str:
    xml = _template("liha_droptips_reference.xml")
    xml = _set_list(xml, "SelectedTipsIndexes", [c - 1 for c in channels], "System.Int32")
    return wrap(_set(xml, "LabwareName", WASTE))


def pipetting_xml(
    kind: str,
    labware: str,
    wells: list[str],
    volumes: list[float],
    liquid_class: str,
    channels: list[int],
    rows: int,
    columns: int,
    cycles: int | None = None,
) -> str:
    """Aspirate / Dispense / Mix of the given channels; wells and volumes are one per channel."""
    xml = _template(
        {
            "Aspirate": "liha_aspirate_reference.xml",
            "Dispense": "liha_dispense_reference.xml",
            "Mix": "liha_mix_reference.xml",
        }[kind]
    )
    serialized, shown = wells_fields(wells, rows, columns)
    xml = _set_list(xml, "Volumes", [f"{v:g}" for v in volumes], "System.String")
    xml = _set(xml, "LiquidClassNameBySelection", liquid_class)
    xml = _set(xml, "SerializedWellIndexes", serialized)
    xml = _set(xml, "SelectedWellsString", shown)
    xml = _set(xml, "WellOffset", "0")
    xml = _set_list(xml, "SelectedTipsIndexes", [c - 1 for c in channels], "System.Int32")
    xml = _set(xml, "TipSpacing", str(TIP_SPACING))
    xml = _set(xml, "LabwareName", labware)
    if cycles is not None:
        xml = _set(xml, "Cycles", str(int(cycles)))
    return wrap(xml)
