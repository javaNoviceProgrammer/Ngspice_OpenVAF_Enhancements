# Enhancement-434 — three silent wrong answers, a silent truncation, and a swallowed request

```
$simparam("temp")              ->  OSDI(fatal) unknown $simparam "temp"
$simparam("abstime")  in .dc   ->  5.0        (the sweep VOLTAGE, not a time)
wcd ... -analysis <513 chars>  ->  a different, shorter command runs
.tf  with a model calling $finish  ->  result reported, request never mentioned
```

Round-35's hunt turned these up. What they share is that none announced itself:
three returned a plausible number and one ran a command the user did not type. A
fifth finding — a `save` list that resolves to nothing destroying the whole run —
is documented here and deliberately left alone; the section below explains why
fixing it has to come after something else.

## A `save` list that matched nothing destroys the run — found, NOT fixed

`save` is the only output-selection command that behaves this way:

| command | one unresolvable name |
|---|---|
| `save` / `.save` | **analysis aborted, every result lost** |
| `.probe`, `.print`, `print`, `wrdata` | diagnose, carry on |
| `save @dev[badparam]` | warns cleanly (Enhancement-418) |

So `save` disagrees even with itself — a bad device parameter warns, a bad node
name is fatal. It fires only when *nothing* in the list resolves.

**The fix was written and then withdrawn, because it creates a crash.** Falling
back to recording everything — what ngspice does when no save list is given —
made the regression's `nameovf` suite die with SIGTRAP. The abort is
load-bearing: it stops execution before a latent long-name stack overflow on the
`.four`/`gettoks` path that Enhancement-237 hardened but did not fully reach.

```
.four 1k i(<600 characters>)     rc=1  (aborted early)  ->  rc=133 (SIGTRAP)
```

That is Enhancement-399's lesson running the other way — there, rejecting a wrong
answer created a crash; here, *accepting* one does. Removing the abort therefore
has to wait until the underlying overflow is fixed, which is its own change
against `dotcards.c`, not something to smuggle into this one. The current
behaviour is pinned in the suite so that fixing it later is a deliberate act.

## `$simparam("temp")` was missing while `tnom` was there

ngspice's `sim_params[]` carried `tnom` but not `temp`, though it has had
`ckt->CKTtemp` all along. A model ported from Spectre — where `temp` is how you
ask — either got the caller's default (silently the wrong temperature) or, with
no default, was killed by `OSDI(fatal)`.

It is returned in **Celsius**, matching `tnom` beside it. That file's own comment
sets the admission test — the names added are *"exactly the ones where ngspice
had the answer all along"* — and `temp` meets it exactly.

**It is the GLOBAL temperature, and that is the correct split.** An instance-line
`temp=` or `dtemp=` does *not* change it:

| | `$temperature` | `$simparam("temp")` |
|---|---|---|
| global 27 °C | 300.15 K | 27.0 |
| `option temp=100` | 373.15 K | 100.0 |
| instance `temp=100` | **373.15 K** | **27.0** |
| instance `dtemp=50` | **350.15 K** | **27.0** |

`$temperature` is this device's temperature and already honoured every route
(Enhancement-397); `$simparam` reports simulator- and analysis-level knobs, which
is why `tnom` beside it is circuit-wide too. It could not be per-instance without
restructuring anyway: `get_simparams()` takes the circuit, and the `OsdiSimParas`
it returns is built once per evaluation and shared by every instance. Spectre
draws the same line. A model wanting its own temperature must use
`$temperature`.

`temperature`, `timestep`, `maxstep` and `freq` are deliberately **not** added.
ngspice holds values resembling the last three, but no simulator answers to those
names, and `$temperature` already covers the first. Supplying them would be
inventing an interface rather than completing one.

## `abstime` handed the model a voltage

`.dc` reuses `CKTtime` as its sweep abscissa, and `abstime` was passing that
field through unconditionally:

| sweep | abstime, before |
|---|---|
| `dc V1 0 5 1` | 5.0 |
| `dc V1 -3 -1 1` | −1.0 |
| `dc Vb 0 7 1` | 7.0 |

