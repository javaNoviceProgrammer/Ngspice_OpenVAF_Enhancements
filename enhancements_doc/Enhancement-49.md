# Enhancement-49 — $root + hierarchical names, transition() input

This document describes the changes made to **OpenVAF-r** in the `version11/`
directory for three related front-end defects: hierarchical references into
flattened instances, nested named-block paths, and `transition()`'s input
type (plus a builtin signature audit). No OSDI/ngspice change.

## 1. Hierarchical references into flattened instances (LRM 6.6)

The probe found `$root`-anchored paths and single-level block paths working,
but every reference into an instance failed — after the E-5 elaboration
flattens `rdiv u1(a, c);` into prefixed locals (`u1__m`, `u1__r`), parent-side
references were never rewritten:

```verilog
analog V(a,c) <+ 0.0*V(u1.m);   // error: 'u1' was not found in the current scope
x = u1.r;                        // same
```

**Fix** (`hir/elaborate.rs`): every rendering scope now carries an
**instance-chain map** — all chains reachable from that scope (`"u1"`,
`"u1.u2"`, `"u1[2]"`, …) mapped to their composed flattening prefixes, built
recursively from the item tree. A token-level scanner
(`find_instance_path_holes`, the same hole mechanism as the bus-port
substitution) rewrites `chain.member` occurrences to
`render_name(prefix + member)`:

- deep chains compose (`u1.u2.x` → `u1__u2__x`); instance-array elements work
  (`u1[2].m` → `u1_2__m`, disambiguated from bus selects by chain lookup);
- the top module's scope adds `<top>.…` alias entries and the scanner strips
  a leading `$root.`, so `$root.hier.u1.u2.m`, `hier.u1.u2.m` and `u1.u2.m`
  all resolve identically (per the LRM, `$root.<top>.x` ≡ `x` from `<top>`);
- bus selects after the member stay in place (`u1.b[2]` → `u1__b[2]`);
  escaped member names re-escape through E-46's `render_name`;
- a member followed by a further `.` (a named block *inside* the child) is
  left untouched — out of scope, cleanly diagnosed by name resolution.

## 2. Nested named-block paths

`outer.inner.w` failed with "'w' was not found in 'inner'" while single-level
`blk.v` worked. Root cause in `hir_def/nameres.rs::resolve_names_in`: the
traversal correctly redirects `current_map` into each nested block's def map,
but the **final name lookup used `self.scopes`** — probing the original map's
scope ids against the wrong arena. One-token fix
(`current_map.scopes[scope]`), plus the write-up of why only multi-segment
paths hit it (single-segment callers had already switched maps).

## 3. transition() input type (user-reported) + builtin audit

The LRM's canonical comparator failed to compile:

```
error: type mismatch: expected integer value ... but found real variable reference
  | V(cout) <+ transition(vcout, td, tr, tf);
```

The TRANSITION signature table typed the input `Val(Integer)` (and the
lowering `ifcast`-ed it), but per LRM 4.5.7 the filter's input is a **real**
expression — smoothing piecewise-constant real waveforms is its whole
purpose. All five signatures now take `Val(Real)` (integer inputs promote
implicitly; the manual cast is gone). The follow-up audit of **every** builtin
signature table (noise, ddt/idt/idtmod, laplace/zi, absdelay/slew,
last_crossing, file I/O, simparam/simprobe, random/arandom, rdist/dist,
plusargs, discontinuity, bound_step, ddx, table_model, display, and the event
kinds) found exactly one more defect: `DIST_2_ARG_CONST_SEED` typed its middle
argument `Val(Real)` while its three siblings say `Val(Integer)` — fixed.

## What now works (`hiername_examples/`, all exact)

| case | result |
|---|---|
| `u1.u2.r` (deep hierarchical parameter) | reads the child's default exactly |
| `V(u1.u2.m)` / `V($root.hier.u1.u2.m)` / `V(hier.u1.u2.m)` | all three spellings identical (sum 557 exact) |
| `outer.inner.w`, `$root.blocks.outer.inner.w` | 3.75 exact (was an error) |
| `real vcout; transition(vcout, td, tr, tf)` | the LRM comparator compiles and switches |

`verify_hiername.py`: 4/4 PASS. Regression: all 45 example verify suites ALL
PASS; 57/57 crate tests.

## Notes

- Upward references (a child naming its parent's objects) and hierarchical
  references *out of* the compiled top module remain out of scope — they have
  no meaning for a self-contained OSDI model.
- Named blocks inside child instances (`u1.blk.v`) are not rewritten; they
  surface as ordinary resolution errors.
