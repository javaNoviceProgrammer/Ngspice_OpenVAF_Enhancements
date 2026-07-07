# Enhancement-91 — multi-name name-then-range declarations and parameter-dependent widths (version11)

Enhancement-91 adds two related pieces of net/port/array declaration
coverage, both handled by textual pre-passes in `hir/src/elaborate.rs`
(the E-85/88/89/90 pattern), so the existing bus (E-3) and array (E-14/15)
machinery is reused unchanged.

## Part 1 — multi-name name-then-range declarations

Enhancement-89 added the *name-then-range* form of a vectored net/port
(`input in[0:2];`) but only for a **single** name with a 1-D range.
Enhancement-91 completes it for a **comma-separated list**, with a per-name
range:

```verilog
input a[0:1], b[0:3], c;       // two buses of different widths + a scalar
electrical a[0:1], b[0:3], c;
```

The normaliser (`normalize_name_range_decls`) now parses the whole name
list and emits one *range-then-name* declaration per name, sharing the head
(`input [0:1] a; input [0:3] b; input c;`) — a form the parser already
accepts. The single-name path is unchanged, and the instance-array
disambiguation is the same as E-89 (an instance has a `(port list)` after
the range; a declaration ends in `,` or `;`).

A **multi-dimensional** name (`in[0:2][0:1]`) is still left untouched:
multi-dimensional vectored ports are unsupported in *both* declaration
orders (the range-then-name form does not parse either), so the existing
diagnostic fires rather than a silent miscompile.

Runtime-verified: two input buses of different widths plus a scalar, each
bit read exactly (`a[1]=2 V`, `b[2]=5 V`, `c=9 V`).

## Part 2 — parameter-dependent declaration widths

A net/port/array range whose bounds reference a parameter now folds to a
literal range using that parameter's **elaboration-time value**:

```verilog
parameter integer N = 4;
electrical [0:N-1] out;        // -> electrical [0:3] out;
real w[0:N-1];                 // -> real w[0:3];
```

The pre-pass (`fold_parameter_widths`) collects each module's
constant-integer parameter defaults (resolving one default through another
by a fixpoint, and skipping `from`/`exclude` constraints) and rewrites every
declaration range `[msb:lsb]` that references a parameter. Only declaration
ranges (which contain a `:`) are touched; bit-selects (`x[i]`) and
already-literal ranges are left alone. The shared constant-integer
evaluator gained an optional parameter map — with an empty map it is exactly
the Enhancement-88 literal-only evaluator, so legacy-generate bounds are
unaffected.

**Scope (a structural parameter).** The width is fixed at the parameter's
default. A model card or instance that overrides the parameter does **not**
resize the bus or array — OSDI has a single fixed node count per module, so
a width parameter is structural (the same decision as generate bounds,
Enhancement-67/88). To get a different width, change the default and
recompile.

Runtime-verified:

- a parameter-sized array with a runtime loop over the parameter (E-70):
  `real w[0:N-1]` with the harmonic sum `∑ vref/(k+1)` — `2.08333` at `N=4`
  and `2.71786` at `N=8`, so the array width tracks the default;
- a parameter-width node bus `electrical [0:bits-1] out` — four terminals
  at `bits=4`, six at `bits=6`.

## What this does *not* cover (documented limitations)

- **Analog-block genvar for-loops** — the LRM ADC pattern (p091/117/134)
  puts `for (i=0;i<bits;...) V(out[i]) <+ ...` *inside* the analog block,
  indexing a bus by a genvar. Unrolling an analog-block genvar loop is a
  separate feature; those examples now fold their widths but still fail on
  the loop.
- **Parameter-valued bus bit-selects outside declarations** (`n[N]`,
  p169) — folding a parameter into an arbitrary bit-select is unsafe for
  variable-array indexing, so only declaration ranges are folded.
- `$table_model` with runtime array data (LRM p274) is deferred to a later
  enhancement — it is a scattered-data, runtime-variable table that the
  compile-time regular-grid machinery (E-16/17/40) cannot express.

## Verification

- `paramwidth_examples` 11/11 (param-sized array, param-width bus at two
  widths, multi-name buses, multi-dim rejection) with ngspice runtime pins.
- Full regression: 82 verify suites + 28 integration tests; `hir` snapshot
  tests green; the E-3/E-14/E-67/E-89 suites unaffected.
- LRM suite 7/7: the five parameter-width examples (p091/117/134/169) stay
  documented limitations but are re-pinned to their post-width-fold blocker
  (analog-block genvar loop / parameter bus bit-select).
