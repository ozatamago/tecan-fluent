# Fluent 780 run scripts

Serial Python scripts that drive whole lab runs through the "Tecan Fluent 780 (All devices)" SiLA2 server
(`fluent780_all`). Each step is sent, waited for and printed with its time; the first failure stops the script,
switches the temperatures back and ends the FluentControl run. They are written for the RIKEN BDR Fluent 780 and its
worktable `WT2411004293_Ver.0.5_OFML`; positions and labware labels are in each script's docstring.

| Script | Run |
|---|---|
| `colour_water_w01_w21.py` | Colour-water run-through W01-W21 (plate A temperature steps, plate B, Incubator1, reader). Ran on the instrument on 2026-11-19. |
| `lb_contamination_check.py` | LB contamination check: the same transfer paths with LB, all 96 wells of plate B, overnight culture, OD600 before and after. `day` leaves the run open over night; `morning` ends it. |
| `transformation_liquid_lb.py` | E. coli transformation with liquid LB culture (lab protocol of 2026-11-12, volumes x 0.75, plate culture): ampicillin LB in trough lane A1, Abs600 and GFP fluorescence (`OFML_GFP.mth`) before and after the overnight culture. Same `day` / `morning` parts as the LB check. |
| `runlib.py` | Shared helpers: SiLA client, waiting, single and multi-channel transfers, lids, BioShake temperature. |

## Running

On the Fluent PC, with FluentControl running (real or `-sim`), the UniteLabs FluentControl connector and the
`fluent780_all` server started:

```
set FLUENT_SILA_HOST=127.0.0.1
set FLUENT_SILA_PORT=50060
python colour_water_w01_w21.py --scale 0.02     # short waits, for a simulation pass
python lb_contamination_check.py day
python lb_contamination_check.py morning
```

Before a run: check the deck with the cameras (hotel first), the deck state of the server (`Deck.Layout`,
`Deck.TipRacks`) and that FluentControl shows no dialog.

## What the runs taught

- After a run, every temperature it switched on goes back: CPLC slots off, BioShake off, Incubator1 to 25 C.
- The CPLC (inhecoMTC) temperature cannot be read with the installed driver configuration: the scripts wait a fixed
  time after setting 4 C.
- The BioShake overshoots when it cools (42 -> 37 C dips to about 35.6 C): plates are placed only after two readings in
  a row within +-0.5 C.
- The RGA cannot reach the lid of a 1000 ul tip rack on a 61 mm nest (Z out of range): that lid is taken off by hand.
- A lid cannot be registered on a plate inside Incubator1 in a new run (collision check): the LB run stays open over
  night.
