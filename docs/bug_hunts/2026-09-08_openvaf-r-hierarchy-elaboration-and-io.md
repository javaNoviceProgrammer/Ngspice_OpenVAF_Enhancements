# openvaf-r hierarchy, elaboration diagnostics and file I/O — a one-hour hunt

**Date:** 2026-09-08, 20:05 to 20:55 local time (about 175 decks). **Rule of the hour:** probe, record,
move on; nothing was fixed. Every finding below has a deck that reproduces it in the
scratchpad (`hunt3/`), and every "expected" value was worked out by hand before the
run. Areas deliberately chosen because the three earlier openvaf-r hunts
(2026-09-04 compiler, 2026-09-07 semantics, 2026-09-07 events/noise/commands) had not
touched them: the preprocessor, integer literals and operators, the whole `laplace_*`
family, `$table_model`, custom natures, ngspice `sens`/`tf`/`pz` on an OSDI device,
hierarchy edge cases, file I/O, and the compiler's command line.

**Toolchain:** `openvaf-r` 23.6.0 built from `OpenVAF-master-20260610` at commit
1b7915f0 (E-588), ngspice-46 from the same tree, both solvers where it mattered.

## Summary

| # | Finding | Severity |
|---|---|---|
| F1 | Hierarchical elaboration merges every unnamed branch that lands on the same two nodes, across modules: an ideal-source leaf beside a resistor leaf gives 0.667 V or 1.0 V depending only on which instance is written first, a child's source is dropped when the parent adds a parallel conductance (1.333 V where 1.0 V is right), a parent's `I(p,n)` probe reads the child's current, and a probe-only parent branch no longer shorts. Named branches are safe. | wrong answer |
| F2 | Every diagnostic inside a module that instantiates a child or runs a genvar loop points into a file that does not exist (`he9.va__elaborated.va:144:18`, `gv2.va__generated.va:145:10`) with no excerpt, and mangled names (`l1__p`, `l2__r`) leak into messages; a user parameter named `l1__r` collides with the child's mangled name. | usability |
| F3 | An array parameter is invisible to every other parameter-level declaration: `aliasparam`, a scalar default `b = a[1]`, a range bound `from [0:a[1]]`, a `localparam` and another array's default all fail with "'a' was not found in the current scope", while the analog block sees it. | wrong refusal, misleading diagnostic |
| F4 | Every `$table_model` file failure (missing, empty, one column, NaN) carries the same explanatory note about non-finite values; only the NaN case earns it. | misleading diagnostic |
| F5 | The LRM's module parameter port list `module m #(parameter real r = 1k) (p, n);` is a parse error ("unexpected token '#'; expected ';'") with no hint; ANSI port declarations work. | missing feature, poor message |
| F6 | `$fclose` is deferred: a `$fwrite` after `$fclose` still lands in the file, and a second `$fopen` of the same path in the same run continues the stream instead of truncating (a 3000-iteration open/write/close loop leaves 3000 lines). Descriptors do not leak. | semantics |
| F7 | ngspice `show` and `showmod` truncate parameter names to 11 characters (`averyveryve`, `twelve_char`) while `print` with the full name works. | display (ngspice) |
| F8 | Smaller diagnostic slips: an empty help line for a non-ASCII identifier; `$param_given(arr)` refused for a whole array; an integer default of 3000000000 saturates silently in the source; lint ids such as `L022` are not accepted by `-A`/`-W`/`-E` and `--lints` does not print them. | diagnostics |

## What was read and run

`hir/src/elaborate.rs` (the source-to-source flattening that produces the
`__elaborated` and `__generated` texts), `basedb/src/diagnostics/sink.rs`,
`hir_lower/src/expr.rs` (the `idt` reset lowering, `$limit`), `osdi/src/metadata.rs`
(parameter kinds), `osdi/src/compilation_unit.rs` (the file-operation callbacks),
`basedb/src/lints.rs` (lint ids), ngspice `src/frontend/device.c` (`show`). About
ninety decks were compiled and run; the ones that matter are quoted below.

## F1 — a child's unnamed branch is merged into the parent's unnamed branch on the same nodes

