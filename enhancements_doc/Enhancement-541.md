# Enhancement-541: the third LRM audit's nine findings, worked

**Scope:** the 2026-09-02 round-3 audit
([`docs/audits/2026-09-02_LRM-audit-round3.html`](../docs/audits/2026-09-02_LRM-audit-round3.html))
raised nine findings, every one about the **timing or addressing of what a
model says to the outside world**. All nine are fixed here.

**Suites:** [`examples/lrmvoice_examples/`](../examples/lrmvoice_examples/) is
new — **28 checks**, both solvers. Against the previously shipped binaries it
scores **11/28**, and the eleven passes are the compile checks plus four
deliberate controls, so every substantive check discriminates. Full sweep ALL
OK. **Both tools change.**

## The shape of all nine

Five of the nine are one sentence: **a guard exists, is correct, and does not
cover every route into the thing it guards.**

| the guard | covers | did not cover |
|---|---|---|
| LRM 9.4.6 display deferral | `$strobe`, `$display`, `$monitor` | `$error`, `$warning`, `$info` |
| the immediate-print tag | `@(initial_step)` | `analog initial` |
| ngspice's multiplicity check | the netlist `m=` | `#(.$mfactor(…))` |
| E-539's descriptor split | reserving bit 31 for file descriptors | the multichannel allocator, which still handed bit 31 out |
| E-539's mode-change reopen | write → read | read → write |

In every case the reasoning that produced the guard applies unchanged to the
uncovered route, which is why none of these fixes needed a new mechanism —
four of the five are the existing mechanism, applied to one more case.

## `analog initial` said nothing at all

LRM 5.2.1 gives the block one job — *"simulation initialization purposes"* —
and then forbids access functions, analog operators, contribution statements
and event control statements inside it. What remains is assigning variables and
**reporting**. The reporting half produced no output whatsoever.

One module, one `analog initial` block, three analyses:

| task | before | after |
|---|---|---|
| `$debug` | 3 lines | 3 lines |
| `$info` | 3 lines | 3 lines |
| `$strobe` | **0** | 3 lines |
| `$display` | **0** | 3 lines |
| `$write` | **0** | 3 lines |
| `$monitor` | **0** | 3 lines |
| `$fdisplay` to a file | **0 bytes**, file created | 3 lines |

`$debug` and `$info` printing three times each is what makes this readable: the
block demonstrably **ran** in every analysis, and only its output was thrown
away.

**Cause.** `hir_lower/src/lib.rs` lowers the block into the eval function under
`make_cond(ParamKind::IsInitialStep, …)` — E-456's fix, and correct for what it
was for. But that puts its statements on the instance's **first** Newton
iteration of an analysis, which is precisely the iteration the 9.4.6/9.5.9
deferral treats as superseded: `osdi_log` buffered the output and the next
`osdi_display_iter_begin` dropped it.

The compiler already has the concept. `stmt.rs` sets `in_event_ctx` while
lowering an event-controlled statement, and the comment above that assignment
states the hazard exactly, for the neighbouring construct: *"the event fires on
its own Newton iteration, so deferring their output to the accepted iteration
(LRM 9.4.6) would drop it entirely."* A new `in_analog_initial` flag joins it,
and `ins_display` tags on either. The file half needed nothing further — the
same flag already drives `osdi_fputs`'s `immediate` argument.

This is the **third** appearance of one hazard: E-516 handled it for
event-gated statements, E-535 (hunt N5) for re-entered setup code, and the
`analog initial` route was still open.

## The severity tasks ran on every Newton iteration

LRM 9.7.3 states the rule for this family in its own words rather than by
reference to 9.4.6:

> Non-fatal system severity tasks (`$error`, `$warning`, `$info`) called during
> a **rejected iteration shall have no effect**. `$fatal` terminates the
> simulation without checking whether the iteration would be rejected.

One diode `.op`, with `$strobe` and `$warning` on adjacent lines of the same
analog block:

| | before | after |
|---|---|---|
| `$strobe` | 1 line, at `v=0.629443` | 1 line, unchanged |
| `$warning` | **21 lines**, `0 → 1.000000 → 0.974135 → … → 0.629443` | **1 line**, at `v=0.629443` |

That is verbatim the August audit's headline — *"every display fired on every
Newton iteration"* — surviving on the one family its remediation did not sweep.

**Cause.** `ngspice-46/src/osdi/osdicallbacks.c`, one condition:

```c
if (display_managed &&
    (level == LOG_LVL_DISPLAY || level == LOG_LVL_MONITOR) &&
    !(lvl & LOG_FLAG_IMMEDIATE)) { ... defer ... }
```

