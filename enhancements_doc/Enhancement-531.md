# Enhancement-531: the bug-hunt round — sixteen fixes, one dead transistor

**Scope:** a one-hour adversarial hunt over ngspice + OSDI produced 19
findings; this enhancement fixes the 16 that survived re-verification
(3 were retracted as artifacts of the hunt harness itself — the ledger
records them, because a hunt that cannot retract its own mistakes cannot
be trusted about the rest). One finding was a genuine compiler
miscompilation that had silently killed the industry's most-used MOSFET
model; the rest harden the day-old E-530 Monte-Carlo machinery and the
`alter`/batch/rawfile surface.

**Suites:** [`examples/huntfix_examples/`](../examples/huntfix_examples/)
(new, 12 checks) and [`examples/osdimc_examples/`](../examples/osdimc_examples/)
extended 24 → 29 checks — both solvers. The `compactmodels` suite's
"known finding" pin for the dead BSIM4 flipped to assert conduction. Full
sweep **445/445** ALL OK; cargo fast+slow green (four snapshots verified
to be pure SSA renumbering); 13 CMC models compile zero-warning.

## The headline: a noise line silently killed BSIM4 (compiler)

The compiled `bsim4.va` — 12.6k lines, compiles zero-warning, loads and
runs every analysis cleanly — conducted **exactly zero at every bias**.
The charge model was alive (AC showed a real ~15 fF gate capacitance);
only the channel current was dead. The trail: the model computes a
healthy `Ids = 3.8 mA` and then `cdrain = Ids * Vdseff` with
`Vdseff = 0`, because the *internal* drain saw 0 V while the terminal sat
at 1 V — the `V(d,di) <+ 0.0` collapse of the default `rdsMod = 0` path
existed in the source and in the runtime's own arithmetic, but not in the
compiled topology: no collapse pair, no switch branch, nothing.

The killer was two lines further down:

