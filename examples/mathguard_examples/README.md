# Enhancement-468 — seven numbers that were wrong

```
python3 verify_mathguard.py
```

57 checks, both linear solvers. No Verilog-A model is needed; every check runs
on built-in devices, one XSPICE code model, and the two expression evaluators.

## What is checked

| # | was | now |
|---|---|---|
| 1 | `psd` total power scaled by the window (1.4999 for a 1 V constant, 3.0 when padded) | 1.000000 for every window and span |
| 2 | `.param {(-2)**1}` = **+2** — the sign of a negative base dropped | −2, and the two evaluators agree |
| 3 | over a nested `.dc`, avg 0.25 / integ 0.5 silently, rms refused | all three refuse and explain; max/min still work |
| 4 | `meas dc` measured a tran or ac plot (an E-467 regression) | refuses again; the device-parameter `.dc` still works |
| 5 | `sens` reported `d1:ikf = nan` on every default diode | 0, with the reason, other entries unchanged |
| 6 | duplicate parameters silent on built-in model cards and instance lines | reported, as they already were for OSDI |
| 7 | XSPICE `limit` with a negative `limit_range` stopped limiting | clamps at the declared limit |

## Why the checks look the way they do

Every check is a **differential** against an oracle that is either analytic (a
constant's mean square is 1, a sine's is A²/2, `(-2)**3` is −8, rms of a ramp is
√⅓) or already in the tree (the same expression through the *other* evaluator,
the same measurement on a *single* sweep, the same analysis under its own name).
A single-deck assertion could pass on a number that is wrong for an unrelated
reason; a differential cannot.

Roughly a third of the checks assert that something did **not** move. Those
carry most of the risk here: the psd change touches a normalisation shared with
the plotted vector, and the duplicate-parameter change now runs on every device
in the tree rather than OSDI alone. So the rectangular-window psd case that was
already exact is pinned bit-for-bit, positive bases are pinned in both
evaluators, and an ordinary deck plus a ten-parameter MOSFET model are pinned
silent.

Two checks exist only to state that two code paths agree with **each other** —
`.param` and a B-source on the same expression. That is the actual defect in
item 2: not that either was unreachable, but that one simulator gave two answers.

## Note

Two candidates found in the same hunt are deliberately **absent**: `sens` does
report instance-valued and source sensitivities (under the bare instance name,
which the original grep missed), and a bare `.probe` does emit a Note. Both are
recorded in `enhancements_doc/Enhancement-468.md`, and item 5's controls pin the
`sens` behaviour that was wrongly called broken.
