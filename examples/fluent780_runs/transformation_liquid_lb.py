"""E. coli transformation with liquid LB culture and 60 min recovery (lab protocol 2026-11-12, volumes x 0.75 as in the
colour-water and LB runs; plate culture), on the Fluent 780.

Layout as in lb_contamination_check.py (verified 2026-11-19/20/24):
  B (96 Well Flat_Custom[001], new) Nest7mm_Pos[1] lidded, A (96 Well Flat_Custom[002], new) CPLC_Flat_Pos[3] lidded,
  trough (4 Well SBS Trough[001], new) Nest7mm_Pos[2] lidded:
    A1 = LB 4 ml + ampicillin 4 ul (mixed by hand) for L2-L4, A2 and A3 = LB 12 ml each (no ampicillin), A4 empty.
  Tubes in the POGO on CPLC slot 1 (cooled to 4 C BEFORE the tubes are placed, by a separate short run):
    M=[001] site 1 (JM109 competent cells 100 ul, thawed on ice), C=[002] 5 (empty), DNA1=[003] 9 (pUC18),
    DNA2=[004] 13 (pUC18-GFP), CaCl2=[005] 3, IPTG=[006] 7, SOC=[008] 15 (cold, as decided 2026-11-25).
  1000 ul rack Nest61mm_Pos_1[6] (new, lid off by hand), 200 ul [4] and 50 ul [7] (partly used racks).

Plate A: T1=B2 (pUC18), T2=B4 (pUC18-GFP), I1=D2, I2=D4. Plate B: L1=B2,D2,F2 (C, no ampicillin),
L2=B4,D4,F4 (C, ampicillin), L3=B6,D6,F6 (I1, ampicillin), L4=B8,D8,F8 (I2, ampicillin): LB 196 ul + 4 ul.
The other 84 wells: LB 200 ul without ampicillin (contamination blanks). Lanes: L1 and columns 1-6 from A2, columns 7-12
from A3, L2-L4 from A1.
Reader before culture and the next morning: Abs600.mth and OFML_GFP.mth (fluorescence 485/535 nm, top, optimal gain).

usage:
  python transformation_liquid_lb.py day [--scale S] [--precool-min M]   plate A -> plate B -> reader -> B in
                                                          Incubator1, shaking; the run is LEFT OPEN for the night
  python transformation_liquid_lb.py morning              stop shaking, B out, reader, Incubator1 25 C, end the run
  --precool-min: fixed CPLC wait after the start (default 0: the CPLC is cooled before the tubes are placed)
Stops at the first failure: temperatures back, run ended (the "day" part does not end the run after B is in the
incubator).
"""

import argparse
import atexit
import subprocess
import sys
import time

import runlib
from runlib import (
    CPLC_A_SLOT,
    CPLC_POGO_SLOT,
    MULTI,
    R50,
    R200,
    R1000,
    TR,
    A,
    B,
    T,
    add_lid,
    bioshake_settled,
    c,
    conn,
    drop_mounted_tips,
    hold_factory,
    lid_back,
    lid_to,
    log,
    multi,
    ready,
    simulation,
    tips_left,
    wait,
    xfer,
)

ap = argparse.ArgumentParser()
ap.add_argument("phase", choices=["day", "morning"])
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--precool-min", type=float, default=0.0, help="fixed wait after setting the CPLC slots to 4 C")
ap.add_argument("--skip-liquid", action="store_true", help="simulation only: no aspirate/dispense/mix (see runlib)")
args = ap.parse_args()
SIM = simulation()
if args.skip_liquid and not SIM:
    sys.exit("--skip-liquid is for the simulation only")
runlib.SKIP_LIQUID = args.skip_liquid
hold = hold_factory(args.scale)
CAMERA_SHOT = r"C:\Users\Tecan\OFML\tools\camera_shot.ps1"  # deck camera snapshot script on the Fluent PC
log(f"FluentControl {'SIMULATION' if SIM else 'REAL'} | phase {args.phase} | wait scale {args.scale}")

M, C, DNA1, DNA2, CACL2, IPTG, SOC = T(1), T(2), T(3), T(4), T(5), T(6), T(8)
T1, T2, I1, I2 = "B2", "B4", "D2", "D4"
L = {"L1": ["B2", "D2", "F2"], "L2": ["B4", "D4", "F4"], "L3": ["B6", "D6", "F6"], "L4": ["B8", "D8", "F8"]}
LANE = {col: ("A2" if col <= 6 else "A3") for col in range(1, 13)}  # LB without ampicillin
L_LANE = {"L1": "A2", "L2": "A1", "L3": "A1", "L4": "A1"}  # A1 = LB with ampicillin
L_WELLS = {w for ws in L.values() for w in ws}
RACK_LIDS = [("Rack50_Lid[001]", R50, "Nest7mm_Pos", 3), ("Rack200_Lid[001]", R200, "Nest7mm_Pos", 7)]
racks_open = False
state = {"incubating": False}


