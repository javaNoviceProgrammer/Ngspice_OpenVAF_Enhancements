# cornerscmd_examples — Enhancement-655

The `corners` command: the analysis at every process corner the loaded
Verilog-A models declare (`(* corner=... *)`, E-654), the nominal `tt`
first, with each `-output` recorded into a `corners<n>` plot on a `corner`
index scale; `-list` names the set, `-nonominal` drops the nominal, and
`-mc N <montecarlo arguments>` runs a montecarlo per corner instead,
recording yield, npass, nsamples and nfailed. A `.option savemc` file gains
a `corner` column with the first cornered row, and a named nominal
(`.option corner=tt`) tags its rows too. The `corner` variable is put back
afterwards.

Run: `python3 verify_cornerscmd.py` (21 checks per solver, both solvers).
