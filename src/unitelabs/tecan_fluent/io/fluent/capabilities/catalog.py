"""What the database does not say: the arms, the instruments and how this connector drives them, and the rules a
plan must follow (docs/lab_capabilities_spec.md).

Every entry says where it comes from: "definition" (read from the FluentControl database or the driver settings on
the Fluent PC), "connector" (a limit this connector enforces), "observed" (seen on this instrument; the date is in
the rule) or "inference" (concluded from the definitions, not confirmed on the instrument).
"""

ARMS = [
    {"name": "Air FCA 1", "kind": "pipetting arm", "channels": 8,
     "facts": ["air displacement: only the AirFca part of a liquid class applies",
               "plunger range 1250 uL per channel (service range test, 2025-06-20)",
               "travel X 1172 mm, Y 500 mm, Z 217 mm per channel (same test)"]},
    {"name": "RGA 1", "kind": "plate gripper with exchangeable fingers", "channels": 1,
     "facts": ["fingers Eccentric[001] and Centric[001] in the FES nests; EccentricFingersLong and TubeFingers empty",
               "travel X 1172 mm, Y 477 mm, Z 645 mm, R 360 deg, G 61 mm (service range test, 2025-06-20)"]},
]

# Instruments of the deck: what drives them and which SiLA server of this connector serves them. "part" is the
# component type on the worktable that shows the instrument is there.
INSTRUMENTS = [
    {"name": "Inheco ODTC 96", "kind": "thermal cycler", "part": "Inheco ODTC 96", "locations": ["ODTC_96_Pos"],
     "driver": "SiLA-ODTC (FluentControl external driver)", "connection": "unknown (SiLA 1 device)",
     "servers": ["Tecan Fluent 780 (All devices) :50060", "Inheco ODTC 96 :50061"],
     "features": ["jp.riken.bdr/inheco.odtc/Door/v1", "jp.riken.bdr/inheco.odtc/Methods/v1",
                  "jp.riken.bdr/inheco.odtc/Temperatures/v1"]},
    {"name": "Tecan Infinite 200 PRO", "kind": "plate reader", "part": "Infinite_200_New",
     "locations": ["InfiniteM200_New"], "driver": "Magellan (FluentControl external driver)", "connection": "USB",
     "servers": ["Tecan Fluent 780 (All devices) :50060", "Tecan Infinite 200 PRO :50063"],
     "features": ["jp.riken.bdr/tecan.infinite/Tray/v1", "jp.riken.bdr/tecan.infinite/Absorbance/v1",
                  "jp.riken.bdr/tecan.infinite/PlateHandling/v1"]},
    {"name": "QInstruments BioShake Q1", "kind": "heater shaker", "part": "BioShake Q1",
     "locations": ["BioShake_Q1_Adapter_Site", "BioShake_Q1_Adapter_Site_PCR"],
     "driver": "BioShake3000 (DriverFramework)", "connection": "serial COM3",
     "servers": ["Tecan Fluent 780 (All devices) :50060", "BioShake :50064"],
     "features": ["jp.riken.bdr/qinstruments.bioshake/BioShake/v1"]},
    {"name": "Inheco Incubator Shaker DWP", "kind": "heater shaker (deep well)", "part": "InhecoIncubatorDWP",
     "locations": ["IncDWP_Pos_4"], "driver": "Inheco (DriverFramework)", "connection": "serial COM4, device 2",
     "servers": ["Tecan Fluent 780 (All devices) :50060", "Inheco Shaking Incubator :50065"],
     "features": ["jp.riken.bdr/inheco.incubator/ShakingIncubator/v1"]},
    {"name": "Inheco CPLC (3 positions)", "kind": "cooling / heating plates", "part": "Inheco CPLC Flat",
     "locations": ["CPLC_Flat_Pos", "CPLC_Flat_Pos_PCR"], "driver": "inhecoMTC (FluentControl external driver)",
     "connection": "unknown", "servers": ["Tecan Fluent 780 (All devices) :50060", "Inheco CPLC (3 positions) :50066"],
     "features": ["jp.riken.bdr/inheco.cplc/CoolingHeatingPlates/v1"]},
    {"name": "Incubator1 (6 positions)", "kind": "shaking incubator", "part": "6 Nest Incubator Shaking",
     "locations": ["Incub6Shake_Pos"], "driver": "Incubator1 (FluentControl external driver)",
     "connection": "unknown", "servers": ["Tecan Fluent 780 (All devices) :50060", "Incubator1 (6 positions) :50067"],
     "features": ["jp.riken.bdr/tecan.incubator/Incubator1/v1"]},
    {"name": "Alpaqua Magnum FLX", "kind": "magnet plate (passive)", "part": "Alpaqua Magnum FLX",
     "locations": ["Alpaqua_Magnum_FLX_Pos"], "driver": "", "connection": "", "servers": [], "features": []},
    {"name": "9 Nest Hotel", "kind": "plate and lid hotel (passive)", "part": "9 Nest Hotel",
     "locations": ["HotelMP_Pos"], "driver": "", "connection": "", "servers": [], "features": []},
    {"name": "7mm Regrip Nest", "kind": "regrip station (passive)", "part": "7mm Regrip Nest",
     "locations": ["Regrip_Pos", "Regrip_Pos_PCR"], "driver": "", "connection": "", "servers": [], "features": []},
    {"name": "Centrifuge", "kind": "centrifuge (on the worktable, no driver configured)", "part": "Centrifuge",
     "locations": ["Centrifuge_Pos", "Centrifuge_LoadPos"], "driver": "", "connection": "", "servers": [],
     "features": []},
]

