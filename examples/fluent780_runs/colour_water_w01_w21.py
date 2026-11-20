"""Colour-water run-through W01-W21 (lab protocol "colour-water run-through" v1.2, 2026-11-14), on the layout
verified on the real Fluent 780 on 2026-11-19. Ran on the real instrument on 2026-11-19 (17:21-17:57).

  B (96 Well Flat_Custom[001]) Nest7mm_Pos[1] lidded, trough (4 Well SBS Trough[001]) Nest7mm_Pos[2] lidded,
  A (96 Well Flat_Custom[002]) CPLC_Flat_Pos[3] lidded, tubes in the POGO on CPLC slot 1 (M=[001] site 1, C=[002] 5,
  DNA1=[003] 9, DNA2=[004] 13, CaCl2=[005] 3, IPTG=[006] 7, SOC=[008] 15 - SOC stays in the cooled POGO),
  50 ul rack Nest61mm_Pos_1[7], 200 ul rack [4], 1000 ul rack [6] (lid off by hand).
  Lid parking: A lid -> HotelMP_Pos[2], B lid -> [3], trough lid -> [4], 50 ul lid -> Nest7mm_Pos[3], 200 ul lid -> [7].

Differences from the protocol (agreed 2026-11-19): positions above; SOC in POGO site 15; tip-rack lids parked on
7 mm nests; the reader reads Abs600.mth and OFML_Abs405.mth.

usage: python colour_water_w01_w21.py [--scale S] [--precool-min M]
  --scale S   multiply every fixed wait by S (1 = protocol times; e.g. 0.02 for a dry/simulation pass)
Stops at the first failure; the temperatures are switched back and the run is ended. Every step is printed
with its time.
"""

import argparse
import atexit
import subprocess
import sys
import time

from runlib import (
    CPLC_A_SLOT,
    CPLC_POGO_SLOT,
    MULTI,
    R50,
    R200,
    TR,
    A,
    B,
    T,
    add_lid,
    c,
    conn,
    hold_factory,
    lid_back,
    lid_to,
    log,
    multi,
    simulation,
    temp_of,
    wait,
    xfer,
)

ap = argparse.ArgumentParser()
ap.add_argument("--scale", type=float, default=1.0)
ap.add_argument("--precool-min", type=float, default=10.0, help="fixed wait after setting the CPLC slots to 4 C")
args = ap.parse_args()
SCALE = args.scale

SIM = simulation()
CAMERA_SHOT = r"C:\Users\Tecan\OFML\tools\camera_shot.ps1"  # deck camera snapshot script on the Fluent PC
print("FluentControl:", "SIMULATION" if SIM else "REAL", "| wait scale", SCALE, flush=True)
if not SIM and SCALE != 1.0:
    print("NOTE: shortened waits on the real instrument (flow check only, not the protocol times)", flush=True)

M, C, DNA1, DNA2, CACL2, IPTG, SOC = T(1), T(2), T(3), T(4), T(5), T(6), T(8)
T1, T2, I1, I2 = "B6", "B8", "D6", "D8"  # plate A wells (shifted 2026-11-19 17:2x: B2/B4/D2/D4 used by the 16:16 run)
# plate B shifted to unused columns (columns 2, 3, 4, 6, 8, 12 were used by the 16:16 run, A11/A12 on 11/18)
L = {"L1": ["B1", "D1", "F1"], "L2": ["B5", "D5", "F5"], "L3": ["B7", "D7", "F7"], "L4": ["B9", "D9", "F9"]}
N = ["C1", "E1", "C5", "E5", "C7", "E7", "C9", "E9", "B10", "D10", "F10", "H11"]  # plate B, water only

hold = hold_factory(SCALE)


def bioshake_until(target, above, timeout_s=1800):
    """Wait until the BioShake reading is >= target (above) or <= target; reading from its serial log."""
    t0 = time.time()
    while True:
        try:
            t = temp_of(wait(c.BioShake.ReadTemperature(), "BioShake.ReadTemperature", limit=180))
        except SystemExit:
            raise
        log(f"BioShake {t:.2f} C (target {'>=' if above else '<='} {target})")
        if (t >= target) if above else (t <= target):
            return t
        if time.time() - t0 > timeout_s:
            log("BioShake temperature not reached in time")
            sys.exit(4)
        time.sleep(30 if not SIM else 2)


def a_to(loc, site):
    wait(c.Labware.TransferLabware(A, loc, site), f"A -> {loc}[{site}]")