```verilog
I(di,d) <+ white_noise(4 * `P_K * T * gdpr, "Rd");
```

`hir_lower` defined the branch's `IsVoltageSrc` place on **every**
contribution, last-write-wins. The unconditional noise line — a current
contribution, spelled in the reversed orientation and lowered after the
conditional voltage contribution — reclassified the branch as
never-a-voltage-source. LRM 4.6.4 makes noise functions **zero in every
large-signal analysis**: a noise-only contribution carries no source kind
and must not reclassify anything. The lowering now detects noise-only
right-hand sides (a noise call, possibly negated/scaled/summed with other
noise calls) and preserves the branch's existing classification; a branch
whose *only* contributions are noise is classified exactly as before.

Stock BSIM4 conducts (−1.27 mA at Vgs=Vds=1 V, a clean Vg family,
`rdsmod=1` unchanged); PSP103, BSIMBULK and BSIMSOI are bit-identical to
before; every noise suite passes untouched. Two lessons worth the ink:
the regression corpus only *compiled* bsim4.va — nothing ever simulated
it, which is how a dead flagship model stayed invisible; and the
`compactmodels` suite had actually **pinned the zero as a "known
finding"** — the fix made that check fail into health, which is precisely
what a pinned finding is for.

## E-530 hardening (ngspice)

* **Machine writes no longer recenter Monte-Carlo nominals.** The
  recenter hook lived in the raw parameter setter, so a `.dc` sweep's
  save/restore — and the `sweep` command's, and sensitivity's
  perturbations — permanently shifted a statistical parameter's nominal
  to whatever value was in flight (a random walk seeded by one sweep).
  Recentering moved into a `doset_user` wrapper on the frontend's
  user-facing `alter`/`altermod` sites (wildcards included); the pinned
  check shows a post-sweep draw landing on the exact nominal-0 delta.
* **`reset`/re-source restarts the MC cleanly**: `inp_dodeck` drops the
  nominal table (the CKTcircuit pointer is reused by `reset`, so the old
  identity check could not see the reallocation — entries leaked and a
  heap-address reuse could have matched a stale nominal to a fresh
  device). The pinned check shows baseline-then-identical-trial-2 across
  a `reset`.
* **A failed trial says so in-band**: the range error names the model and
  the offending value ("Parameter rd of 'mm' is out of bounds (value
  -0.489)!") and a once-per-trial notice states that the previous run's
  vectors remain current — a 1000-trial script can no longer silently
  duplicate its last good sample.
* **Draws are checked finite**: a sigma large enough to overflow
  Box–Muller (±inf) is refused with a named warning and the parameter
  stays at nominal — previously only a declared `from` range caught it.

## The alter / batch / rawfile surface (ngspice)

* **`altermod` reaches string parameters** (`@mm[mode] = "quad"` used to
  die with `no such vector "quad"`; there was no runtime route to a
  string parameter at all). A new `if_setparam_string` sets it through
  the ordinary machinery, with `altermod`'s mid-run `CKTtemp`
  propagation.
* **Whole-array altermod gets the truth**: OSDI registers array
  parameters per element, so `@mm[cf] = [ ... ]` now says the array
  parameter is set per element and names the `@mm[cf[0]]` spelling,
  instead of asserting the parameter does not exist two lines above a
  `showmod` that prints it.
* **`alter` refuses non-representable numbers**: `1e400` was stored as
  +inf — a built-in resistor silently became an open circuit (i = 0,
  rc = 0, a perfectly plausible wrong answer) and an OSDI device died in
  convergence noise pointing nowhere near the cause. The deck route
  already refused it; the `doset_user` wrapper now guards every user
  write, scalars and vectors alike.
* **Repeated `run` of a multi-analysis deck keeps all its jobs**: the
  batch epilogue registered `.op`'s `save all` restricted to the OP
  analysis, so the automatic run's AC/tran jobs found no saves and failed
  with "no data saved ...; analysis not run" — the plots silently lost.
  The dot-card save-all is now unrestricted (strictly more data, no lost
  analyses).
* **Rawfile roundtrips keep qualified names**: `write f.raw dc2.i(v1)`
  came back as the unaddressable `i(dc2.i(v1))` — the writer re-wrapped
  a name that already carried the `i(...)` form inside a plot
  qualifier; same for `v(...)`. The E-373 refinement now covers both.
* **`alter` of a model parameter points at the fix**: through a device
  name it said "no such parameter r." — the E-467 message existed only
  for model-name targets; the device-name mirror now says it is a MODEL
  parameter and names the `altermod` spelling.

## Compiler diagnostics (openvaf-r)

* **Attributes on analog-function items parse** — the recovery set handed
  to the attribute parser inside function bodies contained bare IDENT, so
  the attribute NAME aborted the list and `(* desc="..." *) real g;`
  died as `unexpected token '*)'`. Every function-item attribute was
  unwritable; the set now mirrors `STMT_ATTR_RECOVER`.
* **Statistics attributes on a non-parameter warn** — `(* std=25.0 *)`
  on a plain variable (the shadow-variable typo every compact model
  invites) compiled silently and varied nothing under `.option osdimc`.
* **A duplicated table-file abscissa warns** — `{1.0→5, 1.0→7, 2.0→9}`
  was accepted silently with the zero-width segment anchoring
  interpolation oddly; the new `TableFileDupKnot` warning names the file
  and the repeated knot (NaN and empty files were already clean errors).
* The transient-noise `noise_table` warning **prints the user's label**
  instead of the raw `\x1f`-suffixed correlation name E-528 introduced
  (od-verified: the 0x1F control byte reached the terminal).

## Retractions, recorded

F8 ("empty N-line error") and F9 (".disto disagrees 100×") were artifacts
of the hunt harness — a grep pattern that filtered out the message lines,
and a plot-selection mismatch; with explicit `setplot disto1/disto2` both
device paths match an analytic ground truth (pointwise periodic solve +
FFT) to <1 %, and the handbook's stale ".disto not supported" row was
corrected to say so (E-352's `OSDIdisto` has been real for a while). F18
("duplicate attribute drops statistics") was an off-by-one in the fuzz
harness's own test-array — duplicates already resolve last-wins, verified
four ways.