CONSTRAINTS = [
    # Pipetting
    {"id": "one-aspirate-per-tip", "category": "pipetting", "basis": "observed",
     "rule": "A tip aspirates once: a second Aspirate with the same tips fails. One aspiration may be dispensed "
             "several times. Put GetTips / DropTips around every aspiration."},
    {"id": "air-fca-liquid-classes", "category": "pipetting", "basis": "definition",
     "rule": "Only liquid classes with an AirFca part work on this arm, and only for tip groups the AirFca part has "
             "equations for (LiquidClasses lists both). This connector refuses the others."},
    {"id": "volume-per-tip", "category": "pipetting", "basis": "definition",
     "rule": "Keep the volume within the tip's nominal volume and the liquid class's accuracy range for that tip "
             "group (water-like classes: 10 uL tip 0.5-10, 50 uL 1-50, 200 uL 2-200, 1000 uL 5-1000 uL). The plunger "
             "range is 1250 uL per channel, so 5000 uL tips cannot be used."},
    {"id": "short-tips-low-nest", "category": "pipetting", "basis": "observed",
     "rule": "10 uL tips do not reach the bottom of a PCR plate on a 7 mm nest (Nest7mm_Pos); use 50 uL or longer tips "
             "there."},
    {"id": "tip-rack-1000-001", "category": "pipetting", "basis": "observed",
     "rule": "The 1000 uL tips of rack FCA_ 1000ul SBS[001] do not fit; take 1000 uL tips from FCA_ 1000ul SBS[002]."},
    {"id": "pipetting-places", "category": "pipetting", "basis": "inference",
     "rule": "Pipette only at places whose carriers allow the FCA arm (Places: Pipetting=true): deck nests, CPLC, "
             "BioShake and the magnet, not the hotel, ODTC, reader, incubators or centrifuge."},
    # Gripper
    {"id": "gripper-modes", "category": "gripper", "basis": "inference",
     "rule": "The RGA grips a plate in one mode (Narrow, NarrowReverse, Wide, WideReverse) for both ends of a move: "
             "the mode must be allowed at the source and the destination (Places: GripperModes). Otherwise regrip on "
             "Regrip_Pos (Regrip_Pos_PCR for PCR plates) on the way."},
    {"id": "reader-via-regrip", "category": "gripper", "basis": "observed",
     "rule": "Plates go into the Infinite reader through Regrip_Pos (the reader allows Wide only). Only flat-bottom "
             "plates; PCR plates cannot be read in it (2026-10-09). Load, measure and unload in one run."},
    {"id": "pcr-locations", "category": "gripper", "basis": "definition",
     "rule": "Some stations have a separate location for PCR plates on the same carrier: Regrip_Pos_PCR, "
             "CPLC_Flat_Pos_PCR, BioShake_Q1_Adapter_Site_PCR. Use them for PCR plates (Places: Accepts)."},
    {"id": "lid-fixed-site", "category": "gripper", "basis": "observed",
     "rule": "Put lids on with FixedSite=true; with false FluentControl put the lid on another plate of the same "
             "type (2026-10-16)."},
    # Instruments
    {"id": "odtc-premethod-pairs", "category": "instrument", "basis": "observed",
     "rule": "Every ODTC Method needs its PreMethod run just before it (ini4-HeatShock, ini25-test, "
             "ini37-EnzymeReaction, ini42-For * insert, ini95-PCR); a PreMethod takes about 8 minutes whatever the "
             "temperature. Close the door first, and cover the plate (ODTC_Lid or a seal)."},
    {"id": "odtc-forbidden", "category": "instrument", "basis": "observed",
     "rule": "Never send ODTC SetParameters (it takes the device down) or StopMethod (FluentControl refuses it). "
             "During a Method neither the door nor the temperature can be read or changed."},
    {"id": "device-ranges", "category": "instrument", "basis": "connector",
     "rule": "This connector limits BioShake to 4-70 degC and 1000-2000 rpm in steps of 200, the Inheco DWP incubator "
             "to 20-60 degC with one shaking preset, the CPLC to slots 1-3 and 4-70 degC, Incubator1 to 20-50 degC "
             "(all positions) and 1.0-8.5 Hz. These are safety limits of the connector, not device specifications."},
    {"id": "temperature-not-awaited", "category": "instrument", "basis": "observed",
     "rule": "Temperature commands return when sent (about 9 s); they do not wait for the temperature."},
    # FluentControl
    {"id": "one-operation", "category": "fluentcontrol", "basis": "connector",
     "rule": "FluentControl runs one operation at a time for all servers on the Fluent PC (shared lock); HandsOff "
             "blocks every command."},
    {"id": "run-resets-layout", "category": "fluentcontrol", "basis": "observed",
     "rule": "FluentControl puts labware back to the worktable at the start of every run; the Deck state of this "
             "connector is registered at each start. Keep moves of one plan in one run or record them in the Deck "
             "state."},
    {"id": "definitions-checked", "category": "fluentcontrol", "basis": "connector",
     "rule": "Before sending, this connector checks every name used (liquid class, tip, labware, location, site) "
             "against the database and refuses changed definitions until they are accepted (RunControl)."},
]

NOTES = [
    {"id": "connector-rule", "basis": "inference",
     "note": "Accepts is derived from the connector references of site and component templates; FluentControl's "
             "own placement check was not compared with it."},
    {"id": "geometric-volumes", "basis": "definition",
     "note": "Well volumes are computed from the well shapes filled to the top, not nominal volumes; the database "
             "has no nominal volume."},
    {"id": "accuracy-ranges", "basis": "inference",
     "note": "Liquid class volume ranges are the points of their AdjustAccuracy correction; whether FluentControl "
             "refuses volumes outside them was not tested."},
]
