"""Run Fluent 780 workflows from labcode (the ofplang lab runner) through the Tecan Fluent connector.

- ``steps``: what the environment scripts call to send a command inside the mission's FluentControl run.
- ``manager``: the run manager that opens the run, runs ``lc run`` and ends the run.
- ``mission``: the mission directory shared by both.
"""
