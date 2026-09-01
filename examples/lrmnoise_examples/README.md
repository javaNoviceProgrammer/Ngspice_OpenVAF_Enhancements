# lrmnoise — analysis phases & noise vs. the LRM (Enhancement-528)

An LRM-2023 conformance audit of clause **4.6** found the transient
operating point misreporting its phases, `ac_stim` poisoning `.noise`,
and noise correlation keyed on the wrong thing. This suite pins the
fixes:

- **Table 4-22's TRAN OP column** holds: `analysis("ic")` and
  `analysis("static")` are 1 at the t = 0 operating point (with `tran` 1
  and `dc` 0) and 0 at every timepoint — the bits used to ride ngspice's
  *first accepted timestep*, so the 4.6.1 initial-condition idiom fired
  mid-transient.
- **`analysis("nodeset")`** is 1 exactly while `.nodeset` values are
  enforced (the flag existed in the header and was never set).
- **`ac_stim` matches the running small-signal analysis** (4.6.3): an
  `"ac"`-named stimulus stays out of the `.noise` gain solve (it poisoned
  the input-referred noise 1000×), and `ac_stim("noise")` participates
  there — it could never activate before.
- **Correlation follows the call** (4.6.4.6): one call's output routed
  into two contributions cancels to an exact 0, while two separate calls
  sharing a label read the uncorrelated √2·1e-6 (they cancelled to 0
  before); the label still combines its contributions in the summary
  vector per 4.6.4.1 (1e-18 + 3e-18 report as one 4e-18 entry).

Run `python3 verify_lrmnoise.py` — 17 checks, both solvers.
