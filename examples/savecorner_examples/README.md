# savecorner — every corner run, one row per corner (Enhancement-701)

`.option savecorner[=csv|txt|excel|<name>.<ext>]` is the corner twin of
[`.option savemc`](../savemc_examples/) (E-610): where savemc keys its rows by
trial, this file keys them by **corner**. For every corner run of a circuit
whose Verilog-A models declare process corners
([E-654](../../enhancements_doc/Enhancement-654.md)'s
`(* corner="ss=115, ff=-10%" *)`), one row:

| column | what |
|---|---|
| `corner` | the corner the run was at (`tt` for the nominal) |
| `analysis`, `status` | the run-class command and `ok` / `failed` / `paused` |
| `@<model>[<param>]`, `@<instance>[<param>]` | the value in force of every parameter carrying a `corner` attribute, read off the devices — the corner's value under a corner, the nominal at `tt` |
| the outputs | the `corners -output` values; `writemc`'s (on an `autocorner` combined plot, evaluated on every corner's own plot and put on that corner's row); under `corners -mc N` the montecarlo's `yield`, `npass`, `nsamples`, `nfailed` |

A corner run is a run-class command (`op`, `tran`, the batch `run`, …) that is
not a loop command's sample: a plain run at the deck's `.option corner=<name>`
(or at `tt` without one), each corner of an `.option autocorner` pass, each
corner of the `corners` command. Inside `montecarlo`, `sweep`, `optimize`,
`wcd` and `highsigma` the runs are the loop's samples and make no rows —
`corners -mc N` adds one summary row per corner instead, a drawn parameter's
cell left empty (the row stands for the whole sample), and a `dc` that sweeps
a cornered parameter itself leaves that cell empty as savemc does (E-626).

The file is `corners_<date>_<time>.<ext>` beside the netlist, or the name the
option gives (its directories made, its case kept); `txt` is tab-separated,
`excel` a genuine `.xlsx` whose sheet is `corners`, sharing savemc's writer
and font options — `savecorner_font`, `savecorner_fontsize`,
`savecorner_model` (bold), `savecorner_instance` (regular),
`savecorner_output` (blue), each falling back to the savemc one. One file per
circuit: a `reset` continues it, a different deck starts its own;
`nosavecorner` last turns it off. A circuit no loaded model of which declares
a corner has nothing to record, said once.

```spice
.option savecorner=excel autocorner     * every run at tt and every corner: one row each
.option savecorner=corners.csv          * with `corners -output v(out) gain=v(out)/v(in)`
```

Run `python3 verify_savecorner.py` — 29 checks, both solvers.