The LRM's unnamed branch `(p, n)` is a per-module object: every `I(p,n)`/`V(p,n)`
inside one module names the same branch, but a child instance connected to the same
two nets owns its own branch. openvaf-r flattens hierarchy by rewriting the child's
text into the parent (`hir/src/elaborate.rs`), and the child's `(p, n)` becomes the
parent's `(p, n)`. Three consequences, each with a deck:

**(a) A child's potential source is dropped.** `hb3.va`:

```verilog
module leafd(p, n); inout p, n; electrical p, n;
analog V(p,n) <+ 1.0;
endmodule
module hb3(p, n); inout p, n; electrical p, n;
leafd l1(p, n);
analog I(p,n) <+ V(p,n)/2k;
endmodule
```

Deck: 2 V through 1 kΩ into the device. The child forces 1.0 V; the parent's 2 kΩ is
just a load the source absorbs. Expected `v(1) = 1.0`. Observed:

```
warning[L022]: branch (p,n) is contributed as both a potential and a flow source
    = ... when both are contributed with no condition between them the last contribution decides, and the other one is dropped
v(1) = 1.333333e+00
v1#branch = -6.66667e-04
```

The child's source is gone: 1.333 V is the 2 V divided by 1 kΩ and 2 kΩ. The warning
speaks of "both" contributions as if they were in one module, so the reader cannot tell
that a different module's source was discarded. The mirror image (`hb2.va`: parent
`V(p,n) <+ 1.0`, child `I(p,n) <+ V/500`) also fires L022 and drops the child's
conductance, invisible from outside only because the potential source hides it.

