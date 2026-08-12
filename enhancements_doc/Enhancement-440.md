# Enhancement-440 — `sens` left the circuit altered, and five things went unsaid

A sensitivity analysis is supposed to be a measurement. This one changed what it
measured, permanently, without saying so.

```
                    before          after `sens v(nb)`
  v(nb)             4.432965241196  4.999999907        <- 12.8% wrong
  the transistor    conducting      dead
  diagnostic        --              none
```

Every later analysis in the session — the next `op`, the next `dc` sweep — solved
the altered circuit. A BJT differential pair came back **101%** wrong. Only
`reset` cleared it.

Alongside it, five input paths that accepted values their siblings rejected, and
one defect in Enhancement-438's own diagnostic.

## The sensitivity defect

`sens` computes each derivative by perturbing a parameter, reloading, and writing
the original value back. That restores the *number*. It does not restore the
model's **given** state: every device setter marks its parameter as supplied, and
no device API offers an un-set.

For a model whose behaviour is selected by whether a parameter was given rather
than by its value, the model is left reinterpreted. `bjttemp.c`:

```c
if ((model->BJTBEsatCurGiven) && (model->BJTBCsatCurGiven)) {
    here->BJTBEtSatCur = here->BJTarea * model->BJTBEsatCur * factor;  /* ibe */
} else {
    here->BJTBEtSatCur = here->BJTtSatCur;                             /* is  */
}
```

`ibe` and `ibc` default to 0 and ungiven, so an ordinary BJT takes the `else`
branch and derives its junction saturation currents from `is`. `sens` set them —
to their own value, 0 — and both flags became TRUE for good. From then on
`BJTBEtSatCur` was **0**: a transistor with no saturation current at all.

### How it was found

Four properties, measured before any code was read, said this was leftover state
rather than a numerical accident:

* **Not a tolerance artifact.** The error was bit-identical at `reltol` 1e-3 and
  1e-12. A convergence-path difference shrinks; this did not move.
* **Not a stale initial guess.** Adding `.nodeset v(nb)=4.4` did not change the
  wrong answer, and `sens` run *first*, before any other analysis, corrupted just
  the same.
* **Device-specific.** BJT 12.8–101%, diode 1.7e-7, and MOS, JFET, MESFET,
  linear and OSDI devices exactly zero. Only the BJT has this dual-mode
  parameter pair.
* **One command out of twenty.** `alter`, `altermod`, `sweep`, `montecarlo`,
  `optimize`, `tf`, `pz`, `disto`, `noise`, `hb`, `pss` and `sp` all restored
  perfectly against the same probe. `sens` was alone.

The mechanism came from bisecting the perturbation loop behind an environment
switch — the lesson recorded in Enhancement-439, that a patched path which does
not move the number is not the live path. Skipping the whole loop was clean;
skipping the perturbation, the perturbed load, or the post-perturbation
`sens_temp` individually all still corrupted. Skipping every `sens_setp` was
clean. That isolated it to the setter, and the surprise was that setting a
parameter to **its own current value** was enough — no perturbation required.

A per-parameter sweep then showed no single parameter was responsible: the
threshold sat at the fourth, `ibc`, and `ibc` alone was harmless. It needed
`ibe` *and* `ibc` — which is exactly the `&&` above.

### The fix

Snapshot every model struct before the perturbation loop; restore them
afterwards; re-run `CKTtemp()` so each instance's derived values are rebuilt from
the restored models. Instances are deliberately not snapshotted — they are
recomputed, not remembered.

This is generic rather than BJT-specific on purpose. The hazard is not the BJT;
it is that a setter can change a model's *interpretation* and the analysis has no
way to put that back. Any device with a given-flag branch has it.

`DEVmodSize` and `ckt->CKThead[]` make the walk device-agnostic, and the restore
runs on the error paths too — a half-finished perturbation loop is exactly when
the models are most likely to be left altered.

## The five unchecked inputs

Each was found by asking whether the siblings already did this. In every case all
but one of a family behaved correctly.

**`pss` validated none of its numeric arguments.** `tran`, `ac`, `dc`, `hb`, `sp`
and `noise` each reject a negative or inverted argument and name the value.
A negative `stabtime` sets `CKTfinalTime` behind the current time, so the
stabilization transient integrates toward a final time it has already passed:
`pss 1k -1m 0 1024 5 50 1u` ran **past 100 seconds** with no output and no
diagnostic. Enhancement-348 had guarded `fguess`, `points` and `harmonics` in
this same function; `stabtime`, `sc_iter` and `steady_coeff` were the three it
did not reach.

**`.meas` accepted an inverted window.** Because `m_to == 0.0` doubles as "no
upper limit", `FROM=1m TO=0` did not measure nothing — it measured `[1m, end]`
and returned a confident number for a window nobody asked for. The parser now
records whether each bound was actually written, which is what makes an explicit
`TO=0` distinguishable from an absent one. A `dc` sweep may legitimately run
downward, so there the window is still normalised rather than refused — but it
now says that it did.

**`pow(0,-1)` and `0**-1` returned a raw infinity.** Every other singular case in
`ptfuncs.c` is clamped to `HUGE`, which `ifeval.c` turns into a named error:
`x/0`, `sqrt(-x)`, `log(0)`, and `pwr(0,-1)` since Enhancement-256. These two
were the exceptions, so an infinity reached the matrix, the operating point
reported success, and a transient carried it through to `maximum(v(nb)) = inf`.
They now behave exactly as `pwr` does.