`LOG_LVL_INFO`/`WARN`/`ERR` fell through to the immediate print. The three are
added; `LOG_LVL_DEBUG` and `LOG_LVL_FATAL` deliberately stay out, each for its
own clause — 9.4.6 exempts exactly `$debug`, and 9.7.3 says `$fatal` does not
check. The suite pins `$debug`'s exemption as a check rather than a comment,
because a fix that deferred everything would also stop the 21 lines.

**Prior art, and it is partial.** E-516 contains the parenthesis *"(`$fdebug`/
severity tasks keep their immediate paths)"*, inside a paragraph about event
gating, with no clause cited — and thirty-four lines earlier the same document
states the exemption as *"only `$fdebug` exempt"*. So the behaviour was chosen,
but chosen by grouping the severity tasks with `$debug`: the one task 9.4.6
exempts and the one task 9.7.3 does not cover.

## `$error` in an `analog initial` block let the run proceed

> If `$error` is executed within an `analog initial` block, then the message is
> issued and the initialization continues. However, **the simulation shall not
> proceed past initialization.** — LRM 9.7.3

The message printed and the operating point ran to completion and handed the
deck `v(1) = 1`. This is the standard's designated way for a model to reject a
parameter combination it cannot serve.

The mechanism to stop was already wired up and correct — the same model with
`$fatal` aborts exactly as it should. `$fatal` lowers to a display **plus**
`SetRetFlag(RetFlag::Abort)`; `$error` emitted the display and nothing else.

A new `RetFlag::InitErr` / `EVAL_RET_FLAG_INITERR` carries the weaker
requirement, and the distinction from `Abort` is real rather than cosmetic:
`$fatal` abandons the evaluation, while `$error` must let the initialization
**finish** — the block runs to its end, the message prints, the matrix loads —
and only then stop the analysis. `$error` outside an `analog initial` block
raises nothing, which is all 9.7.3 asks for there.

`CKTop` reports it under its own flag rather than reusing E-492's
`CKTvaFatalRaised`, so the message names the task that actually ran:

```
Error: a Verilog-A device raised $error in an analog initial block; the analysis is not run.
       This is not a convergence failure -- see the OSDI(err) message above for the cause.
       LRM 9.7.3: initialization completes, then the simulation shall not proceed past it.
```

## …and none of the four reported when they were called

Same clause, unmet in a second way:

> these tasks **shall also report the simulation run time** at which the
> severity system task is called. If any of these tasks is called from an
> analog context **during a dc sweep**, the simulator shall report the current
> value of the swept variable in place of the simulation run time. If the task
> is called from an **`analog initial` block**, the simulator shall report that
> the call was made during initialization.

Messages carried the instance name and nothing else, in every analysis — the
same complaint 9.4.4 makes about `%m`, on a family where the LRM spells the
requirement out.

```
OSDI(warn) n1: v is high (0.75) (at sweep value 0.75)
OSDI(warn) n1: v is high (0.5312) (at t = 5.312e-07)
OSDI(err)  n1: ERR-in-initial (during initialization)
```

Two details are load-bearing.

**The context is a trailing parenthetical, not part of the head.** The head
stays the stable `OSDI(warn) <inst>: ` that every reader — and three checks in
`simparamdiag_examples` — already matches on.

**It is resolved at output time, not when the message is formatted.** During a
`.dc` sweep `CKTtime` only takes the point's swept value *after* the solve that
produced the message, so a context baked in at format time reported the
**previous** point's value. The first version of this did exactly that, and
`(at sweep value 0.5)` on a message raised at 0.75 is how it was caught.

Only the severity family gets the context; `$strobe` and `$display` are
untouched.

## A negative `$mfactor` from Verilog-A sign-inverted the device

LRM 9.18 Table 9-29's *Allowed values* column reads `$mfactor > 0`. A plain
resistor model:

```
leaf #(.$mfactor( 3)) -> i(v1) = -3.00000e-03    correct: sinks 3 mA
leaf #(.$mfactor(-3)) -> i(v1) = +3.000000e-03   the resistor SOURCES 3 mA
```

with no diagnostic on any channel. The identical value on the netlist line has
been refused all along, by a message that spells out the consequence:

```
Warning: n2: multiplier m=-3 is negative; the device's contribution is
sign-inverted (a passive device becomes active) and any noise contribution
becomes NaN.
```

So the hazard was understood and the check simply did not cover the Verilog-A
route. There was even a *second* partial guard: give the leaf a `white_noise`
contribution and the compiler rejects the same model, because the noise scaling
divides by `sqrt($mfactor)` and the constant-folded `sqrt(-3)` trips the domain
check. A model without noise got no such luck.