**(b) A parent's flow probe reads the child's current.** `hb.va`: parent
`I(p,n) <+ V(p,n)/1k` and `iop = I(p,n)`, child `I(p,n) <+ V(p,n)/500`, 1 V applied.
LRM: `iop` is the parent's own branch current, 1 mA. Observed `@n1[iop] = 3.0 mA`
(the child's 2 mA included). The same shows in `dp.va` (`defparam` test): the parent's
`iop` reported 2.4167 mA where its own contributions sum to 0.4167 mA.

**(c) A probe-only parent branch no longer shorts.** In a flat module a flow probe on
a branch nothing contributes to is a short (L017 fires, `v(1) = 0`, `fp.va`). With a
child contributing to the same nodes (`hb7.va`: parent `iop = I(p,n)` only, child
`I(p,n) <+ V/500`), no L017, `v(1) = 0.667` and `iop` = the child's 1.333 mA. The LRM
answer is the short.

**(d) Two sibling leaves: the answer depends on the order they are written.**
`hb11.va` is the most ordinary hierarchical shape there is, a parent that wires an
ideal-source leaf (`V(p,n) <+ 1.0`) and a resistor leaf (`I(p,n) <+ V(p,n)/500`) in
parallel and contributes nothing itself:

```
module hb11(p, n); ... srcleaf s1(p, n); resleaf r1(p, n); endmodule   -> v(1) = 0.667 V
module hb12(p, n); ... resleaf r1(p, n); srcleaf s1(p, n); endmodule   -> v(1) = 1.000 V
```

Same deck (2 V through 1 kΩ), same two leaves, L022 in both; the source survives only
when its instance comes last. The LRM answer is 1.0 V for both. With a capacitor leaf
(`I(p,n) <+ ddt(1n*V(p,n))`) instead of the resistor (`sib.va`), source-then-capacitor
gives 2.0 V at the operating point (the source is gone and the capacitor is open) and
a 1 MHz ac magnitude of 0.157 where an ideal source pins it to 0; capacitor-then-source
gives 1.0 V and 0. Two flow leaves (resistor beside capacitor) are right in either
order (1.0 V, 0.15166 at 1 MHz), so the failure needs one potential source among the
siblings, the everyday case of a supply, a reference or a clamp modelled as its own
leaf.

**(e) It can be silent, and it sums sources.** `hb8.va` makes the parent's flow
contribution conditional (`if (V(p,n) > -100) I(p,n) <+ V(p,n)/2k;`) under the same
child source: L022 stays quiet (its rule exempts conditional paths) and `v(1)` is still
1.333 V. `hb10.va` puts `V(p,n) <+ 2.0` in the parent under a child `V(p,n) <+ 1.0`:
3.0 V, the two ideal sources added as if they were one module's two contributions,
where the LRM has two sources in parallel and no answer. Merging on the parent's
*internal* node (`hb9.va`, child on `(p, m)`) behaves the same way.

**Where it lives:** the flattening is the source-to-source rewrite in
`hir/src/elaborate.rs` (E-264 made it linear in the instance count, E-392 added the
instantiation checks); the child's `(p, n)` is spelled with the parent's net names
after the rewrite and nothing records which module it came from, so the later
branch-identity pass (`hir_lower`, the L022 check) sees one branch. Named branches
keep their mangled names (`l1__src`) and therefore keep their identity, which is why
they are safe.

**What is safe:** a named branch in either module (`hb5.va` child `branch (p,n) src;
V(src) <+ 1.0`, `hb6.va` parent `branch (p,n) own; I(own) <+ ...`) gives exactly 1.0 V,
and a *conditional* switch branch in the child under a parent leakage (`swh.va`)
behaves like the flat control (0 V closed, 2.0 V open), because L022's
"unconditional" rule does not apply. So the damage is confined to unconditional
potential-vs-flow across the module boundary and to probe values. Idiomatic leaf
modules (an ideal source, a switch, a capacitor) under a parent that adds its own
conductance or reads `I(p,n)` are exactly the affected shape.

## F2 — diagnostics in an elaborated or genvar-expanded module point into a file that does not exist

`he9.va`: a parent with one child instance and one typo:

```verilog
module he9(p,n); inout p,n; electrical p,n; real x; leafx l1(p,n);
analog begin x = undeclared_thing; I(p,n) <+ V(p,n)/1k; end endmodule
```

```
error: 'undeclared_thing' was not found in the current scope
    --> /he9.va__elaborated.va:144:18
error: could not compile `he9.va__elaborated.va` due to 1 previous errors
```

The user's file is two lines long; line 144 of a path that starts at `/` and does not
exist is reported, without the source excerpt every other diagnostic shows. The same
for a genvar loop with no hierarchy at all (`gv2.va`: `--> /gv2.va__generated.va:145:10`
for an undeclared name and for `ln(-2.0)`), for a type error in an override
(`he10.va`, `.r("abc")`), and for a lint. Mangled names leak: probing a child's net
`V(l1.p)` from the parent says `'l1__p' was not found`; two instances named `l2` say
`'l2__r' was already declared`; and a parent that legitimately declares
`parameter real l1__r` next to an instance `l1` of a module with parameter `r`
(`he13.va`) fails with the same message, so the mangling scheme is part of the user's
namespace. The rewritten text is what `hir/src/elaborate.rs` hands to the parser under the
synthetic names, and `basedb/src/diagnostics/sink.rs` prints whatever file id a span
carries, so nothing maps a generated span back to the user's file.
A syntax error inside such a module (`gs.va`, an `x = ;`) is reported at
`/gs.va__generated.va:135:192`, so the rewrite runs before the parser and even the
first pass loses the user's line; a lint (`gw.va`, L021) is reported the same way
and the closing line says the generated file "generated 1 warning".
Every pre-elaboration check (port counts, unknown override, unknown module,
self-instantiation, positional override count) is reported cleanly at the true
location, so the gap is only in the diagnostics that run on the rewritten text.

## F3 — array parameters are invisible to other parameter declarations

```verilog
parameter real arr[0:2] = '{1, 2, 3};
aliasparam arr_alias = arr;     // error: 'arr' was not found in the current scope
```

The parameter exists and is used in the same module (`ali.va`). The same "not found"
answers `parameter real b = a[1];` (`pd5.va`), a range bound `from [0:a[1]]`, a
`localparam real l = a[0]*2;` and a second array's default `'{a[0], a[1]}` (`pd21`
to `pd23`), while `analog initial z = a[1];` and the analog block read it, so array
parameters are missing from the scope every parameter-level constant is resolved in,
not only from `aliasparam`. Whether an alias
of an array is meant to be supported or not, "not found" is the wrong message, and a
scalar default computed from an array element is ordinary Verilog-A.

## F4 — every `$table_model` file failure gets the non-finite-values note

`tb.va` with `localparam string f = "<file>"` and `$table_model(V(p,n), f, "1L")`:

| file | content | message |
|---|---|---|
| `nofile.tbl` | does not exist | `cannot use 'nofile.tbl' as $table_model data` + "a value that is not finite -- 'nan', 'inf', or an overflowing exponent such as 1e400 -- makes the whole file unusable" |
| `tempty.tbl` | empty | same note |
| `tone.tbl` | one column | same note |
| `tnan.tbl` | a `nan` | same note (correct here) |

A file that exists only in an `-I` directory (`-I inc` with `inc/sub.tbl`) gets the
same message and note, so include directories are not searched for table data (the
source file's own directory is, even when the compiler runs elsewhere).
The duplicate-abscissa case has its own precise warning ("repeats the abscissa 0; the
duplicated knot makes a zero-width segment"), and CRLF, `#` comments, tabs, blank
lines and unsorted rows are all read correctly, so only the note's attachment is wrong.

## F5 — the module parameter port list is a parse error with no hint

LRM A.1.3 (`module_declaration ::= ... module_identifier [ module_parameter_port_list ]
[ list_of_ports ] ;`). `module ansi #(parameter real r = 2k) (inout electrical a, inout
electrical b);` gives `unexpected token '#'; expected ';'` at the `#`. The ANSI port
declaration form on its own (`ansi2.va`) compiles and runs (4 kΩ → 0.25 mA), so the
`#(...)` list is the only missing piece of the 2001-style header, and the message does
not say what it saw.

## F6 — `$fclose` is deferred inside a run

`fio2.va`: `fa = $fopen("a.txt"); $fwrite(fa, "A1"); $fclose(fa); fb = $fopen("b.txt");
$fwrite(fa, "written to closed fa")` — `a.txt` ends with `written to closed fa`.
`fio3.va` opens, writes one line and closes the same file 3000 times in a loop:
the file holds 3000 lines, so a second `$fopen` of an already-opened path continues the
stream instead of truncating; across two ngspice runs the same file is truncated (2
lines stay 2), and the two-argument `$fopen(name, "w")` truncates per run too. No
descriptor is leaked (3000 opens under `ulimit -n 256` all succeed, none returns 0).
The C and Verilog semantics are that `$fclose` closes and a later `$fopen` truncates;
a model that opens at `initial_step` and closes at `final_step` gets the output of
every analysis in one run concatenated. E-11 introduced these callbacks and its
write-up does not mention append behaviour, so this is undocumented rather than chosen.

## F7 — `show` and `showmod` truncate parameter names to 11 characters (ngspice)

```
 parameter real averyveryverylongparametername = 7; parameter real twelve_chars = 12;
showmod lm  ->   averyveryve                     7
                 twelve_char                    12
show n1     ->   averyveryve                     9      (an instance parameter)
```

`print @lm[averyveryverylongparametername]` prints 7, so only the listing is cut:
`src/frontend/device.c` line 867 prints the name with `"%*.*s", LEFT_WIDTH, LEFT_WIDTH`,
and the precision clips it. `sens` output names the same parameters in full
(`n1:l1__r`). The
30-level hierarchy chain's parameters (`a__a__a__...__r`) all display as
`a__a__a__a_`, indistinguishable from one another.

**Status (2026-09-09):** resolved by Enhancement-589. The widths are decided per
table from the names it prints and nothing is truncated; `showwidth_examples`
19 of 19 per solver, sweep 484 of 484.

## F8 — smaller diagnostic slips

- **Non-ASCII identifier** (`real réal;`): `error: encountered unexpected token!` and
  `help: It looks like you used characters that look similar to ascii: ` with nothing
  after the colon. Non-ASCII text in comments and strings is fine.
- **`$param_given(arr)`** on an array parameter: "'arr' requires a bit-select [i]".
  LRM 9.19 takes a parameter identifier; the element form `$param_given(arr[0])` works
  and answers for the whole array.
- **Integer parameter defaults in the source** are silently clipped: `parameter integer
  big = 3000000000` becomes 2147483647 and `parameter integer half = 2.5` becomes 3 with
  no warning, while the same values on a model card are refused (saturation explained)
  or warned (rounded).
- **Lint ids:** diagnostics print `warning[L022]`, but `-A L022` is "invalid value" and
  `--lints` lists names only (`discarded_contribution` is L022, `trivial_probe` L017),
  so the CLI offers no way to go from the printed id to the flag.
- **A branch probe inside an analog function** (`f = x + V(p,n);`) is refused with
  "'V' was not found in the current scope". The refusal is LRM 4.7 (no access
  functions in analog functions); the message says a nature access does not exist.
- **`$table_model` with `localparam string f = {"t1", ".tbl"}`** is refused as "must be a
  compile-time constant string": a concatenation of two literals is one, and the same
  name from a `` `define `` is accepted, so it is the folder that stops at `{}`.
- **`$table_model` control strings:** `"1S"`, `"S"` and `"1Q"` are "unsupported"
  without a list of what is supported, and a two-dimension string `"3L,1L"` on a
  one-dimensional table compiles without comment.
- **An instance without a connection list** (`leafx l1;`, legal Verilog for a module
  whose ports are all left open) is read as a net declaration: "expected discipline but
  found module 'leafx'". The other malformed forms (a port named twice, mixed named and
  positional, zero connections) each get a precise message.
- **A net or a parameter and an instance with one name** (`electrical l1; leafx
  l1(p,n);`, `parameter real l1 = 1; leafx l1(p,n);`) compile without a word;
  identifiers in one scope are unique in the LRM.
- **Unquoted string on a model card** (`s=b`, ngspice): "Undefined parameter [b] /
  Cannot compute substitute" with no hint that a string parameter needs quotes.
- **A conditional `idt` reset** decays toward `ic` with a 10 µs time constant instead
  of jumping; this is E-52's documented deviation (comment in `lower_integral`), noted
  here only because a reader of LRM 4.5.4 will be surprised by 0.62 V one microsecond
  into a reset to 0.25 V.

**Status (2026-09-09):** resolved by Enhancement-590 -- `$param_given(arr)` answers
for the array, lint L030 for lossy integer constants, lint ids accepted by `-A`/`-W`/`-E`
and printed by `--lints`, the function-scope message names the item and quotes LRM
4.7.1, the concatenated table name folds in both folders, an extra control-string axis
is warned, `leafx l1;` gets the port-list note, instance-name collisions are refused,
and ngspice adds the quoting hint. The non-ASCII help line and the control-code list
were withdrawn: both were complete, the hunt's grep had dropped the following lines.
`hunt3diag_examples` 42 of 42 per solver, sweep 485 of 485.

## Smaller notes (not pursued)

- `{}` as an empty array is refused ("empty concatenation"); `'{}` and the LRM's null
  argument (E-453) work. Design.
- `$table_model` with an overridable `parameter string` file name is refused with a
  pointer to `localparam string`; array-sourced tables `$table_model(x, xs, ys, "1L")`
  work (2.5 at 1.5). Design.
- `$limit` requires the branch probe itself as the first argument (LRM); a variable
  holding the probe value is rejected by name.
- Forward references between parameters are refused "textually defined before them";
  matches upstream OpenVAF.
- Array parameters are model-only unless `(* type="instance" *)`, exactly like scalars;
  `alter` names the `altermod` form. An earlier suspicion that the instance line
  "cannot set array elements" was my misreading of a `show` listing.
- Reduction operators (`&i`, `|i`, `^i`) are not parsed; string methods (`s.len()`) are
  not Verilog-AMS.
- An unconnected child port `.n()` is accepted silently; the child's
  `$port_connected(n)` is 0 and its branch carries no current. `V(p,p)` and `I(p,p)`
  are refused by LRM table 4-16.
- `-8 >> 1` is the logical shift 2147483644 and `>>>` the arithmetic −4 (warned as an
  extension). `$clog2(-3)` is 0 where a 32-bit unsigned reading would give 32.
- `aliasparam c = b` where `b` is itself an alias, and `aliasparam c = lp` of a
  `localparam`, both compile without comment; `parameter integer big = 2**40` is
  clipped silently like the literal in F8; two `from` ranges on one parameter are
  accepted (LRM allows several).
- `.model` cards pass parameters named `level`, `tnom` and `version` through to the
  module untouched.
- A contribution to an `input` port (`input i; ... V(i) <+ 1.0;`) compiles without a
  word. The LRM's port-direction rules (3.6) read as if that should be refused; not
  checked against the standard's wording this hour.
- Two `white_noise` contributions with the **same** name in one module sum in power
  exactly like two with different names (1.4186e-9 V/√Hz in both decks, `nz.va`; a
  correlated pair would give 2.0021e-9). Whether the LRM's name argument groups
  same-name sources into one correlated source (4.6.4) is worth checking; nothing in
  the enhancement write-ups says which reading was chosen.
- With a seed the model never changes, every `$rdist_*`/`$dist_*` call site returns one
  constant for the whole run (20000 transient points: uniform "mean" 0.810 with zero
  variance, `$dist_uniform(seed,1,6)` always 1). That is E-10's documented read-only
  seed (the 2026-09-07 F2 was withdrawn for the same reason); a model that wants a
  sequence in time advances the seed itself, and then all nine distributions check out
  (see coverage).
- A child module compiled into a library is also exported as a stand-alone device, so
  two libraries whose helper modules share a name (`leafx` in `topa.osdi` and
  `topb.osdi`) print `Warning(osdi): device "leafx" is already registered; keeping the
  existing device and ignoring this one` even though neither netlist line names it.
  Harmless (each top carries its own flattened copy: 2.5 mA as expected), but helper
  names such as `resistor` will collide across every vendor's library.
- `zi_nd(V(p,n), '{1}, '{1}, 100u)` follows a 1 V/ms ramp continuously (0.23, 0.27,
  0.31 V at 0.23, 0.27, 0.31 ms) instead of holding samples every 100 µs (0.2, 0.2,
  0.3); the 2026-09-04 hunt's F8 recorded the same and it stands as a known
  limitation (no sample-and-hold in the simulator).
- `%m` inside a child prints the parent's instance name (`n1`), the same string the
  parent prints; the LRM's `%m` is the hierarchical instance name (`n1.l1`).
- Robustness that held: a 2000-deep nested `if`, a 3000-way `else if` chain, 500
  nested parentheses, a 20000-statement block (each about a second), 100 and 300
  child instances in one parent (0.15 s and 0.34 s), 64- and 200-port modules run
  by ngspice, case-colliding parameters `r`/`R` warned at load.

## Coverage, honestly

Verified correct this hour (each with a deck, values matched by hand):

- **Preprocessor:** nested function-like macros, a macro whose body is another macro
  call, multi-line bodies, `` `ifdef``/`` `elsif``/`` `else``, `` `undef``, `-D NAME=7`
  overriding an `` `ifndef`` default, a backtick inside a string left alone,
  `` `__LINE__`` and `` `__FILE__``, a self-including file and a self-expanding macro
  both diagnosed with a help line, a trailing backslash at end of file, a 100 kB comment
  line, CRLF sources, a UTF-8 BOM.
- **Literals and integer operators:** `4'b1010`, `8'hFF`, `'d10`, `8'o17`, `1_000`,
  `1_000.5e-1_0`, concatenation and replication, `^~`, all ten scale factors K M G T m u
  n p f a; `1.` and `.5` refused (the first with a clear message).
- **Math edge cases at run time:** `ln(0) = -inf`, `ln(-1)`, `sqrt(-1)`, `pow(-8, 1/3)`,
  `acosh(0.5)`, `asin(2)` all NaN, `atan2(0,0) = 0`, `exp(1000) = inf`, `limexp(1000)`
  finite, `floor(-0.5) = -1`, `ceil(-0.5) = -0`, `$clog2` of 0/1/1024/1025; the same
  expressions written as constants are refused at compile time with the domain named.
- **`laplace_nd`/`zp`/`np` forms:** first- and second-order low-passes (−3.01 dB and
  −45° at the corner, −40 dB/decade), a zero at the origin (`s/(1+s/w0)`: 55.9 dB and
  84° at 100 Hz, 75.96 dB asymptote), `np` with a pole (0.995, 0.707, 0.0995 across
  three decades), all at dc as well.
- **`$table_model`:** 1D linear with linear and constant extrapolation (11.5 vs 9 at
  3.5), a natural cubic spline reproduced by hand (0.35 at 0.5, 2.2 at 1.5, 11.7
  extrapolated), a 2D table at y = 0.5 (`2x + y`), the `E` extrapolation mode raising a
  `$fatal` that names the point and the LRM clause, CRLF/comment/tab/blank/unsorted
  files, a duplicated knot warned.
- **ngspice analyses on an OSDI device:** `tf` (gain 0.6667, output impedance 666.7 Ω,
  input impedance 3 kΩ), dc `sens` of the output to `r`, `g2`, `_mfactor` and the series
  resistor's `m` (each matched analytically), ac `sens` to `c` at four frequencies, `pz`
  (one pole at −1.5e6 = −1/(666.7 Ω · 1 nF)).
- **Natures and disciplines:** a thermal discipline with its own potential and flow
  natures, `idt_nature`/`ddt_nature` cross-links, a potential-only discipline, a nature
  derived from `Voltage` with its own `abstol`, a thermal port solved to 0.4 K.
- **Parameters:** `[5:1]` empty range refused at compile time, real bounds and a real
  `exclude` on integers, `from [0:inf)` on integers, `exclude {1, 2} exclude (3:4]`
  with the netlist refusing 1, 3.5 and 4 and accepting 3 (the excluded interval is
  open on the left), string sets refusing `"b"` and accepting `"q"` and `"a b"`, a
  3000000000 card value refused with the saturation explained, 0.6 and 0.4 rounded with
  a warning, `localparam` from parameters, `defparam l1.r = 500` honoured.
- **Analog functions:** a module parameter read inside a function, implicit real to
  integer in an integer function, argument and local names shadowing module variables,
  a function calling one defined later, `$strobe` inside a function; recursion, a
  literal passed to an `output`, wrong argument counts and a function with no
  arguments each refused with the LRM clause.
- **Branches:** two named branches between the same nodes in parallel (500 Ω), a branch
  to ground, `I(<p>)`, potential and flow contributed to one named branch warned (L022).
- **Strings:** concatenation, `==`/`!=`/`<`/`>` (ASCII order), `$sscanf` into an integer
  and a real, `$sformat`, a 20480-character `$strobe` line intact, `%m` printing the
  instance name, escapes `\t \\ \" \101 \n`.
- **File I/O:** `$fopen` of an unwritable path returning 0 and writes to it dropped,
  `$fopen(name, "r")` returning a descriptor with bit 31 set, `$fscanf`, `$fgets`
  (the rest of the first line, then the next), `$feof`, `$fwrite(1, ...)` to stdout,
  `$write` without a newline, `$display`.
- **Dynamics:** `idtmod` wrapping at the modulus (0.5 at 0.6 ms, 0.1 at 1.2 ms),
  `transition` retargeted mid-ramp (falls from 0.9 over 0.89 ms), `absdelay` whose
  delay argument changes at run time (0.5 ms then 0.2 ms), one-rate `slew` (fall rate
  = −rise), `transition` with zero rise time, `ddt(ddt(V))` = exactly ω² at 180°,
  `idt(ddt(V))` = exactly 1 at 0°, `idt` with `ic` held at `ic` in dc and at t = 0,
  `idtmod` and `absdelay`/`transition`/`slew` passing their input through in a dc
  sweep, `last_crossing` (−1 before any crossing, then the last rising-crossing time),
  `ac_stim("ac", 2.0, 0.5)` giving magnitude 2 and phase 0.5 rad, `ddt` of an integer
  = 0, `ddx` with respect to an unrelated node, `$bound_step(0)` and negative refused
  at compile time, conditional `white_noise` contributing when enabled (8.5255e-10
  V/√Hz including the 1 Ω series resistor's own noise).
- **`analysis()` flags:** `static`/`dc` in op and dc, `static` and `ac` in ac, `ic` and
  `static` at the transient's first point and neither later, `$abstime` 0 in ac and dc,
  `smsig` warned as never matching (L021).
- **Hierarchy:** unknown override name, too few/too many/named-nonexistent/unconnected
  port connections, undefined module, positional override overflow, a module
  instantiating itself ("no way to flatten it into a finite circuit"), a 30-level chain
  compiling in 1.7 s and solving to 1/310 Ω, child parameters on the card and via
  `altermod` (`l1__r`), `[0:0]` bus ports (`i_a[0]`), a zero-port module refused by
  ngspice with "could not find a valid modelname".
- **Command line:** `--dry-run` writing nothing, `-o` into a missing directory, two
  files and a directory argument each refused with a usage line, `-A`/`-E` by lint name,
  `-A all`, batch mode keying its cache on the content of an included file (two cache
  entries after editing `k.vah`), `--batch` refusing `--output`.
- **Random distributions** with a seed advanced per evaluation, 40018 draws each:
  normal 0.008/1.006, uniform 0.500/0.0835, exponential(2) 2.002, poisson(3) 3.009,
  chi-square(4) 3.987, t(5) 0.003, erlang(2, 3) 2.995, `$dist_uniform(1,6)` 3.493,
  `$dist_normal(0,10)` 0.010 with standard deviation 10.007.
- **Genvar loops:** a `localparam` as the loop bound and as the node-array width
  (five-segment ladder, 2 mA), nested genvars indexing `nd[i*3+j]`, a decreasing loop,
  the same genvar reused in a second loop, `$strobe` inside the loop printing once per
  iteration, a genvar used outside its loop refused with the reason.
- **More hierarchy:** a string override `#(.mode("sq"))` into a child with a `from {…}`
  set and `$param_given` 1 for it, 0 for the untouched sibling, and the card form
  `l2__mode="sq"` (12 mA total as computed), an override expression `#(.r(rp*2))`
  following `altermod hm rp=250`, an `(* type="instance" *)` child parameter set on
  the instance line (`l1__r=250`) and by `alter`, `sens` naming `n1:l1__r`,
  `laplace_zd` (−3.01 dB, −45°), `$abstime` = 0 in `analog initial`, a child's
  `aliasparam res = r` reachable from the card as `l1__res=500` (6 mA), and an `-O 0`
  build of the F1 deck giving the same 1.333 V.
- **Derivatives through `$table_model`:** `ddt` of a 1D table as a capacitance in ac
  (3.0 F on the linear segment, 2.4 F on the spline at 1.25, both by hand), `ddx` of
  the spline (2.4), `ddx` of a 2D table with respect to each variable (2 and 1), and
  `ddt(absdelay(V, 1u))` at 1 kHz (6283.185 at 89.64°).
- **Coefficients from parameters:** `laplace_nd` denominators `'{1, 1/w0}` follow
  `altermod lm w0=...` between two ac runs (−3.01 dB, then −0.043 dB at 1 kHz), an
  array-parameter element as a genvar bound refused as non-constant (as for scalars).
- **Bus connections into a child:** a slice `.a(bus[1:2])` and a concatenation
  `.a({p, q})` both wire a two-bit child port (1 mA and 0.5 mA through its two legs),
  and an array parameter override `#(.w('{500, 500}))` reaches the child (4 mA).
- **Analog functions under elaboration:** two leaves that each define `f` with
  different bodies, and a parent and child that both define `f`, each keep their own
  (6 mA = 2 + 4 in both decks).
- **Child scope through the card:** a child's `localparam` shows in `showmod` as
  `l1__r2` and a card value for it is warned and ignored, `$limit` with `pnjlim` inside
  a child diode converges from 5 V through 1 kΩ (0.693 V), `$bound_step(1u)` inside a
  child bounds the parent's transient (1005 points over 1 ms).
- **Odd but legal hierarchy:** a child wired to the same parent port twice (`l1(p, p)`)
  compiles and contributes nothing, a child's `from (0:inf)` range violated through
  the card is refused naming `l1__r`, parameters, variables and nets declared after
  the analog block resolve, `ddt` in `analog initial` refused with the reason, a noise
  source inside `ddt` accepted without comment.
- **Control flow:** `repeat` with a negative count doing nothing, a real loop variable
  in `for`, genvar loops over a node array in contributions and in a probe sum
  (`vsum = 2.0`, `V(nd[2]) = 0.4` on a five-segment ladder), a run-time index into a
  node array refused as non-constant.
