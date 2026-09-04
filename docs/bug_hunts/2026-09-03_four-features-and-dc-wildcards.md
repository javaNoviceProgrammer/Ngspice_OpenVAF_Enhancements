# Bug hunt — autobus / autoadapt / automc / saveused, and `.dc` parameter wildcards

**Date:** 2026-09-03 · **Commit under test:** `19e68147` · **Binaries:**
committed `bin/macos/apple-silicon/ngspice`; test models compiled with the
locally built `OpenVAF-master-20260610/target/opt/openvaf-r`.

Two passes in one session: the four feature options first, then the `.dc`
parameter-wildcard surface of [E-534](../../enhancements_doc/Enhancement-534.md).
Both went at what the existing suites and the [three](2026-09-02_autobus-autoadapt-osdimc-saveused.md)
[prior](2026-09-02_four-features-gaps-closed.md) [hunts](2026-09-02_osdimc-trial-policy.md)
had *not* covered, rather than repeating them.

**Result: no findings.** Nineteen suites pass, the two `saveused` defects that
were confirmed open twice are fixed and hold, and every surface probed here
behaved to specification — including several the suites do not pin at all.

The more useful result is in [§6](#6-three-candidates-a-control-killed): three
separate candidate findings evaporated the moment the right control was built.
All three would have been false reports, and one of them *was* — it had already
shipped in the round-4 LRM audit and is now withdrawn.

| surface | status |
|---|---|
| `saveused` F1/F2 (open in both prior hunts) | **fixed in `cb8a6528`, re-verified here** |
| `saveused` × `meas`/`wrdata`/`fourier`/`@dev[param]` | tested — sound |
| `automc` alias | tested — sound (was never exercised) |
| `autobus` ground / already-indexed tokens | tested — refused *and diagnosed* |
| `autobus` bit order on a descending bus, flat vs subcircuit | tested — sound |
| `autoadapt` × `osdimc`, quiet vs debug | tested — sound |
| `.dc` wildcard spellings `@*[[p]]`, `@*.leaf[p]` | tested — sound (**not pinned by any suite**) |
| `.dc` wildcard per-target nominals, refusals, nesting, error-path restore | tested — sound |
| `.dc` wildcard × `osdimc` recentering hazard | tested — sound (the hazard E-534 names) |

---

## 1. `saveused` — the two known defects are closed

Both were reported by the first hunt and confirmed still open by the second.
Re-measured on the same four-resistor divider:

| deck | first hunt | now |
|---|---|---|
| `.option saveused`, `print v(out)` then `write` | raw held **2** vectors (`out` + a spurious `v(all)`) | **5** — `in`, `v(a2)`, `v(a3)`, `v(out)`, `i(v1)` |
| no option, same control block (reference) | 5 | 5 |
| `.option saveused`, `let y = a2 + a3` | *"vector a2 is not available"* | `y = 1.25` |
| `.option saveused`, `let y = v(a2) + v(a3)` | worked | `y = 1.25` |

The bare-name spelling now agrees with the `v()` spelling that always worked
(1.25 is this deck's closed form — the first hunt's 2.5 was its own divider),
and the implicit-all `write` is byte-identical to the no-option reference.

### the reference forms the hunts only spot-checked

Every form below was run twice — with and without the option — and the whole
diagnostic output diffed, not just the printed values:

| control-block form | result |
|---|---|
| `meas tran … TRIG v(a2) … TARG v(out) …` | identical |
| `meas tran … INTEG v(a3) from/to` | identical |
| `meas tran … FIND v(a2) AT=6u` | identical |
| two `meas` results consumed by a `let` | identical |
| `wrdata` + `print` | identical |
| `fourier 100k v(out)` | identical |
| `print @r1[resistance]` | **differs — by design** |

The last one collects `@r1[resistance]` as a per-timepoint vector (68 rows)
where the option-off deck answers a scalar query.
[E-469](../../enhancements_doc/Enhancement-469.md) specifies exactly that:
wildcard accessors are no longer collected, *"a **named** accessor still is:
`@r1[resistance]` is a perfectly good thing to save"*. Not a finding.

## 2. `automc` — the alias nobody had run

`.option osdimc`'s alias is documented in the suite's own docstring and never
exercised by it. Three spellings, `mcseed=42`, three trials of `smcres`:

```
.option osdimc mcseed=42    1.000000e+03  9.771865e+02  1.020069e+03
.option automc mcseed=42    1.000000e+03  9.771865e+02  1.020069e+03
set automc / set mcseed=42  1.000000e+03  9.771865e+02  1.020069e+03
.option osdimc mcseed=43    1.000000e+03  1.028185e+03  9.772668e+02
```

Bit-identical across spellings, and the seed still steers the draws.

## 3. `autobus` — the refusals, and bit order

The first hunt listed *"the `0`/ground token case, explicit `[0:2]` range
tokens"* as untested. Both are handled, and both **say so**:

```
N1 0 out busdev
  Warning: instance n1: ground cannot be indexed, so it cannot be expanded
           as the bus port 'a'; tie the bits off individually (e.g. "0 0 0").

N1 a[0] out busdev
  Warning: instance n1: "a[0]" already carries an index, so it cannot be
           expanded as the bus port 'a'; write the bits out individually.
```

That is [E-445](../../enhancements_doc/Enhancement-445.md) working as written —
it refuses rather than producing five floating `0[i]` nodes, *"naming the real
cause"*. The line then falls back to positional binding and E-402's
under-connected warning fires, so the deck gets two diagnostics, not none.

**The differential across every spelling.** `busdev` has conductances
`r, 2r, 4r, 8r, 16r`, each bit driven at a distinct voltage (1…5 V), so any
mis-binding moves the currents:

| spelling | `i(vo)` | `i(vb0)` | `i(vb2)` | `i(vb4)` |
|---|---|---|---|---|
| written out (reference) | 3.562500e-03 | −1.000e-03 | −7.500e-04 | −3.125e-04 |
| `N1 a out busdev` | 3.562500e-03 | −1.000e-03 | −7.500e-04 | −3.125e-04 |
| `N1 a[0:4] out busdev` | 3.562500e-03 | −1.000e-03 | −7.500e-04 | −3.125e-04 |
| `N1 A out busdev` (case) | 3.562500e-03 | −1.000e-03 | −7.500e-04 | −3.125e-04 |
| range token, option **off** | 3.562500e-03 | −1.000e-03 | −7.500e-04 | −3.125e-04 |

**Bit order on a descending bus.** `busoff` declares `inout [4:1] a`, and the
model's own terminal order is *ascending* — the under-connected diagnostic names
terminal 3 as `a[3]` and terminal 4 as `a[4]`. Four routes to the same circuit,
holding the formal→actual mapping constant:

| route | `i(vy1)` | `i(vy4)` |
|---|---|---|
| flat, written out | −1.000e-03 | −5.000e-04 |
| flat, `N1 y 0 busoff` | −1.000e-03 | −5.000e-04 |
| `.subckt` formals **ascending** | −1.000e-03 | −5.000e-04 |
| `.subckt` formals **descending** (actuals reversed to match) | −1.000e-03 | −5.000e-04 |

Bits are emitted by ascending index, matching the model's terminal table, while
the `.subckt` line's written order decides the port order — the two rules the
[previous hunt](2026-09-02_four-features-gaps-closed.md) documented, confirmed
here from the other direction: reverse *both* and the circuit is unchanged.

## 4. `autoadapt` — interaction with `osdimc`, and the reporting modes

The first hunt named *"debug-vs-quiet reporting modes, and any interaction with
`osdimc`"*. A four-bit channel with a statistical `r0` (σ = 100), two instances
sharing a bus node, `.option autobus autoadapt=debug adapter=amod osdimc
mcseed=42`:

```
autoadapt: b split -> b_f (n1 port 1) / b_r (n2 port 0), 4 bits, adapter n_adapt1_ amod
trial 1   @m1[r0] = 1.000000e+03   @m2[r0] = 1.000000e+03    (nominal baseline)
trial 2   @m1[r0] = 9.495624e+02   @m2[r0] = 9.540605e+02
trial 3   @m1[r0] = 1.128167e+03   @m2[r0] = 9.469982e+02
```

The injection line prints **once**, not per trial — the rewrite is a parse-time
pass and MC trials do not re-expand the deck — trial 1 is the documented nominal
baseline, and the two model cards draw independently, which is the
process-parameter rule.

**Quiet and debug differ only in reporting:** `.option autoadapt` emits no
`autoadapt:` line and produces identical values.

**A tool-injected instance takes part in MC.** Giving the adapter model its own
`(* std=5.0 *) ra`, the injected `n_adapt1_` draws like any other instance —
`@amod[ra]` = 50 (nominal), 52.44, 45.34.

## 5. `.dc` parameter wildcards (E-534)

Baseline: `dcxsweep`, `sweepdc`, `sweepwild`, `wildparam`, `modelwild`,
`wildrestore`, `sweepparam`, `sweepscale` — 8/8 both solvers.

**Two documented spellings that no suite pins.** E-534 gives `@#*[p]` *and*
`@*[[p]]` for instances, `@*:leaf[p]` *and* `@*.leaf[p]` for named models;
`dcxsweep` pins only the first of each pair. On a divider of two semiconductor
resistors with *different* model nominals (rsh 100 and 250):

| spelling | swept values | `v(m1)` |
|---|---|---|
| `@#*[resistance]` | 1k, 2k, 3k | 0.5, 0.5, 0.5 |
| `@*[[resistance]]` | 1k, 2k, 3k | 0.5, 0.5, 0.5 |
| `@*:ra_mod[rsh]` | 100, 200, 300 | 0.714286, 0.555556, 0.454545 |
| `@*.ra_mod[rsh]` | 100, 200, 300 | 0.714286, 0.555556, 0.454545 |

Each pair is identical, and the named-model figures are the closed form
(`Ra = rsh·10`, `Rb = 2.5 k`).

**Per-target nominals.** Sweeping `@*[rsh]` moves *both* cards (the divider
stays at 0.5 throughout), and afterwards each is back at **its own** nominal —
`@ra_mod[rsh] = 100`, `@rb_mod[rsh] = 250`, not a shared value. The suite's
restore check runs against a single nominal and could not have caught a
collapse to one.

**Refusals name the cause:**

```
dc @*[nosuchparam] …    no loaded model has a settable parameter 'nosuchparam'
dc @#*[nosuchparam] …   no loaded instance has a settable parameter 'nosuchparam'
dc @*:nomod[rsh] …      no loaded model named 'nomod' has parameter 'rsh'
                        (a model inside a subcircuit is flattened to <instance>:nomod)
```

**Partial matches skip, they do not fail.** With two resistor models and a diode
model in one deck, `dc @*[is]` moves only the diode — `v(dn)` = 0.370559,
0.387024, 0.397170 — and the resistor models are passed over silently, which is
the right reading of "every model with `p`".

**Scales and nesting.** `dc @*[rsh] dec 2 100 1000` gives the exact half-decade
grid 100 / 316.228 / 1000. A nested pair (`@*[is]` inner, `@*:ra_mod[rsh]`
outer) gives 3 × 2 = 6 points with **both** knobs verified to move: `v(m1)` is
0.714286 for the first block and 0.555556 for the second, while `v(dn)` repeats
identically across blocks — each value its closed form.

**The hazard E-534 names.** The doc warns that the frontend's own wildcard
setters run `doset_user()`, `alter`'s recentering hook, and must not be reused
for per-point writes. Tested directly against `smcres` under
`.option osdimc mcseed=42`:

| between trial 1 and the next | trial 2 | trial 3 |
|---|---|---|
| nothing (reference) | 9.771865e+02 | 1.020069e+03 |
| `dc @*[r] 500 700 100` (wildcard) | 1.020069e+03 | 9.328405e+02 |
| `dc @mm[r] 500 700 100` (named) | 1.020069e+03 | 9.328405e+02 |
| `altermod @mm[r]=600` (**should** recenter) | 5.771865e+02 | 6.200694e+02 |

The wildcard path is bit-identical to the named path and leaves the nominal at
1000 — the sequence shifts only because `dc` is itself a run-class command and
consumes a trial. `altermod` still recenters exactly: the same deltas (−22.81,
+20.07) about 600 instead of 1000. And `@mm[r]` reads 1000 again after the
sweep.

**Error-path cleanup.** A sweep whose points leave the parameter's `from (0:inf)`
range aborts —

```
dc @*[r] 500 -500 -250
  Parameter r of 'mm' is out of bounds (value 0)!
  dc simulation(s) aborted
```

— and *still restores*: `@mm[r]` = 1000 afterwards, and a following `op` gives
`i(v1)` = −1.000e-03, the nominal answer. Running the same wildcard sweep twice
in one control block reproduces it exactly, both cards ending at 100 / 250.

## 6. Three candidates a control killed

Each of these looked like a finding and was not. They are recorded because the
*same* control retired all three, and because one of them had already shipped.

**`.ic` on an OSDI internal node is ignored under `uic`.** Published in the
round-4 LRM audit as a silent OSDI-layer bug; **withdrawn** in `19e68147`. The
control — *does a built-in device's internal node behave differently?* — says
no: a BJT answers `Warning : IC on non-existent node - q1#collector, ignored`.
`.ic` names resolve in the parser's third pass, before any device setup creates
internal nodes. Not OSDI-specific, not silent, and the published cause (a
missing `MODEUIC` branch in the OSDI load) was invented rather than measured.

**`autobus` silently mis-binds a ground token.** The measured circuit really is
wrong — `i(vo)` = −3.333e-04 against the written-out −1.937e-03 — but it is not
silent: E-445's refusal message is right there, and the first measurement had
been filtered down to printed values with `grep`. Reading the whole output first
turned a finding into a passing test.

**An OSDI model parameter reads 0 before the first analysis.** True, and the
built-in comparison a card-set parameter suggested was not like-for-like: a
*defaulted* built-in diode is worse, reading `@dmod[is] = 1e-28` and
`@dmod[n] = 0` before setup against its 1e-14 / 1 defaults. Resolving defaults
at setup is general ngspice behaviour, not an OSDI or wildcard defect.

The pattern is one control: **does the same deck, in the same shape, do the same
thing on a route that is known-good?** A built-in device beside the OSDI one, an
option-off run beside the option-on one, the whole output beside the grepped
line. Two of these three failures came from filtering the simulator's output
before reading it.

## Coverage, honestly

* A no-finding hunt is worth the file so the next reader does not spend the
  hours again. What moved from "untested" to "tested and sound" is in the table
  at the top; the `saveused` F1/F2 rows moved from "open" to "fixed".
* **Not covered here.** For the four options: `autobus=kicad` beyond what the
  [previous hunt](2026-09-02_four-features-gaps-closed.md) exercised, the
  `.adapt` node-list filter (covered there), and `osdimc`'s trial-policy layer
  (covered in [its own hunt](2026-09-02_osdimc-trial-policy.md)). For `.dc`
  wildcards: the E-533 sweep→dc handover on wildcard knobs, the
  1000-device performance claim, `@*:leaf` matching across *several* subcircuit
  copies, and wildcards over instance parameters of OSDI devices specifically.
* Nothing here re-examined the ground the
  [untouched-areas hunt](2026-09-02_osdi-untouched-areas.md) listed — node
  collapse, temperature, AC and noise, terminal currents, the solver layer.
