# Enhancement-652: an exported name ngspice cannot reach is reported at compile time (2026-09-16 hunt F8)

**Scope:** F8 of the
[2026-09-16 hunt](../docs/bug_hunts/2026-09-16_openvaf-r-functions-conversions-and-events.md).
Compiler: `openvaf/sim_back/src/module_info.rs` (`check_exported_names`,
`is_paramset_twin_name`, the alias items and the `$`-named variables kept
through the declaration walk), `openvaf/sim_back/src/diagnostics.rs`
(`ExportedNameCollision`, `DollarInExportedName`), `openvaf/hir/src/lib.rs`
(`Variable::text_range`/`lint_src`, `AliasParameter::text_range`/`lint_src`),
`openvaf/basedb/src/lints.rs` (`exported_name_collision` L035,
`dollar_in_exported_name` L036). New suite
[`exportname_examples`](../examples/exportname_examples/) (19 checks per
solver). **Compiler side.**

**Suites:** `exportname` 19 of 19 per solver, both solvers (9 of 19 on the
E-644 compiler); `opvar`, `osdiparam`, `limguard`, `paramsetinst` and every
other suite pinning the simulator's own name warnings green; workspace `cargo
test` green; full sweep 525 of 525.

## What was wrong

Verilog-A is case-sensitive; ngspice folds every name to lower case. Per
device it keeps two flat tables: the instance's parameters, their aliases and
the operating-point variables (every module-scope variable carrying `desc` or
`units`), plus the simulator's own `m`, `temp`, `dtemp` and `dt` and the
terminal currents E-394 synthesizes (`i_<port>`, and `i` on a two-terminal
device); and the model's parameters and aliases. Two entries that fold to one
name are one name to `@inst[name]`, `show` and `alter`, and the first in the
table wins: a parameter over a variable, an earlier declaration over a later
one, ngspice's own `m` over a variable, a variable over a synthesized current.
The other is unreachable, and `show` prints two rows of the name.

```verilog
(* type="instance" *) parameter real w = 2;
(* desc="width" *) real W;        // @na1[W] is 2: the parameter; W is unreachable
(* desc="gain" *) real g, G;      // @na1[G] is g; G is unreachable
(* desc="mult" *) real m;         // @na1[m] is the multiplier, 1
(* desc="ip" *) real i_p;         // @na1[i_p] is this variable, not the terminal current
parameter real a$b = 1;           // a$b=5 on the card applies; print @na1[a$b] is "b: no such variable"
```

Every one compiled without a word. ngspice warns about the case pairs at
load time (E-335/E-396: "declared more than once differing only in case",
"has the same name as the simulator's own instance parameter"), but the author
compiling the model never sees that, and L029 (`reserved_parameter_name`)
covered parameters only. The `$` case warned nowhere: `a$b` is a legal
identifier (LRM 2.7.1) and ngspice sets it on a card, but `print @na1[a$b]`
hands the bracket text to the expression parser, which reads `$b` as a shell
variable, so the name is write-only; a variable with a `$` is not exported at
all, its shape being reserved for the `name$paramset` twins of LRM 6.4.3.

## What changed

`check_exported_names` runs once the module's parameters are collected and
promoted (promotion decides which table a parameter lands in). It builds the
two tables the way ngspice will -- instance parameters with their aliases,
then operating-point variables, in declaration order; model parameters with
their aliases -- and reports, under the new lint `exported_name_collision`
(L035, warn, anchored on the losing declaration so `openvaf_allow` on it
silences it):

- two declared names that fold to one, naming both, the kind and name that
  comes first in the simulator's table and wins, and the level the lookup
  happens at (`@<inst>[..]`/`show`/`alter` or `@<model>[..]`/`showmod`/
  `altermod`); a parameter and its own aliases are one entry (ngspice routes
  them to one id) and never collide with each other;
- an operating-point variable named `m`, `temp`, `dtemp` or `dt`, which
  ngspice's own instance parameter wins (a parameter of that name is L029's,
  and `dtemp`/`temp`/`m` on a parameter are routed on purpose, E-396);
- an instance-table entry named like a synthesized terminal current, which
  shadows it, except a parameter named `i`, which ngspice routes (E-644).

A model parameter and an operating-point variable differing by case live in
different tables and are both reachable (`@na1[G]` the variable, `@m[g]` the
parameter), so that pair is not reported; the hunt's first row was this
shape, and it is a naming oddity, not a loss.

`dollar_in_exported_name` (L036, warn) reports a `$` in a parameter's or
alias's name as write-only from ngspice, and in a variable's name as not
exported; the `name$paramset` twins elaboration synthesizes are recognized by
their suffix and left alone.

## Verification

| check | result |
|---|---|
| instance parameter `w` beside variable `W` | L035 names both, "instance parameter 'w' comes first … and wins"; ngspice's `@na1[W]` is 2 |
| variables `g` and `G` | L035, the earlier wins; `@na1[G]` is `g`'s value |
| instance alias `res` beside `Res`; two model parameters `g`/`G`; two aliases `x`/`X` | L035, the alias / the model-level spelling / the alias pair |
| variables `m`, `temp`, `dt` | three L035, "ngspice's own instance parameter … wins the lookup" |
| variables `i_p` and `i` on a two-terminal device | two L035, "shadows … the terminal current ngspice synthesizes" |
| a three-terminal device's `i`, a model parameter `i_p`, an instance parameter `i` | no word |
| `a$b` as a model parameter, `c$d` as an instance parameter, alias `x$y`, variable `a$b` | L036: write-only / write-only / write-only / not exported |
| the `x$ps` twin of a paramset's redeclared variable | no word |
| model parameter `g` beside variable `G` (`@na1[G]` = 3, `@m[g]` = 2), a parameter and its own alias, `dtemp` (L029), an unexported variable, `openvaf_allow` | no L035 |
| workspace `cargo test` | green |
| `exportname_examples` | 19 / 19 per solver, both solvers; 9 / 19 on the E-644 compiler |
| full sweep | 525 of 525 |

## What this does not do

Nothing changes on the ngspice side: its load-time warnings stay as they are
(their "instance parameter" wording for a pair of variables is a slip left for
another day), and the winner of a collision is still whatever its table order
makes it. The `$` name is not made readable: that would need ngspice's
`@dev[param]` reader to stop handing the text to the expression parser. A
variable exported through `all_vars_opvars` (a library build mode) is judged
exactly like a described one.