def temperatures_back():
    """Switch every temperature this run turned on back off (2026-11-20 user: after a run, back to the original
    temperature or off): CPLC slots 1 and 3 off, BioShake off, Incubator1 to 25 C (as Tecan's Sub_Cleanup)."""
    for name, call in [
        ("CPLC slot 1 off", lambda: c.CoolingHeatingPlates.TurnOff(CPLC_POGO_SLOT)),
        ("CPLC slot 3 off", lambda: c.CoolingHeatingPlates.TurnOff(CPLC_A_SLOT)),
        ("BioShake temperature off", lambda: c.BioShake.TemperatureOff()),
        ("Incubator1 -> 25 C", lambda: c.Incubator1.SetTemperature(25.0)),
    ]:
        try:
            wait(call(), name)
        except SystemExit:
            print("cleanup:", name, "failed", flush=True)
        except Exception as e:
            print("cleanup:", name, e, flush=True)


def end_on_failure():
    try:
        if c.RunControl.RunOpen.get():
            temperatures_back()
            try:
                wait(c.RunControl.EndRun(), "EndRun (after a failure)")
            except SystemExit:
                pass
    except Exception as e:
        print("cleanup EndRun", e)


atexit.register(end_on_failure)

t_start = time.time()
# ---- W01: run, lids registered, rack lids and A lid parked
wait(c.RunControl.StartRun(), "W01 StartRun")
u = conn()
# temperatures (no motion; device macros need the open run): CPLC 4 C, BioShake 42 C, Incubator1 37 C
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
lid_to("Rack50_Lid[001]", "Nest7mm_Pos", 3)
lid_to("Rack200_Lid[001]", "Nest7mm_Pos", 7)
lid_to("PlateA_Lid[001]", "HotelMP_Pos", 2)

# ---- W02-W05 (plate A at CPLC 3, 4 C)
xfer(50, DNA1, "A1", 3.75, A, T1, label="W02 DNA1 3.75 -> T1")
xfer(50, DNA2, "A1", 3.75, A, T2, label="W02 DNA2 3.75 -> T2")
xfer(200, CACL2, "A1", 100, M, "A1", mix=(100, 4), label="W03 CaCl2 100 -> M, mix 100x4 (same tip)")
hold(5 * 60, "W04 M on the cold position after mixing")
xfer(50, M, "A1", 37.5, A, T1, mix=(20, 4), label="W05 M 37.5 -> T1, mix 20x4")
xfer(50, M, "A1", 37.5, A, T2, mix=(20, 4), label="W05 M 37.5 -> T2, mix 20x4")
# ---- W06: lid on A, 10 min at 4 C
lid_back(u, "PlateA_Lid[001]", A)
hold(10 * 60, "W06 A lidded at 4 C after the last mix")
# ---- W07: BioShake 42 C reached -> A on, lock, 60 s
bioshake_until(41.5, above=True)
a_to("BioShake_Q1_Adapter_Site", 1)
wait(c.BioShake.LockPlate(), "W07 BioShake LockPlate")
hold(60, "W07 heat (42 C) from lock")
# ---- W08: unlock, A back to CPLC 3, 120 s; BioShake -> 37 C after A is out
wait(c.BioShake.UnlockPlate(), "W08 BioShake UnlockPlate")
a_to("CPLC_Flat_Pos", 3)
wait(c.BioShake.SetTemperature(37.0), "W08 BioShake -> 37 C (after A is out)")
hold(120, "W08 A at 4 C from placing it")
# ---- W09: A lid off, SOC 150 to each T with mix
lid_to("PlateA_Lid[001]", "HotelMP_Pos", 2)
xfer(200, SOC, "A1", 150, A, T1, mix=(100, 4), label="W09 SOC 150 -> T1, mix 100x4")
xfer(200, SOC, "A1", 150, A, T2, mix=(100, 4), label="W09 SOC 150 -> T2, mix 100x4")
# ---- W10: lid on, A to BioShake (37 C command only - the 60 min recovery is done in the LB overnight run, user
# 2026-11-19), lock; W11 during the stay; no wait for 37 C and no 60 min hold
lid_back(u, "PlateA_Lid[001]", A)
wait(c.BioShake.SetTemperature(37.0), "W10 BioShake -> 37 C (command only)")
a_to("BioShake_Q1_Adapter_Site", 1)
wait(c.BioShake.LockPlate(), "W10 BioShake LockPlate")
xfer(200, M, "A1", 50, C, "A1", label="W11 M 50 -> C (while A is on the BioShake)")
# ---- W12: unlock, A back to CPLC 3, lid off, IPTG 22.5 to I1/I2
wait(c.BioShake.UnlockPlate(), "W12 BioShake UnlockPlate")
a_to("CPLC_Flat_Pos", 3)
lid_to("PlateA_Lid[001]", "HotelMP_Pos", 2)
xfer(50, IPTG, "A1", 22.5, A, I1, label="W12 IPTG 22.5 -> I1")
xfer(50, IPTG, "A1", 22.5, A, I2, label="W12 IPTG 22.5 -> I2")
# ---- W13: T -> I 75 with mix
xfer(200, A, T1, 75, A, I1, mix=(50, 4), label="W13 T1 75 -> I1, mix 50x4")
xfer(200, A, T2, 75, A, I2, mix=(50, 4), label="W13 T2 75 -> I2, mix 50x4")
# ---- W14-W16: plate B (lid and trough lid parked)
lid_to("PlateB_Lid[001]", "HotelMP_Pos", 3)
lid_to("TroughLid[001]", "HotelMP_Pos", 4)
# W14: N wells, one column at a time with several channels (wells of one column are 18 mm apart, channels spread)
N_BY_COLUMN = [["C1", "E1"], ["C5", "E5"], ["C7", "E7"], ["C9", "E9"], ["B10", "D10", "F10"], ["H11"]]
assert sorted(w for g in N_BY_COLUMN for w in g) == sorted(N)
for group in N_BY_COLUMN:
    multi(1000, TR, "A1", 200, B, group, lc=MULTI, label="W14 trough A1 200 -> N")
