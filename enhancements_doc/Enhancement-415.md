# Enhancement-415 — the event the solver stepped over

A `@(timer(1e-9, 1e-8))` in a 10 µs run owes 1000 events. At a 1 µs transient
step it produced **109**.

| tran step | events fired | lost |
| --- | --- | --- |
| 1 µs | 109 / 1000 | **891** |
| 0.1 µs | 207 / 1000 | **793** |
| 10 ns | 1000 / 1000 | — |

`cross` and `above` watch a signal, so a sign change across an accepted interval
is still noticed and the event is merely reported late. A timer watches nothing:
if the solver never stops near the scheduled instant, the event does not happen
at all. A model implementing a clock, a sampled system or a periodic update ran
at whatever rate the step controller happened to pick.

The contrast that identified it — for ngspice's **own** pulse edge at 1 µs the
nearest timepoint is exactly **0** away; for an OSDI `@(timer)` at 1 µs it was
**5.6e-08** away, and the grid ran `…8.56e-07, 1.056e-06` with nothing at 1 µs at
all. The breakpoint machinery works; OSDI device events never reached it.

## The fix needs no ABI change

`lower_timer` already computes the next event time, and Enhancement-24's
`$bound_step` channel already runs from the compiler through the descriptor to
`osditrunc.c`. The model now asks for a step of at most `next_event − now`, so
the following timepoint lands on the event.

It is combined with **`min`, never an overwrite**: a model's own `$bound_step`
still holds beside a timer (verified — 1000 events *and* the 5 ns bound, 2004
timepoints), and a second timer composes the same way. A one-shot whose pending
time is `INFINITY` is not smaller than the incumbent bound and changes nothing,
so it does not pin the step for the rest of the run (verified — 59 timepoints,
exactly as before).

## A noise total that was the wrong quantity

```c
#define nVar(i, j) noise_vals[i * descr->num_noise_src + j]   /* the stride was wrong */
```

Each of the `NSTATVARS` noise state variables needs one slot per source **plus**
one for the whole-device total, accumulated at index `num_noise_src` — and
`osdiregistry.c` allocates exactly `NSTATVARS * (num_noise_src + 1)`. Indexing
with the source count alone made two of them collide: with `n` sources,
`nVar(OUTNOIZ, n)` is `noise_vals[1*n + n]` and `nVar(INNOIZ, 0)` is
`noise_vals[2*n + 0]` — the same address.

So `onoise_total_<dev>` came out bit-identical to
`inoise_total_<dev>_<first source>`: an input-referred, single-source number
reported as the device's output-referred total, a 2.24× error in the measured
case. Every built-in device's total matched its own components exactly, which is
what made the OSDI row stand out.

**What was never wrong:** the spectra and the grand totals. `onoise_spectrum`
matched two real 1 kΩ resistors to 9e-08 relative, and the grand `onoise_total`
already equalled the quadrature of the per-*source* entries. The regression test
therefore pins the spectrum **bit-identically against the pre-415 binary** rather
than against a derived value — the claim is that the analysis results did not
move, so that is what is asserted.

## One knob counted twice

`m` is registered as an alias of the model's `$mfactor` **with the same parameter
id**, so anything that walks the parameter table saw the multiplier twice:
`sens` listed both `<inst>_m` and `<inst>__mfactor` with identical non-zero
sensitivities, and summing the table double-counted it.

The obvious fix — flagging the alias `IF_REDUNDANT`, as built-in devices mark
theirs — was tried and **rejected by the regression**: that flag also hides the
keyword from listings, and `show n1` is required to list `m`
(Enhancement-397's suite went 126/127). Marking the *other* spelling instead
would have inverted the flag's meaning, since `spiceif.c` walks BACKWARDS from a
redundant entry to find its principal.

So the de-duplication happens where the repeat actually mattered: the sensitivity
generator skips a parameter whose id an earlier keyword in the same table already
claimed. `sens` lists the multiplier once, `show` still lists `m`, and `m`
remains settable from an instance line, a `.model` card and `alter` — all three
verified to give the identical answer.

## Three findings from the same hunt, deliberately NOT fixed here

**`absdelay()` / `last_crossing()` read 0 when their result is only observed.**
The most serious of the round — a delayed comparator never switches — and it is
not fixed, because the obvious explanation is wrong and I would rather ship
nothing than a plausible non-fix. The theory was that the DAE drops the implicit
equation as dead when the value never reaches a residual. That was implemented,
and the emitted descriptor then compared against the pre-fix compiler's:
**byte-identical** (`count=1, y_node=2, z_node=3, td_offset=152`). The equation
was never being dropped, the change was inert, and it was reverted —
`topology.rs` is untouched in this release. The loss is further down, in eval
codegen or the ngspice runtime. What is known: contributing the value with a
weight of **1e-30** makes it correct while `0.0*q` (constant-folded away) does
not, so the dependency is liveness in the contribution graph, not numerics; and
`ddt`, `idt`, `transition`, `slew` and `laplace_nd` are unaffected.

**`noise`/`tf`/`pz`/`sens` do not validate their output node.** A typo yields a
silent zero, or in `sens` a full table of zeros that reads like a valid
"insensitive" result. `dot_noise` already calls `ANALYSIS_NODE`; the hole is that
`inp_analysis_node` only rejects an unknown name *after* setup and during deck
parsing deliberately **invents** it, so that a card may legitimately precede its
own devices. Distinguishing a typo from a forward reference needs post-parse
connectivity analysis, and `CKTnode` carries no connection metadata.

**`@dev[p]` is unavailable for OSDI devices** while built-ins report it. A gap
rather than a wrong answer; it would be derived from the terminal currents
Enhancement-394 added.

## Verification

* **`examples/evtnoise_examples` 18/18**, and **12/18 on the pre-415 binaries**.
* The timer count is checked at three transient steps, plus the two composition
  cases that a naive fix would break: a model's own `$bound_step`, and a one-shot
  that must not pin the step.
* The noise total is checked against the quadrature of its own sources on both
  sides, with a built-in resistor in the same deck as the control, and the
  spectrum pinned bit-identically to the pre-415 binary.
* **Compiler suite 210/0.** **Full regression 332/332.**

## Found by

A one-hour hunt over ngspice + OSDI. The timer finding came from asking not
whether an event was *detected* but whether the simulator ever *stopped* where it
was due; the noise finding from the arithmetic simply not adding up — a device
total 2.24× its own only component, while every built-in beside it was exact.