def photo(tag):
    try:
        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                CAMERA_SHOT,
                "-Cameras",
                "Right=242701126",
                "-Tag",
                tag,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        ).stdout.strip()
        log(f"photo {tag}: " + (out.splitlines()[0][:150] if out else "no output"))
    except Exception as e:
        log(f"photo {tag} failed: {e}")


def open_racks():
    """50 and 200 ul rack lids off (RGA), for a stretch of pipetting."""
    global racks_open
    if not racks_open:
        for lid, _, loc, site in RACK_LIDS:
            lid_to(lid, loc, site)
        racks_open = True


def close_racks():
    """50 and 200 ul rack lids back on, before a long wait. 200 before 50 (clearance order)."""
    global racks_open
    if racks_open:
        for lid, rack, _, _ in reversed(RACK_LIDS):
            lid_back(u, lid, rack)
        racks_open = False


def settle(target):
    """BioShake within +-0.5 C of the target twice in a row (skipped in the simulation: no real readings)."""
    if SIM:
        log(f"SIMULATION: BioShake {target} C not waited for")
    else:
        bioshake_settled(target)


def a_to(loc, site):
    wait(c.Labware.TransferLabware(A, loc, site), f"A -> {loc}[{site}]")


def measure_b(tag):
    """B lid to the hotel, Abs600 and GFP fluorescence of all 96 wells (B to the reader through Regrip and back),
    lid back."""
    lid_to("PlateB_Lid[001]", "HotelMP_Pos", 3)
    for method in ("Abs600.mth", "OFML_GFP.mth"):
        inst = c.PlateHandling.MeasureWorktablePlate(B, method)
        t0 = time.time()
        while not inst.done:
            if time.time() - t0 > 900:
                sys.exit(f"reader {method} ({tag}) still running after 900 s")
            time.sleep(0.5)
        try:
            r = inst.get_responses()
            log(f"reader {method} ({tag}) done {time.time() - t0:.0f}s")
        except Exception as e:
            if SIM and "Result file" in str(e):  # the simulated reader writes no result file; the transfers did run
                log(f"SIMULATION: reader {method} ({tag}) moved B, no result file")
                continue
            log(f"reader {method} ({tag}) ERROR {str(e)[:400]}")
            sys.exit(1)
        try:
            vals = {v.Well: v.Value for v in r.Result.Values}
            wells = ["A1", "B2", "B4", "B6", "B8", "D2", "D4", "D6", "D8", "H12"]
            log(f"{method} {tag}: " + ", ".join(f"{w}={vals.get(w)}" for w in wells))
        except Exception as e:
            log(f"{method} {tag}: result not parsed ({e})")
    lid_back(u, "PlateB_Lid[001]", B)


def off(name, call):
    try:
        wait(call(), name)
    except SystemExit:
        log(f"cleanup: {name} failed")
    except Exception as e:
        log(f"cleanup: {name} {e}")


def cplc_bioshake_off():
    off("CPLC slot 1 off", lambda: c.CoolingHeatingPlates.TurnOff(CPLC_POGO_SLOT))
    off("CPLC slot 3 off", lambda: c.CoolingHeatingPlates.TurnOff(CPLC_A_SLOT))
    off("BioShake temperature off", lambda: c.BioShake.TemperatureOff())


def end_on_failure():
    """On a failure: temperatures back and the run ended - unless plate B is already incubating (day part done)."""
    try:
        if state["incubating"] or not c.RunControl.RunOpen.get():
            return
        cplc_bioshake_off()
        off("Incubator1 -> 25 C", lambda: c.Incubator1.SetTemperature(25.0))
        drop_mounted_tips()
        try:
            wait(c.RunControl.EndRun(), "EndRun (after a failure)")
        except SystemExit:
            pass
    except Exception as e:
        print("cleanup EndRun", e)


atexit.register(end_on_failure)
u = None