An aging or time-dependent model read the swept voltage as a time. Outside a
transient there is no simulation time, and 0.0 is the honest answer — which is
precisely the guard `OSDIfinalStep` in the same file already applied for
Enhancement-412. The pollution never reached the solver: `ddt` is exactly 0 in
DC, verified to ten digits before and after.

## A 512-byte buffer silently shortened `-analysis`

`montecarlo`, `highsigma` and `wcd` assemble the command into a fixed
`analysis[512]` with `strncat`, which simply stops at the end — so past 509
characters the tail was dropped and a **different command ran**, with no
diagnostic. They now refuse:

```
wcd: -analysis command is too long (limit 511 characters)
```

`sweep` and `optimize` build the same string with `tprintf` and have no limit;
these three cannot without restructuring, so they at least have to say so.

**Disclosure:** for `wcd` this exposure is one Enhancement-433 created three
commits ago, by giving it the same multi-token collector as its siblings — before
that it read a single token and could not overflow. `montecarlo` and `highsigma`
have had it all along.

## `.tf` swallowed a model's stop request

Enhancement-426 gave the operating point a notice for a deferred `$finish`, and
`dctrcurv`, `acan`, `noisean` and `dctran` each have their own. `tfanal` was the
analysis that computes an operating point, reports a result, and says nothing.
It now reports it, and — as in `dcop.c`, for the reason E-426 gives — does not
act on it: a transfer function is a single computed point, there is no sweep left
to truncate, and discarding it would delete a legitimate result.

## Withdrawn while fixing

**A model-name collision was already diagnosed.** A top-level `.model x1:rmod`
does collide with subcircuit `x1`'s own flattened `rmod`, and the wrong model
does win — the resistor goes 1000 → 7777 Ω and the solution moves with it. But
ngspice already says `model "x1:rmod" is already defined; keeping the first
definition`. The hunt reported it as silent because that probe checked only
values, never diagnostics. A second warning would duplicate a diagnostic, which
is exactly what Enhancement-430 removed from `.probe`, so **nothing was changed**
and the existing warning is pinned in the suite instead.

**`$finish` at an operating point is reported, not obeyed** — E-426's deliberate
decision, re-confirmed here. The hunt called it "ignored" because the matrix
asked only whether results appeared, and a follow-up `grep ... | head -4` was
consumed by three `$strobe` lines before reaching the notice.

## Known, not fixed

* After a **refused** `alter`/`altermod`, readback reports the refused value
  while the device keeps the old one (`alter @n1[w]=-2e-6` → warning, yet
  `print @n1[w]` gives −2e-6). Correcting it means rolling back the OSDI
  parameter store on rejection, which is wider than the evidence here.
* Operating-point variables named `temp`, `dt`, `m` or `dtemp` are shadowed by
  the instance knobs Enhancement-397 made readable, so the model's own value is
  unreachable. `dtemp` is a fourth case not previously recorded.

## Verification

* **`examples/silentloss_examples` — 23/23.** Each fix is checked in both
  directions: the failure no longer happens *and* the neighbouring good case is
  unchanged — a normal-length `-analysis` is untouched, `tnom` is unmoved beside
  the new `temp`, a transient still reports a real `abstime`, and a model that
  does not call `$finish` leaves `.tf` quiet. The unfixed `save` abort is pinned
  as current behaviour, together with the long-name case it protects.
* **Full regression 346/346**, both solvers — including `nameovf`, which is what
  caught the withdrawn `save` fix.

## Found by

Round 35 — a one-hour hunt over ngspice + OSDI. Its clean list is worth as much
as its findings: multipliers exact to 2.000000×/4×, noise matching an analytic
reference to seven digits with the flicker slope exactly −0.500/decade, 21
analysis-order permutations bit-identical, KLU ≡ Sparse, timer events exact
including one landing on `tstop`, and 160 randomized fuzz cases with no crash or
hang.

Six of the hunt's own claims were withdrawn on evidence, every one of them a
probe that could not distinguish the two outcomes it was meant to separate: a
deck with no title line (the first line is the title, and it ate the `.model`), a
`meas` failure that is symmetric with built-ins, a `.dc temp` difference that was
pure Newton tolerance, a `head -4` that truncated away the notice it was looking
for, a `showmod` that fails for built-ins too, and a convergence failure caused
by demanding thirteen digits on a 1e-5 current.