A literal instance override is now judged against Table 9-29 where it is
collected (`hir/src/elaborate.rs`):

```
error: instance parameter '.$mfactor' is set to -3, which LRM 9.18 Table 9-29
does not allow ($mfactor > 0 -- a multiplicity is a count of devices in
parallel, and a negative one sign-inverts every flow contribution the instance
makes)
```

**Only a literal is judged**, which is the same boundary the constant-only
`sqrt` domain check draws: an override built from a paramset card parameter is
not known until run time. Stating that boundary is better than guessing at it.

`$hflip`/`$vflip` get the same treatment (`+1` or `-1`), on both routes —
ngspice's parameter setter now warns and ignores an out-of-range flip exactly
as it does a negative multiplier. **`m=0` on the netlist is untouched**:
E-426 established it as the "disable this instance" idiom, it is a SPICE
convention rather than an LRM one, and this change does not relitigate it.

## `$angle` was never reduced modulo 360

Table 9-29 gives `$angle` the resolution rule *"`$angle`<sub>specified</sub> +
`$angle`<sub>hier</sub>, **modulo 360 degrees**"* and the range
*"0 ≤ `$angle` < 360"*. The sum was implemented; the modulo was not.

```
top -> mid #(.$angle(200)) -> leaf #(.$angle(200))
   before:  angle = 400        after:  angle = 40
```

A model that *uses* the angle trigonometrically is unharmed — 400° and 40° have
the same sine — which is why this could sit unnoticed. A model that **compares**
it is not: `if ($angle < 90)`, a quadrant lookup, or a table keyed on
orientation all take the wrong branch, and the LRM's range is exactly the
contract such a model is entitled to rely on.

The value is normalised at every point where one is materialised, so every
route lands in range: the plain read (`hir_lower/src/expr.rs`, which is what a
netlist `_angle=` reaches), the textual read-rewrite that applies an instance
override (`hir/src/elaborate.rs`), the MIR composition for paramset overrides
(`hir_lower/src/state.rs`), and ngspice's own instance-parameter setter.

`x - 360*floor(x/360)` rather than a `%`: the value is a real, and this form is
the correct non-negative remainder for a negative angle too (−90 → 270), which
C's `fmod` and Verilog's `%` are not.

## The thirty-first multichannel descriptor was the reserved bit

> The most significant bit (bit 31) of a multichannel descriptor is **reserved
> and shall always be cleared**, limiting an implementation to at most 31 files
> opened for output via multichannel descriptors. — LRM 9.5.1

Bit 0 is stdout, so the allocatable range is bits 1–30. The allocator scanned
to bit 31:

```
$fopen("e29.txt") -> 1073741824   (bit 30)  ok, the last legal one
$fopen("e30.txt") -> -2147483648  (bit 31)  before: allocated
                  -> 0                      after:  the clause's own failure value
```

The consequence is specific to this tree. [E-539](Enhancement-539.md)
implemented the clause's two-namespace split by taking bit 31 as the
file-descriptor marker (`OSDI_FD_BIT`), with `0x8000_0000` itself being
**STDIN** — so the thirty-first multichannel descriptor was bit-identical to a
pre-opened read-only stream, and a `$fdisplay` to it reached neither the file
nor stdout. The clause's own arithmetic is the check that was not applied.

## A reopen in a different mode was ignored, and the writes vanished

Table 9-24 gives `"w"` as *"truncate to zero length or create for writing"*.
Read a file, `$fclose` it, reopen it for writing, and the descriptor handed back
was the **read-mode stream**: nothing was truncated and every write disappeared
without an error.

```
control   $fopen("a") with no prior open   -> appended, correct
finding   read, close, $fopen(name,"w")    -> same descriptor as the read open
                                              file untouched, write lost
```

E-539's comment on the neighbouring branch names the general rule — *"reopening
a write-mode stream for reading is a MODE CHANGE and needs the freopen below"* —
and implemented it for that direction. The read → write direction is the half
that was still open, and it failed **silently**, where the write → read case it
fixed at least produced visibly wrong data.

`osdi_fopen`'s same-name dedup now `freopen`s whenever the requested mode asks
for a capability the stream does not have, in either direction. One detail is
not optional: the descriptor's queued deferred writes are performed **before**
the reopen. The model has closed the file, so those writes are owed to it — a
reopen for reading must be able to see them, and the `freopen` would otherwise
strand them on a stream that no longer exists. That is not a hole in the 9.5.9
deferral: it is the point at which a real `fclose` would have flushed too.

