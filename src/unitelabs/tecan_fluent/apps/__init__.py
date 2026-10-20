"""Server assemblies (config class, build_features and create_app). Each has its own config class; start one per
process:

    uv run connector start --app unitelabs.tecan_fluent.apps.<app>:create_app -cfg config/<app>.json

| Module | Server | Port |
|---|---|---|
| fluent780_all | Tecan Fluent 780 (All devices); also unitelabs.tecan_fluent:create_app | 50060 |
| odtc | Inheco ODTC (Fluent 780); the stand-alone server is the inheco-odtc repository | 50061 |
| fluent780 | Tecan Fluent 780 (the Fluent itself) | 50062 |
| infinite | Tecan Infinite 200 PRO (through FluentControl) | 50063 |
| bioshake | BioShake | 50064 |
| inheco_incubator | Inheco Shaking Incubator | 50065 |
| cplc | Inheco CPLC (3 positions) | 50066 |
| incubator1 | Incubator1 (6 positions) | 50067 |
| colormix_demo | ColorMix Demo | 50068 |
| infinite_usb | Tecan Infinite 200 PRO (USB, PyLabRobot; create_usb_app) | 50069 |

The UniteLabs CDK assumes a single config class per process, so this package imports none of them (common.py has
the shared parts and no config class).
"""
