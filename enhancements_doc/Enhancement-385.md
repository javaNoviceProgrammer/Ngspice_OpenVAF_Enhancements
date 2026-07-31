# Enhancement-385 — three commands left the user's circuit changed behind them

Found by a **state-restoration audit**: for every (instance, parameter) pair in a
deck, the value after running a command must equal the value before. The class
already had four members — [E-380](Enhancement-380.md) (`.dc` inherited
integration coefficients), [E-381](Enhancement-381.md) (`stb` zeroed its probes),
[E-382](Enhancement-382.md) (`loadpull` left the tuner moved),
[E-384](Enhancement-384.md) (`sens` flipped every source to PORT) — so this time
the oracle went after the class rather than the instances.

It found three more, and one of them is E-384's own fix falling short.

## [A] `sens … ac` killed VCCS and CCCS sources

```
@g1[gain] = 1e-3   ->  sens v(out) ac dec 3 1e3 1e6  ->  0
a following .ac:   vm(out) = 0.0        (the answer is 1.0)
```

Not a bug in `sens`. `VCCSparam` folds the multiplier into the coefficient when
`gain` is written:

```c
case VCCS_TRANS:  here->VCCScoeff = value->rValue;
                  if (here->VCCSmGiven)
                      here->VCCScoeff *= here->VCCSmValue;
```

and `VCCSmValue` was never defaulted to 1. `res` does exactly that in
`ressetup.c` (`if(!here->RESmGiven) here->RESm = 1.0;`); VCCS and CCCS did not.
`sens` perturbs every settable real parameter, so it wrote `m` — which set
`VCCSmGiven` — read it back as 0, wrote that 0 back as the "restore", and the
next write of `gain` multiplied by zero.

That explains the exact scope the audit reported: **VCCS and CCCS have a settable
`m`, VCVS and CCVS do not**, and only the first two were affected. It also
explains why one frequency point was harmless and three were fatal — the
perturbation loop runs per frequency, so `m` has to be written before `gain` is
written again.

## [B] `sweep` never put an `alter`/`altermod` knob back

```
@r1[resistance] = 2000  ->  sweep @r1[resistance] 1800 2200 3  ->  2199
a following op:  v(out) = 0.5770        (the answer is 0.6)
```

[E-350](Enhancement-350.md) captured and restored the nominal of each swept
`.param`; the `alter`/`altermod` path — device and model parameters — was never
covered, so the knob stayed wherever the last point left it. General across
parameter types: `resistance`, `capacitance` and a source's `dc` all stayed moved.

The fix follows E-350's own discipline, including its **all-or-nothing rule**: if
any knob's nominal cannot be read, none are restored, because a partially
restored circuit is harder to reason about than an untouched one. Reading a knob
needs its own helper — `sw_eval_expr()` returns `0.0` on failure, which is
indistinguishable from a knob that is legitimately zero, and restoring a spurious
zero would be worse than not restoring at all.

## [C] …and E-350's own path only restored half of what it moved

```
.param rl=3k ;  sweep rl lin 3 1k 5k  ->  @r2[resistance] = 5000
a following op:  v(out) = 0.7143       (the answer is 0.6 — 19% out)
```

E-350 put the **numparam table** back. On the fast path
([E-320](Enhancement-320.md)) the point loop never touches the deck — it pushes
each point's values straight into the live circuit — so the devices still held
the last point's values. The nominals are now pushed back the same way each point
was pushed, before `sw_fp_free()` drops the binds it needs.

## E-384's fix covered only half its class

E-384 stopped `pwr`/`freq` clobbering an explicit waveform with
`if (!here->VSRCfuncTGiven)`. That left the **dc-only** source unprotected: it has
no waveform, so the guard passed, and `sens` still turned it into a PORT and left
it there. A following transient read **0.0 where the answer was 1.0** — the same
defect E-384 was written to fix, in the half it did not reach.

The decision has moved to `VSRCtemp`, inside the block that already computes
whether the instance really is a port (`portnum` plus a positive `z0`).
`VSRCparam`'s `pwr`/`freq` cases no longer touch the waveform selector at all,
which is the right shape: a parameter setter should store its parameter.

**I would not have found this without the audit.** E-384's own example passes
either way, because its deck carries a `SIN`.

## What keeps it fixed

`examples/staterestore_examples/audit/audit_state.py` is the campaign harness,
kept runnable — 31 commands × 292 (instance, parameter) pairs. A compact form
runs with the regular suite as check [13]. Each reported pair is labelled
`[INPUT]` or `[output]` from the device tables, so the next round does not have to
re-derive that distinction by hand.

Two things make it trustworthy, both learned the hard way:

* **The BEFORE snapshot must be bounded by the AFTER marker.** Without that bound
  it swallowed the AFTER block and — building a dict — the later values overwrote
  the earlier ones, so `before == after` and **every command looked clean**. This
  was caught only by running a **positive control against a binary with a known
  defect** before trusting a single clean result; nothing in a green run would
  have revealed it.
* **The control is a union of benign analyses, subtracted per pair.** A parameter
  is a computed output if it moves merely because the operating point moved.
  `op` vs `op` cannot see those — the same analysis reproduces the same operating
  point — and excluding by *name* would have masked real changes, since `p` is
  settable on some devices and an output on others.

**Limitation, stated rather than hidden:** 114 of 292 pairs are operating-point
dependent and are subtracted, so a command corrupting one of *those* is masked.
The inputs that matter — `resistance`, `dc`, `gain`, `capacitance`, `function` —
are not among them.

## Also observed, not fixed

`sens_cplx` reads uninitialised memory: it returns denormal garbage
(`2.12736e-314`, `2.14522e-314`) that varies between runs. Harmless to results,
and left alone rather than papered over.

## Verification

`examples/staterestore_examples` — 20 checks.

```
   fixed:     20/20
   pre-fix:    9/20
```

The eleven pre-fix failures are the defects. The eight accept checks pass on
**both** binaries: [A] changes the multiplier that scales every VCCS and CCCS, so
an explicit `m=2` still doubling the gain is exactly what a careless fix would
break. They also pin `sens`'s own numbers against the analytic derivative
(`dv/dR1 = -2.5e-4`, `dv/dV1 = 0.5`), VCVS/CCVS gains, a plain `tran` and `ac`,
and E-350's `.param` restore. A genuine RF port still produces bit-identical
S-parameters (`mag(S_1_1) = 9.0889370933e-01`).

Check [14] is an **audit canary** — a deliberate `alter` that the embedded audit
must detect. A harness that cannot see a change makes every clean report
worthless, which is not hypothetical here: it is what the unbounded parse did.

Regression 308/308 → 309/309.
