"""Pipetting with the FCA arm: one transfer (GetTips ... DropTips) per call, single or several channels.

Used by the environment scripts of the pipetting processes, so that one labcode operation (one SiLA2 connection) is
one whole transfer. Every command goes through `Step.call`, so each is checked against the mission's run and
recorded. Labware, wells, volumes, liquid classes and tip racks come from the workflow and the run boundary.

Tips. FluentControl takes tips column-wise (A1, B1, ... H1, A2, ...). The connector's deck state follows partly used
racks with the well of their next tip (``Deck.TipRacks``: "... next tip F4 ..."). Several channels take neighbouring
tips, so they must fit in the rest of the rack's current column: a group of wells that does not is split (e.g. 2 + 1
when two tips are left in the column), as in the 2026-11-19 run.
"""

from __future__ import annotations

import re
from typing import Any

from .mission import MissionError
from .steps import Step

ROWS = "ABCDEFGH"
_NEXT_TIP = re.compile(r"next tip ([A-H])(\d+)")


def column_of(well: str) -> int:
    m = re.fullmatch(r"([A-P])(\d+)", well)
    if not m:
        raise MissionError(f"not a well name: {well!r}")
    return int(m.group(2))


def wells_by_column(wells: list[str]) -> list[list[str]]:
    """`wells` grouped by plate column, columns and wells in the order given."""
    groups: dict[int, list[str]] = {}
    for well in wells:
        groups.setdefault(column_of(well), []).append(well)
    return list(groups.values())


def next_tip(client: Any, rack: str) -> str | None:
    """The well of the rack's next tip as the deck state has it, or None when it does not follow the rack."""
    for line in client.Deck.TipRacks.get():
        if line.startswith(rack + ":"):
            m = _NEXT_TIP.search(line)
            return f"{m.group(1)}{m.group(2)}" if m else None
    return None


def tips_left_in_column(client: Any, rack: str) -> int:
    """Tips left in the column of the rack's next tip (next tip F4 -> 3: F4, G4, H4); 8 when not followed."""
    well = next_tip(client, rack)
    return 8 - ROWS.index(well[0]) if well else 8


class Pipetting:
    """The transfers of one operation. `tips` is a ``TipRack`` value: tip_type, rack, set_next_tip."""

    def __init__(self, step: Step):
        self.step = step

    def _get_tips(self, tips: dict, channels: list[int], label: str) -> None:
        self.step.call(
            "LiquidHandling", "GetTips", tips["tip_type"], channels, tips["rack"],
            label=f"GetTips {tips['tip_type']} ch{channels} from {tips['rack']} ({label})",
        )  # fmt: skip

    def transfer(
        self,
        tips: dict,
        source: str,
        source_well: str,
        volume: float,
        target: str,
        target_wells: list[str],
        liquid_class: str,
        mix_volume: float = 0.0,
        mix_cycles: int = 0,
        mix_liquid_class: str = "",
    ) -> None:
        """One channel, a new tip for every target well."""
        call = self.step.call
        for well in target_wells:
            label = f"{volume} {source} {source_well} -> {target} {well}"
            if tips["set_next_tip"]:
                # "Set Available Tips" makes only the given well available: set it before every GetTips
                nxt = next_tip(self.step.client, tips["rack"])
                if nxt is None:
                    raise MissionError(f"the deck state does not know the next tip of {tips['rack']}")
                call("LiquidHandling", "SetNextTipPosition", tips["rack"], nxt,
                     label=f"SetNextTipPosition {tips['rack']} {nxt}")  # fmt: skip
            self._get_tips(tips, [1], label)
            call("LiquidHandling", "Aspirate", source, [source_well], [volume], liquid_class, [1],
                 label=f"Aspirate {volume} {source} {source_well} ({liquid_class})")  # fmt: skip
            call("LiquidHandling", "Dispense", target, [well], [volume], liquid_class, [1],
                 label=f"Dispense {volume} {target} {well}")  # fmt: skip
            if mix_cycles > 0:
                call("LiquidHandling", "Mix", target, [well], [mix_volume], mix_liquid_class, [1], mix_cycles,
                     label=f"Mix {mix_volume}x{mix_cycles} {target} {well}")  # fmt: skip
            call("LiquidHandling", "DropTips", [1], label="DropTips ch[1]")

    def _rounds(self, tips: dict, target_wells: list[str]):
        """(wells, channels) per GetTips: one plate column at a time, split where the rack's column runs out."""
        for group in wells_by_column(target_wells):
            todo = list(group)
            while todo:
                k = min(len(todo), 8, tips_left_in_column(self.step.client, tips["rack"]))
                wells, todo = todo[:k], todo[k:]
                yield wells, list(range(1, k + 1))

    def transfer_multi(
        self,
        tips: dict,
        source: str,
        source_well: str,
        volume: float,
        target: str,
        target_wells: list[str],
        liquid_class: str,
        mix_volume: float = 0.0,
        mix_cycles: int = 0,
        mix_liquid_class: str = "",
    ) -> None:
        """Several channels: every tip aspirates from the same source well, then dispenses into its well."""
        call = self.step.call
        for wells, ch in self._rounds(tips, target_wells):
            k = len(ch)
            self._get_tips(tips, ch, f"{target} {wells}")
            call("LiquidHandling", "Aspirate", source, [source_well] * k, [volume] * k, liquid_class, ch,
                 label=f"Aspirate {volume} x{k} {source} {source_well} ({liquid_class})")  # fmt: skip
            call("LiquidHandling", "Dispense", target, wells, [volume] * k, liquid_class, ch,
                 label=f"Dispense {volume} {target} {wells}")  # fmt: skip
            if mix_cycles > 0:
                call("LiquidHandling", "Mix", target, wells, [mix_volume] * k, mix_liquid_class, ch, mix_cycles,
                     label=f"Mix {mix_volume}x{mix_cycles} {target} {wells}")  # fmt: skip
            call("LiquidHandling", "DropTips", ch, label=f"DropTips ch{ch}")

    def mix_multi(
        self,
        tips: dict,
        target: str,
        target_wells: list[str],
        mix_volume: float,
        mix_cycles: int,
        mix_liquid_class: str,
    ) -> None:
        """New tips only for mixing, several channels at once."""
        call = self.step.call
        for wells, ch in self._rounds(tips, target_wells):
            k = len(ch)
            self._get_tips(tips, ch, f"mix {target} {wells}")
            call("LiquidHandling", "Mix", target, wells, [mix_volume] * k, mix_liquid_class, ch, mix_cycles,
                 label=f"Mix {mix_volume}x{mix_cycles} {target} {wells}")  # fmt: skip
            call("LiquidHandling", "DropTips", ch, label=f"DropTips ch{ch}")
