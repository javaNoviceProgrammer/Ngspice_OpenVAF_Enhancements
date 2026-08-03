# probeshort_examples — Enhancement-406

A flow probe that **silently shorts the branch it was meant to measure**.

A declared `branch (a,b) br` and the node pair `(a,b)` are **different branches**.
That is correct, and the DAE, the E-400 contribution map and the LRM compliance
notes all agree on it. The trap is what follows: probing the flow of a branch
nothing contributes to makes it an **ideal ammeter** — a 0 V source, supported
since E-36 and documented — so contributing through one spelling and probing
through the other drops an ammeter *in parallel with* the real branch and shorts
it.

The consequence is numeric and was silent:

| model | probe spelling | `i(v1)` |
| --- | --- | --- |
| `ok` | `I(a,mid)` — same as the contribution | −0.5 mA |
| `trap` | `I(br)` — a different branch, same nodes | **−1.0 mA** |

Two 1 kΩ sections in series draw 0.5 mA. With the first shorted they draw 1.0 mA,
rc=0, and before this release no diagnostic at all.

```
python3 examples/probeshort_examples/verify_probeshort.py
```

## What the lint does and does not do

`probe_only_branch_short` (**L023**, warn by default) fires only when a probed
branch has **no contribution of its own** *and* another branch spanning the same
node pair **is** contributed to. It reports; it does not change the semantics,
because the ammeter is a real feature a model may want.

`sense_ok` in `probe_short.va` is that feature used deliberately — a sense branch
nothing else drives, where the short *is* the intended circuit. It must stay
silent, and it does. That is the false positive worth avoiding: **six** probe-only
branches across the shipped corpus rely on the idiom, and a naive "warn on any
probe-only branch" rule would flag all of them.

Swept over every `.va` file this repository ships (640 files), L023 fires **zero**
times, so any future firing is signal.

Suppress with `--allow probe_only_branch_short`, or
`(* openvaf_allow="probe_only_branch_short" *)` on the probing statement or any
enclosing scope; `--deny` makes it an error.

| File | What |
| --- | --- |
| `probe_short.va` | `trap` (reported), `ok` (correct spelling), `sense_ok` (deliberate ammeter) |
| `verify_probeshort.py` | checks the report, the numeric consequence, and the suppression controls |
