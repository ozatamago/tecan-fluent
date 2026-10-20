"""Build the XML of the RGA (plate gripper) statements sent to FluentControl.

Each matches XML that succeeded on the device or a statement of the 01-07 GUI scripts (compared character by
character in tests/):
- RGA1_TransferLabware: succeeded on 2026-10-09 for transfers to the ODTC etc. (template copied from liha_ref)
- AddLabware / RemoveLabware: statement form from the GUI script 02_PCR_Ver1_0
- CgaGetFingers / CgaDropFingers: from the GUI scripts 03-06
"""

import re

from ...fluentcontrol.errors import BackendError
from ...fluentcontrol.statements import DATA, _esc, wrap

RGA_TEMPLATE = DATA / "rga_transfer_reference.xml"


def rga_xml(
    labware: str, location: str = "<BASE>", site: str = "", move_to_base: bool = False, fixed_site: bool = False
) -> str:
    """RGA1_TransferLabware. Replace the template values with triple-escaped text (same as qpcr_water_demo.rga).

    The real <BASE> is stored as &amp;amp;lt;BASE&amp;amp;gt;
    = inner XML text (level 1) -> string value (level 2) -> ScriptGroup XML (level 3).
    """
    src = RGA_TEMPLATE.read_text(encoding="utf-8").strip()
    fields = {
        "FixedSite": "true" if fixed_site else "false",
        "Labware": labware,
        "Location": location,
        "MoveToBase": "true" if move_to_base else "false",
        "Site": site,
    }
    for tag, value in fields.items():
        pattern = rf"(&amp;lt;{tag}&amp;gt;).*?(&amp;lt;/{tag}&amp;gt;)"
        new, count = re.subn(
            pattern, lambda m, value=value: m.group(1) + _esc(_esc(_esc(value))) + m.group(2), src, count=1
        )
        if count != 1:
            raise BackendError(f"RGA template has no {tag}")
        src = new
    src = re.sub(r'LineNumber="\d+"', 'LineNumber="0"', src, count=1)
    return wrap(src)


def add_labware_xml(labware_type: str, label: str, location: str, position: int) -> str:
    """Register labware in FluentControl's worktable memory (no device motion). Statement form from 02_PCR_Ver1_0."""
    return wrap(
        '<Object Type="Tecan.Core.Scripting.Worktable.Data.AddLabwareDataV1">\n'
        "  <AddLabwareDataV1>\n"
        f"    <LabwareType>{_esc(labware_type)}</LabwareType>\n"
        f"    <LabwareLable>{_esc(label)}</LabwareLable>\n"
        f"    <Location>{_esc(location)}</Location>\n"
        f"    <Position>{int(position)}</Position>\n"
        "    <Rotation>0</Rotation>\n"
        "    <HasLid>False</HasLid>\n"
        '    <Data Type="Tecan.Core.Scripting.Programming.ProgrammingStatementBaseDataV1">\n'
        "      <ProgrammingStatementBaseDataV1>\n"
        "        <IsBreakpoint>False</IsBreakpoint>\n"
        "        <IsDisabledForExecution>False</IsDisabledForExecution>\n"
        "        <LineNumber>0</LineNumber>\n"
        "      </ProgrammingStatementBaseDataV1>\n"
        "    </Data>\n"
        "  </AddLabwareDataV1>\n"
        "</Object>"
    )


def remove_labware_xml(label: str) -> str:
    """Remove labware from FluentControl's worktable memory (no device motion). Statement form from 02_PCR_Ver1_0."""
    return wrap(
        '<Object Type="Tecan.Core.Scripting.Worktable.Data.RemoveLabwareDataV1">\n'
        "  <RemoveLabwareDataV1>\n"
        f"    <LabwareName>{_esc(label)}</LabwareName>\n"
        '    <Data Type="Tecan.Core.Scripting.Programming.ProgrammingStatementBaseDataV1">\n'
        "      <ProgrammingStatementBaseDataV1>\n"
        "        <IsBreakpoint>False</IsBreakpoint>\n"
        "        <IsDisabledForExecution>False</IsDisabledForExecution>\n"
        "        <LineNumber>0</LineNumber>\n"
        "      </ProgrammingStatementBaseDataV1>\n"
        "    </Data>\n"
        "  </RemoveLabwareDataV1>\n"
        "</Object>"
    )


FINGERS = ("Eccentric[001]", "Centric[001]")
"""Finger sets on the worktable (FES Eccentric Nest / FES Centric Nest). 03 and 05 use Eccentric, 04 and 06 Centric."""


FINGER_NESTS = ("FES Eccentric Nest[001]", "FES Centric Nest[001]")
"""Where DropFingers may put the fingers. Empty means back where they came from (BackToSource)."""


def _statement(template: str, labware_name: str) -> str:
    src = (DATA / template).read_text(encoding="utf-8").strip()
    src, n = re.subn(
        r"<LabwareName>[^<]*</LabwareName>", f"<LabwareName>{_esc(labware_name)}</LabwareName>", src, count=1
    )
    if n != 1:
        raise BackendError(f"{template} has no LabwareName")
    return wrap(src)


def get_fingers_xml(fingers: str) -> str:
    if fingers not in FINGERS:
        raise BackendError(f"Fingers must be one of {', '.join(FINGERS)}")
    return _statement("cga_get_fingers_reference.xml", fingers)


def drop_fingers_xml(nest: str = "") -> str:
    """Put the fingers down: into the named finger nest (as in 06 line 58), or back where they came from when nest is
    empty (as in 03 and 05). Naming the nest does not rely on FluentControl remembering where the fingers came from,
    e.g. when they were picked up in an earlier run."""
    if nest and nest not in FINGER_NESTS:
        raise BackendError(f"Nest must be one of {', '.join(FINGER_NESTS)} (or empty for back to source)")
    return _statement("cga_drop_fingers_reference.xml", nest)


def transfer_xml(labware: str, location: str, site: int, fixed_site: bool = True) -> str:
    return rga_xml(labware, location, str(int(site)), fixed_site=fixed_site)


def to_base_xml(labware: str) -> str:
    return rga_xml(labware, "<BASE>", "", move_to_base=True)


def lid_on_xml(lid: str, plate: str) -> str:
    # FixedSite must be true. The cover site location is shared by every plate of the same type (e.g.
    # 96Microplate_CoverSite_4 for all 96 Well Flat_Custom plates); with FixedSite=false FluentControl ignores the
    # site index and takes the first free cover site, i.e. possibly another plate. On 2026-10-16 the lid went onto
    # the Flat plate at Nest7mm_Pos[6] instead of the one at [2] this way (03 line 45 uses false; it has one plate).
    q = plate.replace('"', "")
    return rga_xml(lid, f'GetCoverSiteName("{q}")', f'GetCoverSiteIndex("{q}")', fixed_site=True)
