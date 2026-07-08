# Enhancement-92 — freezing structural (width) parameters

Enhancement-92 closes a safety gap in Enhancement-91's parameter-dependent
declaration widths: a parameter that shapes a width is now frozen to a
`localparam`, so a netlist override can no longer desync the frozen
structure from behavioural code.

## The problem

Enhancement-91 folds a parameter-dependent width to a literal at
elaboration, using the parameter's default. But it left the `parameter`
declaration overridable. When the *same* parameter also drives behavioural
code, an override desynced the two:

```verilog
module wsum(out);
   parameter integer N = 4;
   output out; electrical out;
   real w[0:N-1];              // sized [0:3] at the default (E-91)
   integer k;
   analog begin : b
      real acc; acc = 0.0;
      for (k = 0; k < N; k = k + 1) begin   // loop bound follows the override
         w[k] = 1.0/(k+1); acc = acc + w[k];
      end
      V(out) <+ acc;
   end
endmodule
```

With `.model ws wsum N=8`, the array `w` stayed sized at 4 (frozen from the
default) while the runtime loop ran to 8 — a **silent out-of-bounds** write
to `w[4..7]`, giving a garbage result (`~6.08` instead of the correct
`2.0833`). ngspice accepted the override because `N` was still a settable
OSDI parameter, even though structurally it could not take effect (the OSDI
descriptor has one fixed node/array count per module).

## The fix

The width-fold pre-pass (`fold_parameter_widths`, `hir/src/elaborate.rs`)
now records every parameter that shaped a declaration width and rewrites its
declaration from `parameter` to `localparam`
(`freeze_width_parameters`):

- a **multi-parameter declaration is split** so only the structural names
  freeze — `parameter integer bits = 4; parameter real gain = 2.0;` with a
  `bits`-width bus becomes `localparam integer bits = 4; parameter real
  gain = 2.0;`, leaving `gain` overridable;
- a **range constraint** (`parameter integer width = 8 from [2:24];`) is
  dropped from the frozen name — a `localparam` cannot carry one — but
  preserved on parameters that stay overridable.

A `localparam` is a compile-time constant, so it is not exported as an OSDI
parameter: the value is fixed at the default everywhere (structure *and*
behaviour stay consistent), and a netlist attempt to set it is simply
ignored rather than corrupting the model. To use a different width, change
the default and recompile.

## Verification

`paramfreeze_examples` (4/4, ngspice runtime pins):

- `wsum` default (`N=4`) gives the correct harmonic sum `2.08333`;
- `.model ws wsum N=8` now **stays `2.08333`** — the override is ignored and
  the model keeps its default (before this fix it produced the corrupted
  `~6.08`);
- a non-width parameter (`gain`) stays overridable: `.model m mp gain=10`
  scales the outputs (`out[0]=1.0`, `out[3]=4.0`), confirming the
  multi-parameter declaration was split and only the structural name froze.

Full regression: 84 verify suites + 28 integration tests + `hir` snapshot
tests green. The Enhancement-91 `paramwidth_examples` suite still passes
11/11 with the freeze active.