**One version of this was wrong, and the suite estate caught it.** The first
implementation also applied 9.5.1.1's append-on-rewrite rule on this path, which
looks like consistency and is not: 9.5.1.1 is about *"content written from the
following **analyses**"*, while ngspice runs instance initialization **twice**
per analysis (setup and temperature). A model that writes a file, reads it back
and writes it again therefore appended its second run's output onto its first's
instead of reproducing it — breaking the byte-for-byte re-run guarantee E-516
had established. Nothing in the check output moved; `stringio_examples`'
committed round-trip artefacts did, one line becoming two, which is the whole
reason those files are in the repository. The requested mode is now honoured
verbatim here, and 9.5.1.1 stays on the fresh-open path a following analysis
actually reaches.

## `$write` could not compose a line

> The `$write` task provides the same capabilities as `$strobe`, but with **no
> newline**. — LRM 9.4.1

Suppressing the newline has one purpose, and the per-call instance prefix
defeated it:

```
$write("[A]"); $write("[B]"); $write("[C]\n");
  before:  OSDI n1: [A]OSDI n1: [B]OSDI n1: [C]
  after:   OSDI n1: [A][B][C]
```

The head is now written only at the **start of a line**, tracked per stream.
Every other display task ends its text with a newline, so each of those still
carries its own head and nothing else changes — which the suite pins with a
`$strobe` immediately after the three `$write`s.

## LRM 9.20's other two error rules

The clause states three *"shall be an error"* rules for
`$analog_node_alias`/`$analog_port_alias`. Only the context rule (a call outside
an `analog initial` block) was enforced. Both others compiled clean:

* **the aliased net is a port** — *"it shall be an error for the
  analog_net_reference to be a port or to be involved in port connections"*;
* **the target is another call's aliased net** — chaining one alias onto
  another, which has no defined resolution.

The first is decided exactly. The second is judged only where it does not need
hierarchy resolution: the target's last path segment names a node of **this**
module that another call in it aliases. A path into some other instance is left
alone rather than guessed at — a false error on a legal alias would be worse
than the missing one this closes, and the limit is stated rather than hidden.

Severity is genuinely low here: both functions are a documented always-return-0
stub, so nothing numerically wrong followed. It is fixed because the tracker's
wording, *"their 9.20 context rule is enforced"*, reads as covering the clause.

## Compatibility

Two **additive** ABI bits, following E-55's precedent:

* `EVAL_RET_FLAG_INITERR` (32) — an older simulator ignores an unknown return
  bit and gets exactly today's behaviour;
* `LOG_FLAG_INIT` (32) — an `.osdi` from an older compiler never sets it, and a
  message without it reads as before.

A new model on an old ngspice therefore loses only the two behaviours those
bits carry; nothing crashes and nothing changes meaning. An old model on the
new ngspice gets the severity deferral and the `$write` composition (both
simulator-side) and not the rest.

Two behaviours change for existing decks, both deliberately:

* a `$warning`/`$error`/`$info` in a model that used to print per Newton
  iteration now prints once per accepted point — which is the fix;
* those three messages gain a trailing `(at …)`. The head is unchanged, so
  matches on `OSDI(warn) <inst>: <text>` still hold.

## What was deliberately not changed

* **`m=0` on a netlist line** stays silent and applied (E-426's "disable this
  instance" idiom). The Verilog-A `#(.$mfactor(0))` route is refused, because
  Table 9-29 governs it and the SPICE convention does not.
* **`$strobe`/`$display` carry no time context.** LRM 9.7.3 asks for it on the
  severity tasks; 9.4 does not ask for it on the display tasks, and adding it
  would rewrite the output of every model in the corpus.
* **Constant-argument display hoisting** remains as documented at the split
  (E-516, and the compliance tracker §7.1). It reproduced during the audit and
  is prior art, not a finding.

## Files

**Compiler:** `hir_lower/src/{ctx,lib,fmt,callbacks,expr,state}.rs`,
`hir_ty/src/validation{,/body}.rs`, `hir_def/src/builtin.rs`,
`hir/src/elaborate.rs`, `osdi/src/compilation_unit.rs`,
`osdi/src/metadata/osdi_0_4.rs`, `osdi/header/osdi_0_4.h`, `osdi/stdlib.c`,
`openvaf/tests/load/osdi_0_4.rs`.

**Simulator:** `src/osdi/{osdicallbacks.c,osdiload.c,osdiparam.c,osdi.h,osdidefs.h}`,
`src/include/ngspice/cktdefs.h`, `src/spicelib/analysis/cktop.c`.

**Suite:** `examples/lrmvoice_examples/` (28 checks, both solvers).
