# `lrmvoice_examples` — what a model says, and when it says it

Pins [Enhancement-541](../../enhancements_doc/Enhancement-541.md): the nine
findings of the [2026-09-02 round-3 LRM
audit](../../docs/audits/2026-09-02_LRM-audit-round3.html), every one of them
about the **timing or addressing of a model's output** rather than about a
number it computes.

```
python3 verify_lrmvoice.py
```

**28 checks, both solvers.** Against the previously shipped binaries the suite
scores **11/28** — and the eleven passes are the seven compile checks plus the
four deliberate controls listed below, so every substantive check
discriminates.

## What each model is for

| model | clause | pins |
|---|---|---|
| `lrmvoice_init.va` | 5.2.1, 9.4.6, 9.5.9 | every display task and the file write of an `analog initial` block reach their destination. They reached nothing at all: the block runs on the initial-step iteration, which the deferral treats as superseded, so its output was buffered and dropped. `$debug`/`$info` (immediate path) printed throughout, which is how the block could be shown to have *run*. |
| `lrmvoice_sev.va` | 9.7.3 | `$error`/`$warning`/`$info` fire once per **accepted** iteration. One diode `.op` used to print 21 `$warning` lines walking the unconverged Newton sequence where `$strobe`, on the adjacent line, printed one. |
| `lrmvoice_err.va` | 9.7.3 | `$error` inside an `analog initial` block issues its message and then stops the run — "the simulation shall not proceed past initialization". It used to print and hand the deck a full operating point. |
| `lrmvoice_ctx.va` | 9.7.3 | a severity message reports the simulation time, or the **current** swept value during a `.dc`, or "during initialization". None of the three was reported. |
| `lrmvoice_hsp.va` | 9.18 Table 9-29 | `$angle` composes modulo 360 (200 + 200 → 40), the *Allowed values* column is enforced, and a legal `#(.$mfactor(3))` still applies the full 6.3.6 transform. |
| `lrmvoice_file.va` | 9.5.1, Table 9-24 | multichannel allocation stops at bit 30 (bit 31 is reserved — and is the file-descriptor bit, so the 31st channel used to alias STDIN and swallow its writes), and a file reopened in a different mode is really reopened. |
| `lrmvoice_write.va` | 9.4.1 | several `$write` calls compose **one** line. The per-call instance prefix used to make that impossible, which is the only thing that distinguishes `$write` from `$strobe`. |

The alias rules (LRM 9.20) and the refused `#(.$mfactor(-3))` are checked from
source built inside the script, since they are compile-time diagnostics.

## The four controls

A suite for "output that was missing" is easy to satisfy by making everything
immediate, or by deferring everything. These four checks are what stop that:

* **`@(initial_step)` output is unchanged.** The fix must tag `analog initial`
  as immediate, not tag everything.
* **`$debug` still prints per Newton iteration.** LRM 9.4.6 exempts exactly
  `$debug`; a fix that deferred the whole log would also silence the 21 lines.
* **`#(.$mfactor(3))` still gives −3 mA.** The multiplicity transform is
  untouched; only the illegal value is refused.
* **A plain append with no prior open still appends.** The mode-change reopen
  must not fire on the ordinary path.

`lrmvoice_rw_seed.txt` is the fixture the reopen test reads before rewriting;
`lrmvoice_ctl.txt` and `lrmvoice_rw.txt` are written from it per run and
removed afterwards, so the suite is re-runnable.
