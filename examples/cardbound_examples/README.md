# cardbound_examples — Enhancement-643

A netlist number is the double its text names, and a paramset is selected
by its own parameters (IHP hunt B1/B2). ngspice's number parsers computed
`mantissa × 10^exponent` and rounded twice — `1.2` was 1.2000000000000002,
`0.96u` 9.600000000000001e-07 — so a card value at a declared bound was
refused by the model's own range check (`vmax=1.2` against `from [0:1.2]`)
and the paramset selection judged a member's default outside its own range;
the compiler's scaled literals (`1.1u` = 1.1 × 1e-6) had the same ulp. Every
parser now hands the digits and the whole power of ten to strtod as one
number. The selection also reads the `{…}` value sets the compiler writes
(`exclude {0}` used to exclude everything), judges and counts only the
paramset's own parameters (exported as `OSDI_PARAMSET_OWN`, LRM 6.4.2's
last sentence), and a tie names the ranges that would break it.

Run: `python3 verify_cardbound.py` (10 checks per solver, both solvers; 7
fail on the E-642 binaries).