# W15: each L condition is one column (B, D, F rows): 3 channels at once
multi(1000, TR, "A1", 196, B, L["L1"], lc=MULTI, label="W15 trough A1 196 -> L1")
for name in ("L2", "L3", "L4"):
    multi(1000, TR, "A2", 196, B, L[name], lc=MULTI, label=f"W15 trough A2 196 -> {name}")
# W16: 4 ul from the tube (one source, one channel per well), then the three wells mixed at once with new 200 ul tips
src = {"L1": (C, "A1"), "L2": (C, "A1"), "L3": (A, I1), "L4": (A, I2)}
for name in ("L1", "L2", "L3", "L4"):
    for w in L[name]:
        xfer(50, src[name][0], src[name][1], 4, B, w, label=f"W16 {name} 4 -> {w}")
    multi(200, None, None, None, B, L[name], mix=(100, 4), label=f"W16 {name}: new 200 tips, mix 100x4")
# ---- W17: photo of B (no motion)
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
            "W17_plateB",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    ).stdout.strip()
    log("W17 photo: " + out.splitlines()[0][:150] if out else "W17 photo: no output")
except Exception as e:
    log(f"W17 photo failed: {e}")
# ---- W18: lids back on A and B (trough lid too)
lid_back(u, "PlateA_Lid[001]", A)
lid_back(u, "PlateB_Lid[001]", B)
lid_back(u, "TroughLid[001]", TR)
# ---- W19-W21: lidded B through Incubator1, 5 Hz 10 s
wait(c.PlateTransfer.MoveLabware(B, "Regrip_Pos", 1), "W19 B -> Regrip_Pos[1]")
wait(c.PlateTransfer.MoveLabware(B, "Incub6Shake_Pos", 1), "W19 B -> Incub6Shake_Pos[1]")
wait(c.Incubator1.CloseDoor(), "W19 Incubator1 CloseDoor")
wait(c.Incubator1.StartShaker(5.0), "W20 StartShaker 5 Hz")
time.sleep(10)
wait(c.Incubator1.StopShaker(), "W20 StopShaker (10 s)")
wait(c.PlateTransfer.MoveLabware(B, "Nest7mm_Pos", 1), "W21 B -> Nest7mm_Pos[1]")
wait(c.Incubator1.CloseDoor(), "W21 Incubator1 CloseDoor")
# ---- 2.6 reader: B lid off, Abs600 and OFML_Abs405, lid back
lid_to("PlateB_Lid[001]", "HotelMP_Pos", 3)
for method in (
    "OFML_Abs405.mth",
    "Abs600.mth",
):  # Abs600 writes its .asc to C:\\FluentData\\00_A600_Result\\ASC (read by hand)
    inst = c.PlateHandling.MeasureWorktablePlate(B, method)
    while not inst.done:
        time.sleep(0.5)
    try:
        r = inst.get_responses()
        log(f"reader {method} done")
    except Exception as e:
        if "Result file" in str(e) and "not found" in str(e):
            log(f"reader {method}: measured, result file not where the server looks (read by hand): {str(e)[:160]}")
            continue
        log(f"reader {method} ERROR {str(e)[:400]}")
        sys.exit(1)
    try:
        vals = {v.Well: v.Value for v in r.Result.Values if v.Label == r.Result.Labels[0]}
        log(f"{method}: " + ", ".join(f"{w}={vals.get(w)}" for w in L["L1"] + L["L2"] + L["L3"] + L["L4"] + N[:3]))
    except Exception as e:
        log(f"{method}: result not parsed ({e})")
lid_back(u, "PlateB_Lid[001]", B)
# ---- end: rack lids back, BioShake off, run ended
lid_back(u, "Rack200_Lid[001]", R200)  # 200 before 50 (clearance order)
lid_back(u, "Rack50_Lid[001]", R50)
temperatures_back()
wait(c.RunControl.EndRun(), "EndRun")
minutes = (time.time() - t_start) / 60
log(
    f"ALL STEPS DONE in {minutes:.1f} min; "
    f"state {c.Status.FluentControlState.get()} dialogs {c.Status.ActiveDialogs.get()}"
)
