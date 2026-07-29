# Enhancement-353 — `.disto` for Verilog-A models that use `$limit`

> **Superseded by [Enhancement-359](Enhancement-359.md).** `$limit` models still
> work — the seven-shape suite below passes unchanged — but the chain-fold this
> enhancement added no longer exists. E-359 differences the Jacobian the
> simulator actually uses, so a limited model needs no special handling at all:
> the problem this solved cannot arise. Retained as the record of why limiting
> models were invisible to the original symbolic design.

[Enhancement-352](Enhancement-352.md) gave Verilog-A devices distortion
analysis, but only for models that read their controlling voltages directly. A
model that passes one through `$limit` contributed **nothing at all** — and
limiting is how every production diode, BJT and MOS model converges, so the
feature did not reach the models people actually run.

| shape | chain lengths | before | after |
|---|---|---|---|
| single limited branch | 2 | *no tensors* | `rel 1.0e-09` vs the unlimited twin |
| two limited diagonals | 2, 2 | *no tensors* | `rel 6.9e-10` |
| cross term, both limited | 2, 2 | *no tensors* | exact |
| cross term, one limited | 2, 1 | *no tensors* | exact |
| third-order cross term | **3**, 2 | *no tensors* | exact, IM3 included |
| reversed-branch limit | 2 (one negated) | *no tensors* | exact, sign correct |

---

## Why a limiting model looked linear

`$limit` hands the model a *limited* copy of a branch voltage, and the residual
is written in terms of that copy. Differentiating the residual by the **raw
voltage read** therefore yields zero: nothing in the expression depends on it.
The model is not linear, but every derivative the tensor pass asked for was.

This is not a new problem — `build_jacobian` has always folded the limited
values back in, via `intern.lim_state`, which is why AC and transient were
always right. Enhancement-352's `build_taylor_tensors` simply did not perform
the same fold.

## The fix

Each model input maps to a **chain** of autodiff unknowns rather than a single
one:

```rust
fn taylor_unknown_chain(&self, val: Value, derivatives: &KnownDerivatives)
    -> Vec<(Unknown, bool)> {
    let mut out = Vec::new();
    if let Some(lim_vals) = self.intern.lim_state.raw.get(&val) {
        for (lim_val, negate) in lim_vals {
            if let Some(u) = derivatives.unknowns.index(lim_val) { out.push((u, *negate)); }
        }
    }
    if let Some(u) = derivatives.unknowns.index(&val) { out.push((u, false)); }
    out
}
```

The second-order pass then sums over every pair drawn from the two chains and
the third-order pass over every triple, each term carrying the XOR of its
entries' signs — a chain entry can be negated when the model limits a **reversed**
branch, `$limit(V(ref,a), …)`.

Nothing changed in ngspice: it already consumes whatever tensors the model
publishes. The OSDI ABI is unchanged too — this is a compiler fix, so 0.8
descriptors from before and after are interchangeable.

## Verification

`$limit` is a convergence aid: at convergence the limited value equals the
actual one, so a model written with it and the same model written without it are
**the same device**, and every distortion product must agree. That is an exact
expectation with no appeal to another simulator. Both spellings are generated
from one body string, which is what guarantees they differ only by `$limit`.

The shapes cover the chain combinatorics, which is where this can go wrong — a
model limiting a single branch never puts more than one entry on either side of
a pair. All 13 live comparisons agree, the worst at `7.1e-10`, which is
convergence noise: the two spellings settle `8.3e-11` apart because limiting
changes the Newton path, and `d²/dv²` of `exp(v/vt)` amplifies that by `1/vt²`.

The rest of the E-352 suite is unchanged by this: closed-form HD2/HD3 still
`0.0` and `1.2e-16`, two-tone against the built-in diode still `1.9e-06`, the
closed-form mixer still exact.

## Three ways this could have passed while being wrong

Each was caught and closed; they are recorded because each produces a confident
green.

1. **Both-zero comparisons.** "No distortion" is precisely the pre-fix
   behaviour, so scoring `0 == 0` as agreement would certify the bug. The suite
   scores a both-zero product as a **failure** except where the mathematics
   requires zero — a bilinear term `k·v₁·v₂` has no third derivative, so its IM3
   is correctly zero and is asserted as such.
2. **Comparing magnitudes.** A dropped sign on a negated chain entry flips the
   result and leaves `|·|` untouched, so the reversed-branch shape — the only
   one that tests the sign logic — would have scored its own target bug as a
   pass. Products are compared as **complex** values, and the shape is pinned
   against the forward one: they come out at `+1.2488e-01` and `−1.2488e-01`.
3. **Degenerate decks.** Three shapes initially read zero everywhere for reasons
   unrelated to `$limit`: the probed node was pinned by an ideal voltage source,
   so no injected distortion current could move it, and each nonlinearity saw
   only one tone and so had nothing to intermodulate. Fixed with series
   resistors and both tones on both drives.

A fourth trap was ruled out rather than fixed. Several shapes agree at exactly
`0.00e+00`, which would be the signature of OpenVAF having elided the `$limit`
altogether — identical code compared against itself. Dumping the chains
(`OPENVAF_DAE_DEBUG=1`) settles it: every plain build reports `len 1` on every
input and every `$limit` build reports 2 or 3.

```
DAEDBG chain in0 len 3 [(unknown3, false), (unknown4, false), (unknown0, false)]
DAEDBG chain in1 len 2 [(unknown5, false), (unknown1, false)]
```

## Files

| file | change |
|---|---|
| `openvaf/sim_back/src/dae/builder.rs` | `taylor_unknown_chain`; both tensor passes sum over chains with signs |
| `openvaf/osdi/src/load.rs` | cleared an `unused_mut` left by E-352 |
| `src/osdi/osdidisto.c` | the no-tensors warning no longer names `$limit` |
| `examples/limitdisto_examples/` | new, 7 checks |
| `examples/osdidisto_examples/` | check [6] now uses a ground-referenced probe |

`examples/limitdisto_examples/` is a proven trigger: on the pre-fix compiler
every one of its five shapes reports *no tensors* and contributes zero.
