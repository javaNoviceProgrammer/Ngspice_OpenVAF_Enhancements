# Enhancement-347 — the SSA re-builder no longer mints an Invalid phi operand

Enhancement-329 fixed the **crash** a GRAVESTONE phi operand caused in the
small-signal network builder, and stated plainly what it was leaving open:

> the MIR that carries a GRAVESTONE phi operand is SSA-invalid, so the assertions
> build still trips `debug_assert!(cx.func.validate())` … The root fix is in the
> SSA re-builder (`mir_build/src/ssa.rs`).

This is that fix. The whole `.va` corpus — **496 files** — now compiles under an
assertions build with zero panics.

---

## The root cause is not where E-329 guessed

E-329 named the right *file* but the wrong *path*, and that mattered: the obvious
fix — repairing phis in `FunctionBuilder::finalize()`, where `mir_build` declares
a function complete — **did not work**, because those phis do not exist yet.

Measuring instead of assuming settled it. Instrumenting `finalize()` showed
exactly **one** phi at that point, carrying no `v0`. A backtrace armed at phi
creation showed where the gravestone actually comes from:

```
mir_build::ssa::SSABuilder::finish_predecessors_lookup
mir_build::SSAVariableBuilder::use_var           <- a SECOND SSA builder
mir_build::SSAVariableBuilder::define_at_exit
sim_back::topology::lineralize::builid_analog_operators
sim_back::topology::Topology::new
```

It is minted by **`SSAVariableBuilder`** — the *"add values to an already
finished MIR function"* builder — during topology linearisation, long after
`mir_build` is done. That accounts for every symptom, including the one that had
looked contradictory: `validate()` **passes** at `sim_back/src/lib.rs:175` and
**fails** at `:179`, on either side of `Topology::new`.

Two other candidates were instrumented and cleared on the way, so this is not a
guess by elimination:

- the topology builder's own phi rebuild already defaults unmapped operands to
  `F_ZERO` (`val_map.get(&val).copied().unwrap_or(F_ZERO)`) — traced, never fires;
- `try_remove_phi_edge*` in `mir/src/dfg/phis.rs` does write `GRAVESTONE` into an
  arg slot — traced, and the only write targets `inst11`, not the failing
  `inst27`/`inst30`.

An earlier hypothesis — that the operand was an unresolved **alias** at
`finalize()` time, since `value_def` reports `Invalid` for `Alias(_)` as well —
was tested and **refuted** by the same instrumentation.

## The fix

In `finish_predecessors_lookup`, the branch that builds a phi now substitutes a
**live sibling operand** for a GRAVESTONE:

```rust
let live = vals.iter().copied().find(|&v| v != GRAVESTONE);
…
if pred_val == GRAVESTONE {
    if let Some(live) = live { pred_val = live; }
}
```

Why a sibling and not a synthesised zero: a GRAVESTONE operand sits on an edge
out of a block unreachable from the entry, so the edge **cannot execute** and the
value on it is never read — any sibling is equally correct. And this builder is
**type-agnostic**: it holds `variables: TiVec<Place, TiVec<Block, …>>` and no
`Type` for the place, so a sibling is the only *type-correct* value available to
it. Minting `F_ZERO` would be wrong for an integer or boolean place.

A phi whose operands are *all* gravestones is left alone: there is nothing valid
to substitute, and such a phi is itself dead.

Fixing it here covers **both** callers — the `FunctionBuilder` path and the
`SSAVariableBuilder` path — which is what makes it the root fix rather than a
patch at one call site.

## Output preservation

The `--dump-mir` oracle over the whole corpus:

```
TOTAL 496   IDENTICAL 495   CHANGED 1   NONDETERMINISTIC 0
   CHANGED examples/vafssngravestone_examples/ssngravestone.va
```

The single changed model is the E-329 reproducer itself. Its diff is **value
renumbering only** — normalising `v\d+` makes the two dumps byte-identical, and
the value count drops from 131 to 130, exactly what reusing an existing sibling
instead of leaving a placeholder produces. The instruction sequence is untouched.

That model still computes the right answer: `ssn` and `ssn_ref` agree exactly at
`i = -5.0e-4`, `v = 0.5`, which is E-329's own criterion.

## Verification

| | |
|---|---|
| assertions build on the E-329 reproducer | **passes** (was `assertion failed: cx.func.validate()`) |
| **whole `.va` corpus under assertions** | **496 files, 0 panics, 0 assertion failures** |
| MIR A/B over the corpus | 495/496 identical; the 1 change is the reproducer, renumbering only |
| numerical result of the changed model | `ssn` == `ssn_ref` exactly |
| regression | 279/279 |

The three models in `examples/ssavalid_examples/va/` were each verified to
**trip** `assertion failed: cx.func.validate()` on a *pre-fix* assertions build
and to be clean after — they are proven triggers, not decoration. A fourth
candidate using a `for` loop instead of a `while` did **not** trip and was
dropped rather than shipped as filler.

## Reproducing the definitive check

`validate()` is `debug_assert`-only, so the shipped release binary cannot show
this. Build an assertions binary:

```bash
cd OpenVAF-master-20260610
CARGO_TARGET_DIR=target-assert RUSTFLAGS="-C debug-assertions=on" \
    cargo build --release --bin openvaf-r --features openvaf-driver/llvm18
```

then compile any model in `examples/ssavalid_examples/va/` with it.

`examples/ssavalid_examples/verify_ssavalid.py` checks what the *release* binary
can still prove: every shape compiles, reaches a finite operating point, and the
dead code contributes exactly zero — each shape bit-identical to a reference
circuit with the gravestone ingredients removed.