if args.phase == "day":
    # ---- checks before anything moves
    need = {50: 18, 200: 18, 1000: 96}
    for tip, rack in [(50, R50), (200, R200), (1000, R1000)]:
        left = tips_left(rack)
        log(f"tips {tip} ul in {rack}: {left} left, {need[tip]} needed")
        if left < need[tip]:
            sys.exit(f"not enough {tip} ul tips in {rack} (for 1000 ul: place the new rack and set its next tip to A1)")
    t_start = time.time()
    wait(c.RunControl.StartRun(), "StartRun")
    u = conn()
    for slot in (CPLC_POGO_SLOT, CPLC_A_SLOT):
        wait(c.CoolingHeatingPlates.SetTemperature(slot, 4.0), f"CPLC slot {slot} -> 4 C")
    wait(c.BioShake.SetTemperature(42.0), "BioShake -> 42 C")
    wait(c.Incubator1.SetTemperature(37.0), "Incubator1 -> 37 C")
    hold(args.precool_min * 60, "CPLC cooling to 4 C (fixed wait: its temperature cannot be read)")
    for n, typ, holder in [
        ("PlateA_Lid[001]", "Lid_9mm_Custom", A),
        ("PlateB_Lid[001]", "Lid_9mm_Custom", B),
        ("TroughLid[001]", "Lid_9mm", TR),
        ("Rack50_Lid[001]", "Lid_DiTiFCA", R50),
        ("Rack200_Lid[001]", "Lid_DiTiFCA", R200),
    ]:
        add_lid(u, n, typ, holder)

    # ---- W01-W03: A lid off, DNA, CaCl2 -> M
    lid_to("PlateA_Lid[001]", "HotelMP_Pos", 2)
    open_racks()
    xfer(50, DNA1, "A1", 3.75, A, T1, label="W02 DNA1 3.75 -> T1")
    xfer(50, DNA2, "A1", 3.75, A, T2, label="W02 DNA2 3.75 -> T2")
    xfer(200, CACL2, "A1", 100, M, "A1", mix=(100, 4), label="W03 CaCl2 100 -> M, mix 100x4 (same tip)")
    close_racks()
    hold(5 * 60, "W04 M at 4 C after mixing")
    # ---- W05-W06: M -> T, lid on A, 10 min at 4 C
    open_racks()
    xfer(50, M, "A1", 37.5, A, T1, mix=(20, 4), label="W05 M 37.5 -> T1, mix 20x4")
    xfer(50, M, "A1", 37.5, A, T2, mix=(20, 4), label="W05 M 37.5 -> T2, mix 20x4")
    t_mix = time.time()
    lid_back(u, "PlateA_Lid[001]", A)
    close_racks()
    hold(
        max(0.0, 10 * 60 - (time.time() - t_mix) / args.scale) if args.scale else 0,
        "W06 A lidded at 4 C from the last mix",
    )
    # ---- W07-W08: 42 C for 60 s, back to 4 C for 120 s
    settle(42.0)
    a_to("BioShake_Q1_Adapter_Site", 1)  # the BioShake locks the plate itself when it is placed
    wait(c.BioShake.LockPlate(), "W07 BioShake LockPlate (check)")
    hold(60, "W07 42 C from the lock")
    wait(c.BioShake.UnlockPlate(), "W08 BioShake UnlockPlate")
    a_to("CPLC_Flat_Pos", 3)
    t_back = time.time()
    wait(c.BioShake.SetTemperature(37.0), "W08 BioShake -> 37 C (A is out)")
    hold(max(0.0, 120 - (time.time() - t_back) / args.scale) if args.scale else 0, "W08 A at 4 C from placing it")
    # ---- W09: SOC 150 to each T with mix
    lid_to("PlateA_Lid[001]", "HotelMP_Pos", 2)
    open_racks()
    xfer(200, SOC, "A1", 150, A, T1, mix=(100, 4), label="W09 SOC 150 -> T1, mix 100x4")
    xfer(200, SOC, "A1", 150, A, T2, mix=(100, 4), label="W09 SOC 150 -> T2, mix 100x4")
    lid_back(u, "PlateA_Lid[001]", A)
    close_racks()
    # ---- W10-W11: 37 C, 60 min on the BioShake (no shaking); M -> C during the stay
    settle(37.0)
    a_to("BioShake_Q1_Adapter_Site", 1)
    wait(c.BioShake.LockPlate(), "W10 BioShake LockPlate (check)")
    t_w10 = time.time()
    open_racks()
    xfer(200, M, "A1", 50, C, "A1", label="W11 M 50 -> C (while A is on the BioShake)")
    close_racks()
    hold(max(0.0, 60 * 60 - (time.time() - t_w10) / args.scale) if args.scale else 0, "W10 37 C from the lock")
    # ---- W12-W13: A back to CPLC 3, IPTG, T -> I
    wait(c.BioShake.UnlockPlate(), "W12 BioShake UnlockPlate")
    a_to("CPLC_Flat_Pos", 3)
    lid_to("PlateA_Lid[001]", "HotelMP_Pos", 2)
    open_racks()
    xfer(50, IPTG, "A1", 22.5, A, I1, label="W12 IPTG 22.5 -> I1")
    xfer(50, IPTG, "A1", 22.5, A, I2, label="W12 IPTG 22.5 -> I2")
    xfer(200, A, T1, 75, A, I1, mix=(50, 4), label="W13 T1 75 -> I1, mix 50x4")
    xfer(200, A, T2, 75, A, I2, mix=(50, 4), label="W13 T2 75 -> I2, mix 50x4")

    # ---- plate B: lids off; direct 84 wells column by column (1 -> 12), one new 1000 ul tip per well
    lid_to("PlateB_Lid[001]", "HotelMP_Pos", 3)
    lid_to("TroughLid[001]", "HotelMP_Pos", 4)
    for col in range(1, 13):
        wells = [f"{r}{col}" for r in "ABCDEFGH" if f"{r}{col}" not in L_WELLS]
        # channels spread evenly: a column with L wells (rows B, D, F) is done as A, C, E, G (18 mm) and then H
        groups = (
            [wells] if len(wells) == 8 else [[w for w in wells if w[0] in "ACEG"], [w for w in wells if w[0] == "H"]]
        )
        for g in groups:
            multi(1000, TR, LANE[col], 200, B, g, lc=MULTI, label=f"B direct col {col}: LB 200 from {LANE[col]}")
    # L wells: LB 196 (rows B, D, F of one column at once), then 4 ul from C / I1 / I2 and a new 200 ul tip mix
    for name in ("L1", "L2", "L3", "L4"):
        multi(1000, TR, L_LANE[name], 196, B, L[name], lc=MULTI, label=f"B {name}: LB 196 from {L_LANE[name]}")
    src = {"L1": (C, "A1"), "L2": (C, "A1"), "L3": (A, I1), "L4": (A, I2)}
    for name in ("L1", "L2", "L3", "L4"):
        for w in L[name]:
            xfer(50, src[name][0], src[name][1], 4, B, w, label=f"B {name} 4 -> {w}")
        multi(200, None, None, None, B, L[name], mix=(100, 4), label=f"B {name}: new 200 ul tips, mix 100x4")
    # lids back, plate A work done: CPLC and BioShake off
    lid_back(u, "PlateA_Lid[001]", A)
    lid_back(u, "PlateB_Lid[001]", B)
    lid_back(u, "TroughLid[001]", TR)
    close_racks()
    cplc_bioshake_off()
    log(f"pipetting done in {(time.time() - t_start) / 60:.1f} min")

    # ---- before culture: photo, Abs600 of all wells; then B lidded into Incubator1, 37 C, 5 Hz
    photo("TF_B_before")
    measure_b("before culture")
    ready()
    wait(c.PlateTransfer.MoveLabware(B, "Regrip_Pos", 1), "B -> Regrip_Pos[1]")
    wait(c.PlateTransfer.MoveLabware(B, "Incub6Shake_Pos", 1), "B -> Incub6Shake_Pos[1]")
    wait(c.Incubator1.CloseDoor(), "Incubator1 CloseDoor")
    wait(c.Incubator1.StartShaker(5.0), "Incubator1 StartShaker 5 Hz")
    state["incubating"] = True
    log(
        f"B IS INCUBATING (37 C, 5 Hz) since {time.strftime('%Y-%m-%d %H:%M:%S')}. The run stays open over night; "
        "next morning: python transformation_liquid_lb.py morning"
    )

else:  # morning
    if not c.RunControl.RunOpen.get():
        sys.exit(
            "the run of the day part is not open: re-register B with its lid first "
            "(RemoveLabware, AddLabware HasLid=True)"
        )
    u = conn()
    state["incubating"] = True  # on a failure here, keep the run (and B's lid registration) for a manual decision
    ready()
    wait(c.Incubator1.StopShaker(), "Incubator1 StopShaker")
    log(f"SHAKING STOPPED {time.strftime('%Y-%m-%d %H:%M:%S')}")
    wait(c.PlateTransfer.MoveLabware(B, "Regrip_Pos", 1), "B -> Regrip_Pos[1]")
    wait(c.PlateTransfer.MoveLabware(B, "Nest7mm_Pos", 1), "B -> Nest7mm_Pos[1]")
    wait(c.Incubator1.CloseDoor(), "Incubator1 CloseDoor")
    photo("TF_B_after")
    measure_b("after culture")
    wait(c.Incubator1.SetTemperature(25.0), "Incubator1 -> 25 C")
    wait(c.RunControl.EndRun(), "EndRun")
    log(f"DONE; state {c.Status.FluentControlState.get()} dialogs {c.Status.ActiveDialogs.get()}")
