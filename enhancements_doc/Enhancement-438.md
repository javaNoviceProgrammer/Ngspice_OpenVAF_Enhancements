# Enhancement-438 — a failed simulation must not become data

Eleven fixes from round 37 of the bug hunt, plus one new opt-in option. The
theme running through almost all of them: **construct A validates something,
its equivalent sibling B does not**, and the sibling that stays quiet is the one
that produces a confident wrong number.

## 1. `montecarlo` counted failed simulations as passing samples

```
montecarlo: 20 random samples, analysis 'op', 1 spec
DC solution failed -            <- six times
yield  : 100.000%  (20 / 20 pass)
```

With a built-in diode at σ=10, **14 of 20 samples failed to simulate and the
yield still read 100 %**. Monotonic in the failure count: 0/3/4/6/7 failures all
reported 100 %. Reproduced by a second, independent mechanism (an illegal tstep
drawn from a sampled parameter): 37 errors, "100 % (12/12)". Plain ngspice, no
Verilog-A involved.

The cause is shared by three commands. Each drives an analysis in a loop and
reads a metric back from the resulting plot — but ngspice leaves the *previous*
point's plot in place when a run fails, so the read-back succeeds and returns
stale or zero data. Nothing downstream could tell a failed point from a real one.

**The signal already existed.** `runcoms.c` publishes `sim_status` per analysis:
0 before each run, 1 when `if_run` reports aborted or not-started. Reading it is
exact and needs no new plumbing.

* **`montecarlo`** — a sample that never solved is neither a pass nor a spec
  violation; it is missing data. It now leaves the yield population, and the
  exclusion is reported: *"NOTE: 6 of 20 samples failed to simulate and are
  EXCLUDED from the yield above"*. The confidence interval widens correctly for
  the smaller population. A run with no failures is unchanged.
* **`sweep`** — a point that never converged still contributes a value to every
  output curve, and for a failed operating point that value is exactly `0.0`,
  indistinguishable from a real zero and persisting into `wrdata` files. The
  curve keeps its shape (dropping points would misalign every output against the
  sweep scale) and the sweep now says so at the end, where it cannot scroll past:
  *"WARNING -- 2 of 5 points did not converge; their output values are NOT valid
  results (a failed operating point reads back as 0)."*
* **`optimize`** — failed evaluations were absorbed silently and the search still
  reported that it had **converged**. A failed evaluation is now scored as
  worst-case, so the search moves away instead of scoring the previous point's
  plot, and the count is reported with the usual cause named.

## 2. `.option warn_physics` — an opt-in physical-domain check

Every value this flags is one a simulator has good reason to accept by default:
a negative resistance is a standard small-signal equivalent, a negative
capacitance appears in de-embedding, and behavioural modelling deliberately uses
non-physical elements. Refusing them outright would break working decks. But
when such a value is a *mistake* it was completely silent, and the results
stayed plausible rather than obviously wrong:

| | measured consequence |
|---|---|
| `K1 L1 L2 1.5` | with Lp = Ls, physics caps \|v(s)\|/\|v(p)\| ≤ k; ngspice reports **\|v(s)\| = 1.178 > \|v(p)\| = 0.9986** — the coupled pair generates energy |
| `.model sm sw ron=-1` | the switch is a −1 Ω resistor; a passive divider reports **−0.001001 V** (exactly −1/999) |
| `M1 … l=-1u` | **v(nb) = 1.0306 above the 1 V supply**, with negative drain current — the MOSFET sources current |

So the values stay legal and the check is something you ask for:

```
.option warn_physics
```

It covers negative `ron`, `roff`, `l`, `w`, `area`, `bf`, `br`, and `|k| > 1`.
Most rules run over the same device-type / model / instance walk the wildcard
accessors use, so they need no per-device code. The coupling coefficient is the
exception and is checked in `MUTtemp`, the one place that has both the
coefficient and the two inductances — the askable `k` returns the mutual
inductance M, not the coefficient.

### What the controls forced

A diagnostic that fires on a correct circuit gets switched off and ignored, so
every rule was checked against clean multi-device decks. Two candidate rules were
dropped for exactly that reason:

* **Zero is not flagged, only strictly negative values.** `l` and `w` sit at 0 on
  every device that does not use them — a resistor model carries `l`, so does a
  diode. Flagging zero made the option warn **six times on a circuit with nothing
  wrong with it**.
* **`is` is not checked at all.** It is the saturation current on a diode or BJT
  model but the **source current** on a MOSFET instance, where a negative value
  is the normal operating point. (ngspice already clamps a negative diode `is` to
  1e-28, so nothing is lost.) This is the hazard of matching on parameter *name*
  across every device.

