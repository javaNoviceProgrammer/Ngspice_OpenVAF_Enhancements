# Enhancement-417 — the collapse is decided once, and three things forgot

A Verilog-A node collapse (`V(d,di) <+ 0`) is decided inside `setup_instance`,
and everything that matters is built from that single decision: the node
mapping, the matrix element pointers, the state layout, Enhancement-416's
collapse-owner map. `OSDItemp` re-runs `setup_instance` on every temperature
update — so the decision can be **re-made** — but it cannot rebuild any of them.

`osdisetup.c` had said so for years, in a comment and a question:

```c
/* OSDI does not differentiate between setup and temperature update so we just
 * call the setup routines again and assume that node collapsing (and therefore
 * node mapping) stays the same */
...
      // TODO check that there are no changes in node collapse?
```

Nothing checked. Three separate consumers reported confidently on a topology the
matrix did not implement.

## 1. `sens` printed roundoff and called it a derivative

`sens` perturbs each parameter and differences two loads. When the parameter is
the one selecting the collapse, the perturbed device stamps a topology that does
not exist in the matrix — and the failure is not a small error, it is a different
quantity.

With the collapse taken, `init_matrix` maps **four** Jacobian entries — (d,d),
(d,di), (di,d), (di,di) — onto the **one** matrix element the merged node owns.
The perturbed load writes `+g, −g, −g, (g+gs)` into that single element with
`g = 1/δ = 1e6`. Algebraically that is `gs`. In IEEE double it is not:

```
perturbed diagonal = 0.0010000000474974513
base diagonal      = 0.001
difference         = 4.7497e-11        <- 0.214 ulp of g
```

Divided by `δ = 1e-6`, what reaches the user is `eps·E/(Y·δ²)`: a number with no
relation to the derivative, whose magnitude tracks `1/rd` and whose **sign moves
with unrelated parameters**. In the shipped example it printed `2.5289e-02`
where the true derivative is `2.2676e-04` — 112× — and the hunt's original case
printed `−2.59e-02` against a true `+1.8157e-06`, 14000× and the wrong sign.

It cannot be computed correctly here. `DEVsetup` runs only at the base value,
and re-running it after the perturbation would allocate nodes and trip
`cktsens.c`'s own guard:

```c
if (node != ckt->CKTlastNode) {
    fprintf(stderr, "Internal Error: node allocation in DEVsetup() during sensitivity analysis, ...");
    controlled_exit(EXIT_FAILURE);
}
```

So the parameter is now reported as **0** and said out loud, naming the exact
instance and parameter. A knowingly-inert row plus a warning beats a plausible
number that is pure roundoff. Every other row of the same table is untouched,
and away from the boundary `sens` still computes the real sensitivity —
`rd = 1e-2` gives `2.2676e-04`, matching the deck-rewrite finite difference to
1e-3 relative.

## 2. A `.dc temp` sweep ran the whole range on one topology

`.temp` and `set temp` were always correct, because each re-does the setup. The
sweep does not, and it failed in **both** directions:

* **Into** a collapse — the `d–di` branch loses its equation, the terminal is
  left floating, and the source current reads **exactly 0**.
* **Out of** a collapse — the collapsed topology is kept, so the series element
  that should appear never does: **1 mA where the truth is 500 µA**. A
  plausible-looking 2× error is the more dangerous of the two.

Rebuilding mid-sweep is not a fix, it is a re-architecture. It would have to
allocate and delete nodes (changing `CKTmaxEqNum` and the size of `CKTrhs`,
`CKTrhsOld`, `CKTirhs`, `CKTsolution`, `CKTstates`), call `SMPmakeElt` on a
matrix that has already been ordered and factored — a hard no under KLU, whose
symbolic factorization is fixed — and invalidate every *other* device's cached
`double *` element pointers. `DCtrCurv` also holds live state across the point
and the output plot's vector set was fixed at `OUTpBeginPlot`.

So the sweep now **warns**, once per instance, naming the instance, the model
type and the temperature, and pointing at the thing that does work:

```
Warning: n1: node collapse of model type 'cs_gate' changed at 353.1 K, but the
matrix was built for the collapse decided at setup and cannot be rebuilt here.
         Results for this device are NOT trustworthy at this temperature. Run
         each temperature as its own analysis (.temp / set temp), which re-does
         the setup.
```

Not an error: making it one means propagating five bare `CKTtemp(ckt);` returns
in `dctrcurv.c`, which changes error handling on `.dc temp` for **every** device
model in the tree, not just OSDI. That is a much wider blast radius than the
defect, so it is deliberately not taken here.

### The detection had one trap, and it is the whole fix

`OpenVAF`'s collapse callback only ever **stores true** — `sim_back` writes a
hint, it never retracts one — and ngspice clears the flags in exactly one place,
`OSDIunsetup`. So a naive "call `setup_instance`, compare" sees nothing when a
collapse *stops* happening: the stale `true` persists, and that is precisely the
direction this defect takes. `OSDItemp` therefore clears the flags first, then
re-decides, then compares against a snapshot taken in `OSDIsetup` — and restores
the snapshot unconditionally, **before** the error check, because the matrix
implements the snapshot and every consumer downstream has to keep seeing it.

The snapshot rides in the instance block beside Enhancement-416's owner map: one
`bool` per collapsible pair, both per-descriptor constants, so `DEVinstSize`
stays fixed per device type.

Under `sens` the temperature-flavoured warning is suppressed — the trigger there
is a parameter, not the temperature, and `cktsens.c` reports it per parameter
with the right wording. It does not burn the once-per-instance warning either, so
a later sweep still gets it.

## 3. `savecurrents` skipped per-terminal names at two terminals

