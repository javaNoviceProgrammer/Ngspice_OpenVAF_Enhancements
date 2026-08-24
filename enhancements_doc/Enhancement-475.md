# Enhancement-475 — a stated value is honoured or refused, never replaced

Seven defects from bug-hunt round 44. They are one shape: something the deck
said was discarded and something else quietly put in its place, or a refusal
named a fault other than the one it found. None raised an error, so none was
visible while it was happening.

## 1. `sin` with an explicit `freq=0` took its frequency from TSTOP

```c
FREQ =  here->VSRCfunctionOrder > 2
   && here->VSRCcoeffs[2] != 0.0        /* <- removed */
   ? here->VSRCcoeffs[2] : (1/ckt->CKTfinalTime);
```

`functionOrder > 2` already asks the only question that matters — *was a
frequency supplied?* The `!= 0.0` made an explicitly written zero fall through
as though nothing had been typed, so `sin(0 1 0)` became one cycle per
simulation:

| TSTOP | first rising 0.9 crossing |
|---|---|
| 10 µs | 1.78 µs |
| 20 µs | 3.57 µs |
| 40 µs | 7.13 µs |
| 100 µs | 17.8 µs |

Exactly linear in TSTOP — **lengthening the run changed the stimulus.** An
explicit 50 kHz stayed at 3.56 µs throughout, which is the control.

Three things make this the clear case rather than a judgement call. `TD` and
`THETA`, on the next two lines of the same block, test only `functionOrder` —
`FREQ` was the odd one out. `PULSE`, immediately above, documents its own
zero-substitutions in a `/* Parameter limits */` comment; `SINE` had none. And
unlike a zero rise time, **a zero frequency is meaningful**: it is DC. It now
gives DC, and *omitting* the frequency still defaults to `1/TSTOP` as documented.

The identical line in `isrcload.c` is fixed with it — the current source carried
the same code and the same behaviour.

## 2. An unknown parameter on a subcircuit call was silently dropped

`X1 a 0 div rr=5k` against `.subckt div p n r=1k` built a **1 kΩ** divider — the
default, exactly as if nothing had been passed. One transposed character and the
circuit is not the one that was written.

The two sibling constructs that take `name=value` both say something:

| unknown parameter name on… | before |
|---|---|
| `.model` | Warning |
| a device instance | Error, deck refused |
| **a subcircuit call** | **silent** |

It is now a warning naming the parameter and the subcircuit. A warning rather
than an error because the name is not usable inside the body either way, so
nothing that works today stops working. `m` is exempt — the multiplier is added
to the subcircuit automatically by the pass above.

## 3. A failed `.measure` left the previous answer under its name

```
meas tran xx FIND v(a) AT=0.25m   ->  xx = 9.999960000000e-01
meas tran xx FIND v(a) AT=5m      ->  "failed!"
print xx                          ->  9.999960000000e-01      (stale)
```

In a loop — where `meas` mostly lives — that is the previous iteration's answer
standing in for a measurement that never happened, while the "failed!" line
scrolls past. Nothing could detect it: `sim_status` (Enhancement-438) is not set
by `meas`.

The name is now dropped on failure, so a later read says *"vector xx is not
available"* — which is already what happens when the very first measurement
fails and the name was never set. Before, only the never-set case was honest;
the two now agree.

## 4. `tran` TMAX had no validation

`TSTEP`, `TSTOP` and `TSTART` each say *"is invalid, must be…"*. TMAX was
assigned unchecked, and a negative one reached the integrator and came back as

```
Warning: singular matrix:  check node b
```

— blaming a trivial RC divider that solves fine with any other TMAX. It now
names TMAX. Zero stays legal, because zero is how TMAX is spelled when you want
the default.

## 5. Six options accepted nonsense in silence

`pivtol` and `pivrel` were the only members of the tolerance family with no
check — `reltol`, `abstol`, `vntol`, `trtol` and `chgtol` all refuse `<= 0`, and
`gmin`/`gshunt` refuse a negative. `minbreak`, `srcsteps`, `gminsteps` and
`ramptime` had none either, while the sibling counts `itl1/itl2/itl4` refuse a
negative. All six now use the same `E426_BAD_OPT` path as their siblings, and
`pivrel` additionally refuses `> 1` — Sparse silently clamps anything above 1
back to its own default, which is precisely the substitution worth reporting.

Zero stays legal wherever zero is its meaning: `minbreak=0`, `srcsteps=0`,
`gminsteps=0`, `ramptime=0`.

**Left open, deliberately:** the round could not make *any* `pivtol` value change
a result on either solver, including `1e30`, which should reject every pivot. The
plumbing is correct — `SMPreorder` forwards into `spOrderAndFactor`'s
`(RelThreshold, AbsThreshold)` order properly — and `AbsThreshold` is consulted
in the pivot search, so the cause lies further in. Validating the input is a
separate matter from whether the value then does anything, and that question
needs its own change with its own evidence.

## 6 & 7. Two `.for` refusals named the wrong fault

Both are defects in Enhancement-474, shipped hours earlier, and both contradict
its own stated rule that each fault produces one message pointing at the mistake.

**Every unevaluable `{{ }}` reported "outside any .for loop"** — thirteen ways of
being wrong, all of them *inside* a loop. The fix separates the two questions an
unresolved brace can be asking. If nothing is left that a later binding could
fill in (`{{}}`, `{{1/0}}`, `{{1+}}`, `{{1.5}}`), it can never resolve and is
named where it stands. If a name survives (`{{j}}`, or `{{i+j}}` waiting for an
inner loop), it is left alone — and if it is still there at the end of the pass,
it is reported as *never resolved*, naming the expression. Only a deck with no
`.for` at all still gets the original message.

**A nested `.for` reusing the enclosing index** produced duplicate lines — the
outer pass substitutes the name first, so every inner iteration emits identical
text — and died with *"device already exists"*, naming the symptom. It is now
refused while the cause is still visible, by checking the nested header's
variable against the enclosing one during the walk that already looks for the
matching `.endfor`.

## What this deliberately does not change

Three findings from the same round look exactly like the above and are settled
decisions. Each was re-confirmed by reading the code, not the behaviour, and
checks `[20]`–`[22]` pin them so a later round does not "fix" them:

- **Negative R/C/L stay unflagged.** Enhancement-438 says so directly:
  *"negative passives are the very idiom this project's own examples use for
  equivalent circuits, and flagging them would make the option too noisy."*
- **`pow(-4,0.5)` still returns 2, and `1/0` still clamps to 1e32.**
  Enhancements 256/446 chose the finite value over NaN *"because a NaN here
  poisons the Newton Jacobian"*. numparam refuses both, and that divergence is
  intended: it runs at parse time, where nothing downstream can be poisoned.
- **`pulse` with `tr=0` still takes the timestep** — documented in a
  `/* Parameter limits */` comment directly above the code. Unlike a frequency,
  a zero rise time has no meaning for an integrator.

## Verification

`examples/explicitvalue_examples/verify_explicitvalue.py` — **41/41**, both
solvers.

**The oracle for the substitution defects is that the answer must not move.** A
default quietly standing in for a stated value is only visible if you vary the
thing the default is drawn from, so the checks sweep TSTOP, measure the
subcircuit through the current it actually draws, and read a variable *after* a
failure — rather than asserting a single number.

Three of the suite's own first-run failures were the harness, not the product: a
body without a trailing newline glued `.control` onto the last element line, and
one check compared two `None`s and called it agreement. Both are fixed; the
newline is now forced in `run()`.

Full regression **389/389**, both solvers. ngspice-only.