## 3. Five smaller fixes

* **A bogus co-knob no longer cancels the whole sweep restore.**
  `sweep @r1[resistance] 1k 2k 1k -vs @nosuchdev[res] 1k 2k 1k` left r1 at 2000
  and the next `op` read **0.3333 instead of 0.5** — a 33 % error from a typo in an
  unrelated knob name. Enhancement-385's all-or-nothing rule was justified by
  "a partly restored circuit is harder to reason about than an untouched one",
  but that premise fails when the knob that failed is a *different* knob from the
  one that moved: the circuit is not untouched. Capture is now per knob, and the
  outcome no longer depends on the order the knobs were listed in.
* **`.meas … WHEN` no longer fabricates a result.** `com_measure_when()` reports
  `MEASUREMENT_FAILURE`, and that verdict was thrown away — only `isnan` was
  consulted, and `m_measured` starts at zero. So an unresolvable WHEN printed a
  clean `0.00000e+00` formatted exactly like a successful measurement: in an AC
  run, `meas ac f WHEN mag(v(nb))=0.707` recorded **0 Hz as the −3 dB point**. Its
  sibling `FIND` already failed loudly on the same input.
* **An unknown `.options` name is reported.** `.options reltoll=1e-12` left
  reltol at its default with nothing on stderr, while the correctly spelled
  option demonstrably changes the answer. The warning is raised on the `.options`
  **card** path only — `if_option()` itself is called by `cp_usrset()` for every
  shell variable precisely to discover whether a name is an option, so warning
  there makes ngspice complain about its own `rndseed` on every run.
* **An unmatched `.if` sets the exit status.** It printed `Error: Mismatch of .if
  … .endif` and then exited **0** with a full set of results, while the
  `.subckt`/`.ends` sibling twelve lines above prints almost the same words and
  exits 1. A CI step checking the exit code saw a clean run.
* **A successful `hb` exits 0.** `main.c` decides "did anything simulate?" from
  `sim_status`, which `hb` never set because it drives the solver itself. Every
  successful harmonic-balance run in `ngspice -b` exited **1** with "Error:
  incomplete or empty netlist".

## Found but not fixed here

Five findings from the same round are deliberately left, each for a stated
reason rather than for lack of time:

* **`pow(v,e)` aborts for 0 < e < 1** while `sqrt`, `pwr` and `exp(0.5·ln v)`
  succeed. The abort is the Newton solver refusing an unbounded derivative
  `e·v^(e−1)` at the initial guess v = 0 — mathematically it is right to object.
  Guarding it means choosing a clamp, which changes results for a working
  construct. Recorded, not bundled.
* **numparam is 1 ULP off** on 3, 6, 7, 0.1, 0.2, 1.5. `R 3` gives exactly 3.0
  but `.param q={3}` gives 3.0000000000000004, and it reaches results (a 3/1
  divider reads 0.25 versus 0.24999999999999994). Replacing numparam's decimal
  scanner touches every parameterised deck in existence; the payoff is a last-bit
  difference. It wants its own change with its own regression.
* **XSPICE `pwl` with mismatched `x_array`/`y_array` lengths** silently produces
  a wrong transfer function that goes negative. The fix belongs in the code
  model's parameter validation, which is a separate subsystem.
* **A PWL *source* with an odd token count** silently produces a different
  waveform.
* **A typo'd subcircuit parameter is silently ignored**, at every nesting level.
  Subcircuit actuals are matched positionally by `$`-substitution in numparam,
  and a `.subckt` line without `params:` produces no formals to match against —
  so reporting an unknown name means changing how the call line is parsed.
* Half of the `.meas ac` finding also remains: `WHEN v(nb)=…` on a **complex**
  vector still measures off the real part and returns 1024 Hz instead of 1591 Hz.
  The vector resolves, so it is not the failure path fixed above.

## Verification

* **`examples/failacct_examples` — 9/9.** Each of the three commands is checked
  both for reporting the failures *and* for leaving a clean run unchanged. The
  optimize case needs a Verilog-A model with `area from (0:inf)`, because
  ngspice's built-in devices **clamp** an out-of-range parameter instead of
  refusing it and so never produce a failed evaluation.
* **`examples/warnphysics_examples` — 18/18.** Every positive is paired with the
  option **off** (nothing changes for anyone who does not ask), the boundary
  `|k| = 1` is checked to stay legal, and five clean multi-device decks are
  checked to produce no warning at all.
* **Full regression 347/347**, both solvers.

## Found by

Round 37 of the ngspice + OSDI bug hunt. Sixteen findings, of which the ones
fixed here were the ones that produce a confidently wrong number rather than a
refusal.