Enhancement-413 expanded `.options savecurrents` into `@dev[i_<term>]` once the
descriptor was known — but bailed out at exactly two terminals, on the reasonable
grounds that `@dev[i]` already works there:

```c
if (n == 2) {                       /* `@dev[i]` is defined there */
    ...
    return 0;
}
```

`@dev[i]` does work. `@dev[i_p]` did not: it stayed a **length-1 scalar**, so
`meas tran … @n1[i_p]` silently reduced a waveform to one settled point. That is
the exact shape Enhancement-413 existed to remove, surviving at a different
terminal count — and it is what produced the incorrect "2.1e-3 gap" recorded in
Enhancement-416's own notes (see below).

The expansion is now unconditional, and `ft_getSaves` **keeps** the bare name
beside it rather than replacing it, so two-terminal decks gain `i_p`/`i_n`
without losing the `i` that Enhancement-394 defines for them and that existing
decks use. Measured on a 1 kΩ ‖ 1 nF device over a 120-point transient:
`len(i_p)` goes 1 → 120, `i_p − i` is **exactly 0** at every point (they are the
same parameter id), and `i_n + i_p` is **exactly 0**.

Expansion now runs on explicit `.save @dev[i]` entries too, which is the same
thing that already happened at three or more terminals. Because a synthesized
name can now collide with one the deck asked for outright, `ft_getSaves`
de-duplicates: the pre-existing dedup runs on `db_nodename1` at insert time and
cannot see anything synthesized here.

## 4. A correction to Enhancement-416's own notes

Enhancement-416 recorded, under "deliberately not changed", that a transient
terminal current disagrees with the source current by ~2e-3, that a plain
two-terminal `R‖C` shows the same, and that "it does not shrink with `reltol`
(so it is not Newton convergence)". **Both claims were wrong**, and the
measurement behind them was defect 3 above: `@n1[i_p]` was a length-1 scalar
being compared against a waveform.

| | |
| --- | --- |
| plain `R‖C`, using the vector that is actually saved | **1.31e-15** — no gap at all |
| HICUM/L2, 1032-point waveforms, `reltol=1e-3` | 4.73e-04 |
| HICUM/L2, `reltol=1e-6` | **7.9e-15** — eight orders |

The gap that does exist on a multi-terminal model **is** Newton convergence.
`Enhancement-416.md` is corrected in place, since a wrong note in a shipped
document misdirects whoever picks up the open item.

## Noted, and deliberately NOT fixed: `%m` names the module, not the instance

`$strobe("%m")` prints the **module** name, so three distinct instances — `na`
at top level and `nb` inside two different subcircuits — all print `cs_gate`.
Identifying the instance is the entire purpose of `%m`, and the information is
demonstrably available: `$info`/`$warning`/`$error` from the same model already
come out as `OSDI(warn) n1: …`.

It is not an ngspice defect at all. The compiler splices the module name into
the format **string constant** at compile time —
`hir_lower/src/fmt.rs`, `'m' | 'M' => fmt_lit.push_str(self.path)` — and
`osdi/src/compilation_unit.rs` emits that constant as parameter 1 of the print
stub. By the time the simulator sees the text there is nothing marking where
`%m` was, so no simulator-side fix is possible.

The clean fix is a handle→name callback mirroring `osdi_log`, which needs **no**
ABI change (it is a `dlsym` into a global slot, not an `OsdiDescriptor` field).
It is not taken here because of how that slot is initialised: the compiler sets
it to a **null pointer** (`let val = cx.const_null_ptr()` in `osdi/src/lib.rs`)
and relies on the simulator to bind it. A model compiled by a new `openvaf-r`
and run on an older ngspice would therefore call NULL — the Enhancement-396
`$limit` SIGSEGV class, bought for a cosmetic gain. Doing it safely means
emitting a fallback function into the `.osdi` so an unbound slot degrades to
today's behaviour, which is real codegen work in a part of the compiler this
change does not otherwise touch.

Two adjacent compiler-local observations, recorded and also not acted on: inside
a user analog function the path is `module` + function concatenated with no
separator (`expr.rs`), so `%m` there prints `cs_gatemyfunc`; and parameter-context
bodies construct the lowering context with an empty path, so `%m` expands to
nothing.

## Verification

* **`examples/collapsestate_examples` 22/22**, and **13/22 on the pre-417
  binaries** — nine checks flip, so the suite discriminates rather than merely
  passing. Both solvers.
* `sens` is pinned on both sides of the boundary: the collapsed row is 0 **and**
  warned, the uncollapsed row still equals the deck-rewrite finite difference,
  and the other parameters' rows are unchanged. The finite-difference reference
  rewrites the deck per point — never `alter`, which does not reach a model-only
  parameter at all and silently returns the unperturbed answer.
* The `.dc temp` sweep is checked in **both** directions against a `.temp`
  oracle, plus the negative control that matters: a model whose collapse does
  **not** move stays quiet and returns the identical value at every temperature.
* `savecurrents` is checked for the alias identity (`i_p == i` exactly), KCL
  (`i_n == −i_p` exactly), that the waveform is the ~1 A capacitive one rather
  than the settled 1 mA, that a three-terminal device still names `i_d`/`i_s`,
  and that neither `.save @n1[i]` nor `.save @n1[i_p]` beside `savecurrents`
  produces a duplicate vector.
* **Full regression 334/334**, which is the gate that matters here: the
  `OSDItemp` clear/compare/restore runs on every temperature update of every
  OSDI instance in every analysis.

## Found by

A one-hour hunt over ngspice + OSDI. All three defects are the same sentence
read three ways — the collapse is decided once and re-decided later, and nothing
noticed. The `sens` one was found by asking what the reported number *was*, once
it was clear it was not a derivative: it tracked `1/rd` and changed sign when an
unrelated parameter moved, which is the signature of a cancellation, not a slope.