An expression that merely *overflows* — `v='1e300*1e300'` — is now reported but
deliberately **not** clamped. Unlike the singular cases there is no defensible
finite substitute for arbitrary user arithmetic, and inventing one would change
results that today are only reported. The silence was the defect.

**The temperature guard was one-sided.** Enhancement-426 refused temperatures at
or below absolute zero. Above, nothing was checked at all, and `.temp 1e6` was
accepted in silence — a plain diode divider then answered -2.7e-15 V. A high
temperature is not impossible the way a negative absolute one is, so this warns
and still applies the value; the threshold is far enough above any real
simulation that it cannot fire on a legitimate deck.

**`set curplotname=x` killed ngspice with a heap abort.** Before the first
analysis `plot_cur` is `constantplot`, a statically initialised struct whose
`pl_title`, `pl_date` and `pl_name` are string **literals** — and the assignment
began with `FREE(plot_cur->pl_name)`. Freeing a pointer malloc never returned
aborts the process, with no diagnostic, from a line as ordinary as
`set curplotname=x` at the top of a `.control` block. The same code also ignored
its `isset` flag, so `unset curplotname` performed the assignment too and
silently renamed the plot instead of doing nothing.

**`PP_mkfnode()` copied an unbounded function name into a fixed buffer.**
`fourier 1k <600-char-name>(v(a))` smashed the stack, and the same through `meas`
died on the fortify check. Two unbounded writes, `strcpy` and `sprintf`, into
`char buf[BSIZE_SP]`.

## Enhancement-438's own diagnostic

`warn_physics` reported from `dosim()` — once per analysis *run*. That is right
for `op`, `dc` and `tran`, where one command is one run, and wrong for the
drivers that loop: `montecarlo 20` and a 6-point `sweep` repeated an identical
warning 20 and 6 times for one unchanged bad parameter. A diagnostic that scrolls
the real output away is one users switch off.

Each distinct finding is now reported once per circuit. The *value* is part of
the key on purpose: a sweep that walks a knob through a non-physical range should
report each distinct bad value, because those are genuinely different findings.
Only the unchanged repeat is suppressed.

## Test integrity: the binary and its code models must come from one build

`examples/_setup.py` prefers a locally built `ngspice-46/build/src/ngspice`, but
pointed `SPICE_LIB_DIR` unconditionally at the committed `bin/<os>/<arch>`
bundle. A locally built simulator was therefore verified against whatever code
models CI had built weeks earlier, and an edit under `src/xspice/icm/` was not
exercised by the suite that is supposed to be authoritative for it.

The failure mode is worse than a stale test. With no `SPICE_LIB_DIR` at all,
ngspice falls back to its compiled-in prefix and silently loads a **third
party's** code models — on the development machine, an unrelated ngspice
installed under `/usr/local` in February 2025. Four "crashes" found by hand
against that install (`d_source`, `s_xfer`, `table2D`, `table3D`, all SIGSEGV)
**do not exist in this tree**: against this repo's own code models every one is
clean, and `s_xfer`'s was fixed here by Enhancement-240 in July. They were
withdrawn, and the harness now generates a spinit that loads the code models
built alongside the binary it is testing.

## Withdrawn

Five findings from the round-38 hunt did not survive verification and are
recorded so they are not re-investigated:

| finding | why it was withdrawn |
|---|---|
| `d_source` SIGSEGV on any relative path | the Feb-2025 `/usr/local` code models, not this tree |
| `s_xfer` SIGSEGV, `den_coeff` length 1 | same; fixed here by Enhancement-240 |
| `table2D` SIGSEGV on a headerless file | same |
| `table3D` SIGSEGV on empty/garbage | same |
| `xfer` silently returns 0 for a bad file | it reports `No option line found in file …`; the hunt's filter did not match XSPICE's `Instance: … Message: …` format |

One more was corrected rather than withdrawn: `montecarlo` does not *lose* the
`warn_physics` warning, it repeats it once per sample. The original reading came
from a malformed `montecarlo` command that never ran.

## Verification

* **`examples/sensrestore_examples` — 16/16, both solvers.** The BJT split is
  pinned closed and checked to stay closed across repeated ops, a following `dc`
  sweep, `sens`-run-first, and reltol from 1e-3 to 1e-12; the diffpair too. Four
  control devices are checked unchanged. Because a fix that quietly disabled the
  analysis would also pass a before/after comparison, `sens` is separately
  checked to still produce its per-parameter output **and to be numerically
  right**: on a divider both `r1` and `r2` are compared against the analytic
  ∓2.5e-4 V/ohm, which pins the sign convention as well as the magnitude.
* **`examples/argguard_examples` — 44/44, both solvers.** Every guard above, each
  paired with the controls that would catch an over-broad fix: a valid `pss` still
  runs, valid `.meas` windows still measure the right numbers, `pow(2,3)`,
  `pow(0,2)`, `pow(0.5,-1)` and `1/0` are unchanged, ordinary temperatures warn
  about nothing, setting the plot name after an analysis still works, an ordinary
  function call still evaluates, and a healthy circuit still produces no
  `warn_physics` output at all.
* **Full regression, both solvers.**

## Found by

The round-38 bug hunt, and — for the two crashes no probe of mine had caught —
macOS's own crash reports. Twenty-six `.ips` files grouped by faulting frame
turned up the `cp_usrset` heap abort and the `PP_mkfnode` overflow, neither of
which had appeared as a failure in any test I ran, because both had happened
inside runs I had already scored as passing.
