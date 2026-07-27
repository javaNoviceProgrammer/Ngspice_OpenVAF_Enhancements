# Enhancement-332 — summing three or more `ddt()` terms silently dropped charge

A wrong number, not a crash. This compiles cleanly and is a **1 F** capacitor:

```verilog
I(a, b) <+ ddt(V(a,b)) + ddt(V(a,b)) + ddt(V(a,b));   // must be 3 F
```

Two terms were correct, which is why it survived. Measured across N:

| N terms | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| shipped | 1 | 2 | **1** | **1** | **1** |
| fixed | 1 | 2 | 3 | 4 | 5 |

It is reachable from entirely ordinary code — a `generate` loop is unrolled at
compile time, so this is the same expression and was equally wrong:

```verilog
generate k (0, 2)  s = s + ddt(V(a,b));    // 3 F; shipped gave 1 F
```

## Root cause — a traversal order, not `ddt`

`create_dimension` (`sim_back/src/topology/builder.rs`) replays the instructions
that consume an analog operator's result to build its linear coefficient. Its
`Fadd`/`Fsub` arms read:

```rust
(None, Some(&arg)) | (Some(&arg), None) => Some(arg),
```

which *means* "the unmapped operand does not depend on the dimension". That is
sound **only** in a topological order, where every operand has already been
replayed.

`postorder` does not provide one. `Postorder::populate` (`mir/src/dfg/postorder.rs`)
pushes **every** use of the operator's result onto its stack up front and marks
each visited *on push*. When one of those uses feeds another, the earlier-pushed
one is popped — and emitted — first. For `(t+t)+t` the traced order was:

```
inst4  fadd [v19, v17]   <- (t+t)+t   replayed FIRST
inst2  fadd [v17, v17]   <- t+t       replayed LAST
```

So replaying `(t+t)+t` looked up `v19`, found it unmapped, concluded it was
dimension-independent, and **dropped** the 2 F term instead of adding it —
leaving 1 F. With two terms there is no nested sum, so nothing is lost.

The unoptimised MIR was correct throughout (three `ddt` calls, correctly summed);
only the DAE linearisation lost the term.

## The fix

Sort into a real topological order before replaying, in the consumer rather than
in the shared traversal (`small_signal_network` uses the same `Postorder`, and
this keeps the change contained). Instructions in a dependency cycle — phi back
edges — keep their previous relative order, matching the phi deferral the replay
already performs deliberately.

## A second defect, found while verifying

With the charge fixed, `repeat (3) s = s + ddt(V(a,b));` gave **0 F**. That shape
is ill-formed: LRM 4.5.1 forbids analog operators in non-genvar loops, and `for`
and `while` already rejected it. `repeat` slipped through because the generic
check consults `ctx`, which only becomes `BodyCtx::Loop` when the loop's
controlling expression is **non-constant** — so a literal trip count evaded it.

Enhancement-330 introduced a `loop_depth` counter for exactly this reason but
applied it only to `ddx`. It now covers every analog operator, so the diagnostic
no longer depends on whether the trip count happens to be a literal:

```
for     -> error: analog operator 'ddt' is not allowed in loops
while   -> error: analog operator 'ddt' is not allowed in loops
repeat  -> error: analog operator 'ddt' is not allowed in loops   (was: accepted)
```

`report_illegal_access` also had to report the context the check actually used;
otherwise a `repeat` was described as being in an "analog block", naming the
wrong construct and omitting the loop rule.

## Verified

- **Two independent oracles agree.** AC (`|I| = 2*pi*f*C`) and transient (a 1 V/s
  ramp, `I = C dV/dt`) both give exactly N farads for N = 1..8. A single oracle
  could have been an artifact of the AC path; charge is what actually changed.
- **Every other analog operator was checked for the same defect** — summing N
  copies of any linear contribution must give N times one copy:

  | operator | shipped | fixed |
  |---|---|---|
  | `ddt` | **wrong at N>=3** | correct |
  | `idt`, `idtmod`, `ddx`, `transition`, `slew`, `absdelay`, `laplace_nd`, `zi_nd` | correct | correct |
  | `white_noise`, `flicker_noise` | correct (N independent sources add in power, so amplitude scales as sqrt(N)) | correct |

  `ddt` was the only one affected, and nothing else moved.

## Corpus impact — measured, not assumed

Across all 475 corpus models: **0 changed accept/reject**, 9 changed MIR. Of those:

- **HICUM x3** (`hicumL2V2p4p0`, `hicumL2V3p0p0`, `hicumL2_v310`) — **semantically
  identical**. Canonicalising value numbering makes the dumps equal; the diff is
  renumbering caused by the new instruction creation order.
- **Angelov x2** — 3 restored `fadd`s. The model sums several `ddt` contributions
  into one branch (`I(gdi,di) <+ ddt(Qgd)` alongside `I(gdi,di) <+ ddt(Cgd*Vgdc)`),
  i.e. exactly the affected shape. DC operating point and all AC quantities are
  numerically **identical** at a bias with the capacitances enabled, so the
  restored terms sit on a path that configuration does not activate.
- **3 LRM examples** (`lrm_p209_1`, `lrm_p091_1`, `lrm_p134_1`) — fail to compile
  on **both** binaries (they live in `ams/` and `limitations/`). Two gain one
  extra diagnostic on a model already failing with `'k'/'i' was not found in scope`.
- `lrm_p150_1` also differs, but that file is nondeterministic for an unrelated
  reason (implicit nets get hash-ordered internal IDs); it is noise, not this change.

## Known limitation, stated rather than hidden

The generalised loop check keys on `loop_depth`, which counts every loop form. In
a **genvar** `for` loop analog operators are legal (the loop is unrolled), so such
a loop should be exempt. It is not, today — harmless only because openvaf does not
support `genvar` in a plain `for` at all (`'k' was not found in the current
scope`), so such a model already fails for an earlier reason. The supported
unrolling form, `generate k (a,b)`, does **not** increment `loop_depth` and is
unaffected — verified, and it is the form the example uses. If `genvar`-in-`for`
is ever implemented, this check must become genvar-aware. Adding that gating now
would be untestable code for an unreachable path, so it is recorded here instead.

## Files

- `OpenVAF-master-20260610/openvaf/sim_back/src/topology/builder.rs` — the
  topological order (`dfg_topo_order`) and its use in `create_dimension`.
- `OpenVAF-master-20260610/openvaf/hir_ty/src/validation/body.rs` — `loop_depth`
  generalised to every analog operator, and the context actually used reported.
- `examples/vafddtsum_examples/` — N terms give N farads (AC **and** transient),
  the `generate` form is correct, and every loop form rejects alike
  (`verify_vafddtsum.py`, 5 checks).
