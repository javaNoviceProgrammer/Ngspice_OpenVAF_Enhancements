# openvaf-r bug hunt — analog functions, implicit conversions, events under conditions, natures and the preprocessor

**Date:** 2026-09-16, one hour (08:07–09:07), at head `a304a79e` (after
E-641…E-644 and the IHP audit). **Binaries:** the repo's
`OpenVAF-master-20260610/target/opt/openvaf-r` and `ngspice-46/build/src/ngspice`.
**Method:** ~530 small Verilog-A modules written for the hour, compiled and (where
they compile) run on ngspice through a throw-away harness in the scratchpad
(`hunt14/p1.py … p44.py`), each probe checked against the VAMS-2023 text
(`pdftotext -layout docs/VAMS-LRM-2023.pdf`). Nothing was fixed; this is the
list. Areas chosen to avoid the ground the earlier hunts already covered
(parameters, arrays, hierarchy, events/noise/commands, osdi integration, KLU):
user-defined analog functions, integer/real semantics, `case` and loops,
filters, natures and disciplines, preprocessor directives beyond
`` `define ``/`` `include ``, numeric literals, lexer and CLI edges, contribution
and branch forms, `analog initial`, noise, `$table_model`, `ddx`, `$simparam`,
`analysis()`, `$strobe` formats.

## Summary

| # | finding | kind |
|---|---|---|
| [F1](#f1--a-parameter-array-cannot-be-passed-to-an-analog-functions-array-argument) | a **parameter** array cannot be passed to an analog function's array argument — `sum3(c)` with `parameter real c[0:2]` is refused as "`c` requires a bit-select", while a variable array (LRM 4.7.1 Example 3) passes; a size mismatch gets the same wrong message | wrong refusal, misleading diagnostic — **fixed in [E-645](../../enhancements_doc/Enhancement-645.md)** (the paramset face included) |
| [F2](#f2--an-analog-functions-local-variables-are-static-across-calls-and-newton-iterations) | an analog function's **local variables are static** across calls and across Newton iterations, an initializer included — `integer n; n = n + 1;` counts every evaluation (1074 at one operating point), and a model whose function reads a local before writing it converges only through gmin stepping; the return variable and output arguments are zeroed per call as LRM 4.7.2 says, locals are not, and nothing warns | semantics hazard, lint gap — **fixed in [E-646](../../enhancements_doc/Enhancement-646.md)** (per-call initialization) |
| [F3](#f3--real-to-integer-implicit-conversion-is-refused-in-some-contexts-and-accepted-in-others) | real→integer **implicit conversion is refused in some contexts and accepted in others**: an integer function *input* given a real (literal or variable), a real `case` label under an integer selector, a real shift distance are type errors, while `k = 2.7`, `repeat (2.7)`, an integer return of a real, an integer array element, a real `case` selector with an integer label all convert silently | inconsistency, wrong refusal (LRM 4.7.3, 5.8.3) — **fixed in [E-647](../../enhancements_doc/Enhancement-647.md)** (the integer input formal and the `case` item; the shift distance and `%d` stay refused by design) |
| [F4](#f4--an-event-control-inside-a-non-constant-conditional-compiles-without-a-word) | an event control inside a **non-constant conditional** compiles without a word — LRM 5.8 forbids it unless the condition is constant — and its outcome depends on the solver's iteration state: `if (V(p,n) > 0) @(initial_step) k = k + 1;` leaves `k = 0` at an operating point where V = 1 | silent misuse — **fixed in [E-648](../../enhancements_doc/Enhancement-648.md)** (refused under a non-constant `if`/`case`; a runtime loop is not a conditional statement and stays allowed) |
| [F5](#f5--a-natures-abstol-must-be-a-literal) | a nature's `abstol = 1e-3*1e-3` is refused ("must be a real constant") where the grammar (A.1.6 with A.8.3, `nature_attribute_expression ::= constant_expression`) allows a constant expression | wrong refusal — **fixed in [E-649](../../enhancements_doc/Enhancement-649.md)** (every nature and discipline attribute value folds as a constant expression; the width-bound folder shares it) |
| [F6](#f6--diagnostic-slips) | diagnostic slips: a contribution across two disciplines blamed on "invalid destination … expected nature access such as V(foo)" instead of LRM 5.5.1; `` `endif `` without `` `ifdef ``, a `\` followed by spaces in a `` `define ``, and a NUL byte all say "encountered unexpected token!"; `` `line `` silently ignored; an unknown lint name in `openvaf_allow` silently accepted; `from {1, 2.5}` on an integer accepted silently; `.5` vs `5.`; `\777` in a string becomes U+01FF; `%m` in a child prints the top instance; a `-D G==2.0` error located in the virtual defines file | diagnostics |
| [F7](#f7--noise-power-that-is-nan-or-negative-at-run-time-contributes-nothing-in-silence) | a noise power that is NaN or negative at run time contributes nothing, in silence (a literal is refused at compile time); likewise `$rdist_normal` with a run-time negative sigma returns the mean and `$rdist_uniform` with start > end returns the start, where `$rdist_exponential`/`$rdist_poisson` with a bad run-time mean are a `$fatal` | silent misuse, inconsistency |
| [F8](#f8--an-operating-point-variable-whose-name-collides-case-insensitively-is-unreachable-on-the-ngspice-side) | an operating-point variable whose name collides **case-insensitively** with a parameter, an alias, another variable or ngspice's own `m`/`temp` is unreachable on the ngspice side, or shadows the parameter: `real G;` beside `parameter real g` makes `@na1[g]` return the variable; `real g, G;` makes both "no such parameter"; `aliasparam res = r; real Res;` loses `@na1[res]`; `real m;` is hidden behind the multiplier. E-644's case-twin warning covers parameter pairs only | lint gap (both sides) |

Still present from earlier hunts, seen again in passing: the 09-04 hunt's F10 (integer
`/` by a zero-valued parameter or run-time zero is 0 with no message, `%` by zero is a
`$fatal`; `INT_MIN / -1` wraps), F3 (an internal node that is only probed is
singular at run time with no compile-time word), and the 09-08 hunt's F4 (a table
file refused for a `;` comment or a comma separator still carries the note about
non-finite values).

## What was read and run

LRM sections read for the probes: 4.2 (operators, conversions), 4.5.6/4.5.11/4.5.15
(ddx, laplace forms, restrictions on analog operators), 4.7 (analog functions),
5.4.2.2 and 5.6.5 (source and switch branches), 5.5.1 (access rules), 5.8/5.8.3
(conditional and case statements), 9.21 (`$table_model`), A.1.6 (nature attributes).

What was measured and holds (no finding): integer semantics (`-7/2 = -3`, `-7%2 = -1`,
`7%-2 = 1`, `2**-1 = 0`, `0**0 = 1`, wrap on `+`, saturate on real→integer at run time,
NaN → 0, `>>` logical, `>>>` sign-fill, `2**3**2 = 64` left-assoc, `-2**2 = 4`), all
scale factors of LRM 2.6.2 (`P` is rightly not one), BOM / CRLF / CR-only files and
includes, a `` `define `` continuation across CRLF, escaped identifiers and keywords,
300-character names, the 1000-deep nesting limit (a clean error), `-D` forms, filename
with a space, the four `laplace_*` forms agreeing at −3 dB (the zp/np forms are the
LRM's unity-dc-gain form), `idtmod` saw-tooth, `absdelay`/`transition`/`slew` timing,
`$bound_step` honoured, an altered `laplace` coefficient or `transition` delay honoured,
`ddt` of an explicit time expression, `last_crossing`, `@(timer)`/`@(cross)`/`@(above)`
counts, `initial_step("ac","tran")` lists, `analysis()` in every analysis, 1-D and
2-D `$table_model` interpolation and end handling (the file format of LRM 9.21.1:
`#` comments, blank lines, tabs, CRLF, exponents accepted; `;` or `//` comments and
commas rightly refused; unsorted abscissae sorted, a duplicated knot warned),
`noise_table` with unsorted rows (sorted) and a duplicated frequency (refused),
`noise_table_log`, noise sums (uncorrelated in power,
correlated in amplitude; a source through a variable, a named block or a function),
`m=` on the instance line with `$mfactor` (LRM 6.3.6 exactly: a potential source
stays 0.5 V under `m=2`, flows double, and `I(<p>)` read inside the module is the
per-device value), instance `temp=`, `aliasparam` on an instance line,
analog operators and `$bound_step` under an `analysis()` condition accepted as constant, `analog initial` restrictions
(and an `analog initial` re-evaluated after `alter` of `temp` or of a parameter, so a
constant computed there from `$temperature` is not stale), `$strobe` formats and escapes, output
arguments zeroed and inout arguments kept (LRM 4.7.2.2), array arguments by
assignment pattern, functions in parameter defaults and ranges and paramset values,
forward references between functions, the `return` statement, string functions,
the Jacobian carried through a function's `output`, `inout` and output-array
arguments (`ddx` gives 2V, 3V², 2V and the operating point converges first try),
a variable array, a parameter array and an internal bus sized by a parameter
(`real a[0:nn-1]`, `electrical [0:nn-1] b` with a genvar loop), where a card value for
that parameter is refused with "'nn' is a fixed (localparam) value … ignored" rather
than silently mis-sizing, a one-port module (`na1 1 op1`, −1 A), a self-including or mutually including file
refused rather than looped, 500-deep `` `ifdef `` nesting, an exponential macro
expansion caught by the nesting limit in 0.1 s, non-literal `$strobe` formats printed
rather than interpreted (L026, no run-time format parsing to exploit),
multiple `analog` blocks combining (LRM 6.2), `disable` of a named block,
`break`/`continue` and `do … while` (extensions), mutual recursion refused with the
call cycle named, 2000 parameters in 0.3 s, a 100 KB string literal, `$fopen` in
`analog initial`, `$sformat` into an array element, case-sensitive string `==`,
operating-point arrays readable element-wise (`@na1[a[0]]`), and `$simparam` with the
LRM 9.15 names — `gmin`, `gdev`, `iteration`, `scale`, `simulatorVersion`,
`sourceScaleFactor`, `tnom` answer; `imax`, `imelt`, `shrink`, `timeUnit` return the
default given, or `$fatal` without one, with lint L025 at compile time.

## F1 — a parameter array cannot be passed to an analog function's array argument

LRM 4.7.1 Example 3 (`arrayadd`: `inout [0:1]a; input [0:1]b; real a[0:1], b[0:1];`)
compiles and runs with two variable arrays (33 = 1+2+10+20). The same function
signature fed a **parameter** array is refused, and the message blames the call site
for a missing index:

```verilog
parameter real c[0:2] = '{1.0, 2.0, 3.0};
analog function real sum3; input [0:2] a; real a[0:2]; sum3 = a[0]+a[1]+a[2]; endfunction
analog I(p,n) <+ sum3(c) * V(p,n);
```
```
error: 'c' requires a bit-select [i]
  = help: use `c[i]` to select a single element
```

A variable array with the same declaration passes (−6 A). A size mismatch — `real c[0:3]`
into `input [0:2] a` — gets the identical "requires a bit-select" message instead of a
size complaint. The 09-08 hunt's F3 was the same parameter-array blindness at the
declaration level; this is its function-call cousin, and a **paramset** is a third
face: `paramset ps m; .c = '{10.0, 20.0, 30.0}; endparamset` over the module above is
refused as "paramset assigns 'c', which module 'm' does not declare" (an element,
`.c[0] = 10.0`, is a parse error) — a paramset over any module with an array parameter
can bind none of it, while a child instantiation `leafa #(.c('{10.0, 20.0, 30.0}))
l1(p,n)` binds it fine (−60 A).

## F2 — an analog function's local variables are static across calls and Newton iterations

```verilog
analog function real cnt; input x; real x; integer n; begin n = n + 1; cnt = n; end endfunction
real a;
analog begin a = cnt(1.0); $strobe("cnt = %g", a); I(p,n) <+ a + V(p,n)*0; end
```

At a single `op` the strobe prints `cnt = 1074` and ngspice reaches the point only
through dynamic gmin stepping: the local `n` is never reset, so the function's value
grows with every Newton iteration and the model is a moving target. Two instances each
count on their own (per-instance statics). With `integer n = 0;` the initializer is
applied once (`cnt = 4` after four iterations), not per call. Two functions each
declaring `n` keep separate statics. The function's own identifier variable *is*
zeroed on every call (`f = f + x` twice gives 2, LRM 4.7.2.1), and an output argument
is zeroed and an inout kept exactly as 4.7.2.2 says — so the asymmetry is not what
a reader of 4.7.2 expects. The LRM does not state a rule for locals (Verilog-2005
function variables are static, which is presumably what openvaf-r inherited), but a
local read before it is written in the same call yields an iteration-count-dependent
value with no diagnostic; a lint for that read, or per-call zeroing in line with
4.7.2, would remove the trap.

## F3 — real-to-integer implicit conversion is refused in some contexts and accepted in others

LRM 4.2.1.1 converts a real to an integer on assignment by rounding; 4.7.3 assigns
the actual arguments to the formals; 5.8.3 compares case expressions. openvaf-r
applies the conversion in some of these places and refuses it in others:

| context | result |
|---|---|
| `integer k; k = 2.7;` / `integer a[0:1]; a[0] = 2.7;` / `repeat (2.7)` / `for (i = 0; i < 3; i = i + 0.5)` | accepted, converted |
| `analog function integer f; input x; real x; f = x;` (real into the integer return) | accepted, converted (2.5→3, −2.5→−3, 0.5→1, 1.5→2 verified) |
| `parameter integer k = 2.7;` | accepted with L030 |
| `analog function integer f; input y; integer y; …` called as `f(2.7)` or `f(r)` with `real r` | **refused**: "expected integer value but found real literal / real variable reference" |
| `case (sel)` with `parameter integer sel` and a label `2.0` (or a real parameter label) | **refused**: "expected integer value but found real literal" |
| `case (sel)` with `parameter real sel` and an integer label `2` | accepted |
| `analog function real f; output y; integer y; …` called as `f(a)` with `real a` | **refused**: "expected integer variable reference but found real variable reference" (defensible: the write-back needs a home of the formal's type) |
| `1 << 2.0` | refused |
| `$strobe("%d", 2.7)` | refused (defensible: the specifier names the type) |

The `case` asymmetry is the clearest: the same comparison is legal one way round and
a type error the other. A function's integer input refusing a real is what breaks
real code — `f(V(p,n) * 3)` into an integer formal is a rounding the author wrote on
purpose and can only get by an explicit temporary.

## F4 — an event control inside a non-constant conditional compiles without a word

LRM 5.8: *"Event control statements (e.g.: timer, cross) cannot be used inside
conditional statements unless the conditional expression is a constant expression."*

```verilog
integer k;
analog begin
  if (V(p,n) > 0) @(initial_step) k = k + 1;
  @(final_step) $strobe("k=%d", k);
  I(p,n) <+ V(p,n);
end
```

Compiles clean and prints `k=0` at an operating point where V(p,n) = 1: the
`initial_step` event is delivered on the first Newton iteration, when the node is
still at 0, so the condition is false exactly then and the block never runs. The same
statement under `if (1)` or under a parameter condition gives `k=1`, and a `timer`
under a node condition fires (6 of 6 over 5 µs). A `case (V(p,n) > 0.5)` selector and a
`while (i < V(p,n) * 3)` loop around the event compile the same way and give the same
`k=0`. So the construct is neither refused
nor reliable — the outcome is whatever the solver's first guess makes of the condition.
The LRM's rule exists for this reason; the constant-condition test the compiler already
applies to analog operators (4.5.15, "not allowed in conditions") is the one to reuse.

## F5 — a nature's abstol must be a literal

```verilog
nature N1; units = "x"; access = X1; abstol = 1e-3*1e-3; endnature
```
```
error: nature 'N1' declares an abstol that is not a real constant
  = the value was discarded, so the nature ended up with no abstol at all
```

A.1.6 (`nature_attribute ::= nature_attribute_identifier = nature_attribute_expression ;`
with `nature_attribute_expression ::= constant_expression | nature_identifier |
nature_access_identifier`. `1e-3*1e-3` is a constant expression. (A negative abstol
is rightly refused; a derived nature `nature Vd : Voltage; abstol = 1e-3;` works.)

## F6 — diagnostic slips

- **A contribution across two disciplines.** `electrical p; thermal2 n;` and
  `Pwq(p,n) <+ 1.0` — LRM 5.5.1 requires both nets of an unnamed branch to share a
  discipline — is reported as `invalid destination for branch contribution … expected
  nature access such as V(foo) or I(foo)`, which points the reader at the access
  function that *is* the discipline's own.
- **"encountered unexpected token!"** for three unrelated inputs: a `` `endif `` with
  no `` `ifdef ``, a `` `define `` whose `\` continuation is followed by spaces before
  the newline (`` `define K \  `` then `8.0` on the next line), and a NUL byte in the
  source. Each deserves its own sentence; the second is a classic editor artefact.
- **`` `line 100 "other.va" 0 ``** is accepted and ignored: a following error is
  still reported at the physical line of the physical file.
- **`(* openvaf_allow="no_such_lint" *)`** is accepted in silence, so a typo in a
  lint name silences nothing and says nothing.
- **`parameter integer k = 1 from {1, 2.5};`** compiles without a word; no integer
  can equal 2.5, so half the set is dead.
- **`.5`** is "unexpected token '.'; expected '(', ''{', …" while `5.` gets the
  dedicated "a real constant needs a digit on each side of the decimal point".
- **`"\777"`** prints U+01FF (`ǿ`): the octal escape is read as a code point, where
  Verilog's `\ddd` is one 8-bit character (≤ `\377`). `\q` and `\x41` pass through
  as text, silently.
- **`%m` inside a child instance** prints the top instance's name (`na1`), not the
  hierarchical `na1.l1` the LRM describes.
- **`-D G==2.0`** (a `=` at the start of the value) errors at
  `/std/__openvaf_defines__.va:5:11`, a file the user never wrote, without naming the
  `-D` argument. `-D '`G=2.0'` likewise.
- **A file that `` `include ``s itself** is "defines no module" with the unterminated-comment
  help line; two files including each other get the right sentence, "nests too deeply
  (a file that includes itself?)". The direct case deserves the same.
- **`` `define G() 6.0 ``** (empty formal list — 1364-2005 19.3.1 requires at least one formal argument) is
  "unexpected token, expected 'an identifier'" at the `)`; a sentence about the empty
  list would help.

## F7 — noise power that is NaN or negative at run time contributes nothing, in silence

`white_noise(z/z)` with `parameter real z = 0`, and `white_noise(pw)` with
`parameter real pw = -1e-20`, both compile (the check is "only when the argument is
written out as a constant") and both contribute exactly nothing to the noise analysis
— the output spectrum equals the series resistor's thermal floor. A literal `-1e-20`
is refused at compile time with a good message, so the run-time path is the only one
that stays quiet; the `$fatal` the compiler raises for a run-time zero modulus shows
the mechanism exists.

The distributions split the same way. Every degenerate *literal* argument is refused
at compile time (negative sigma, reversed uniform bounds, zero exponential mean,
negative Poisson mean — four clear sentences). At run time, from parameters:
`$rdist_exponential(s, mn)` with `mn = 0` and `$rdist_poisson(s, pm)` with `pm = -1`
raise `$fatal` citing LRM 9.13, but `$rdist_normal(s, 0, sg)` with `sg = -1` returns
0 (the mean; with sigma 0 it returns the mean too, which is fine) and
`$rdist_uniform(s, lo, hi)` with `lo = 1, hi = 0` returns 1, both without a word. A
Monte-Carlo run whose sigma parameter went negative through a formula draws nothing
and reports nothing.

## F8 — an operating-point variable whose name collides case-insensitively is unreachable on the ngspice side

Verilog-A is case-sensitive; ngspice is not. E-644 warns when two *parameters* differ
only by case. Operating-point variables (every module-level `real`/`integer`, exposed
to `show` and `@inst[name]`) take part in the same flat, case-folded namespace and get
no such warning. Four shapes, each compiled without a word:

| module declares | on ngspice |
|---|---|
| `parameter real g = 2; real G;` (G = 3) | `@na1[g]` and `@na1[G]` are both 3 — the variable shadows the model parameter; `show na1` prints `g 3`, only `showmod` still says `g 2` |
| `(* type="instance" *) parameter real w; real W;` (W = 5) | `@na1[W]` is the parameter (2); the variable is unreachable |
| `real g, G;` | `@na1[g]`: `Error: no such parameter g.` — neither is readable |
| `parameter real r; aliasparam res = r; real Res;` | `res=2` on the card applies, then `@na1[res]` is `no such parameter res` |
| `real m; real temp;` | `show na1` prints two `m` rows and two `temp` rows (the instance keyword and the variable); `@na1[m]` is the multiplier, the variables are unreachable — L029 (`reserved_parameter_name`) fires for a parameter named `m`, not for a variable |

Related, one step further from case: a parameter named `a$b` (legal Verilog) is set by
`a$b=5` on the card but `print @na1[a$b]` is "b: no such variable" — ngspice's
expression parser reads `$b` as a shell variable — so the name is write-only from
the simulator.

The compiler knows every name; the E-644/L029 checks extended to variables (against
parameters, aliases, other variables and the instance keywords) and to `$` in a name
would close this.

## Smaller notes (not pursued)

- `V(p,n) <+ 0.5; I(p,n) <+ 1.0;` in one block: L022 warns and the **last**
  contribution wins (the order swapped, the potential wins). LRM 5.4.2.2 says a branch
  cannot be both; the lint is the right response, the silent preference is not
  obvious to a reader.
- `abs(-2147483647 - 1)` is −2147483648 (the C wrap); `2147483647 + 1` folds to
  −2147483648 without the L030 word the literal `2147483648` gets.
- `$simparam("iteration")` returns a real, so `%d` on it is a type error — the LRM
  has `$simparam` return real, fine, but the name suggests an integer.
- `white_noise(pw, nm)` with a **string parameter** as the source name is refused
  ("expected string literal"); the LRM types the name as a string.
- `$strobe("%g", 1.0, 2.0)` prints `1 2` (extra arguments appended in default
  format, as Verilog does); `$strobe()` prints an empty line.
- `%l` prints `__.__`.
- `1e-400` folds to 0 silently (underflow), where `1e309` is refused.
- A sized literal wider than its size is truncated in silence: `3'b1111` is 7,
  `40'hFFFFFFFFFF` is −1 (Verilog truncates too, but every other tool warns);
  `4'b10x0` and `4'bz` are refused with the right sentence, `4'sd9` is −7 as it should be.
- `ddx(ddt(V(p,n)), V(p))` is 0 with no word; 4.5.6 does not define a derivative of
  an analog operator, so a diagnostic would be kinder than a zero.
- A `` `define `` whose body is another `` `define `` (`` `define D `define A 9.0 ``)
  produces three confusing errors; 1364-2005 19.3.1 does not allow it, one sentence
  would do.
- `analog function … ; real x; f = x;` with no `input` declaration is refused as
  "declares no arguments" — correct (LRM 4.7.1 requires at least one), and the call
  then also reports "expected 0 arguments but found 1", a second error for one cause.
- `while (1) begin … if (i > 3) break; end` is refused as "loop condition is always
  true" although `break` is accepted and ends the loop; the lint predates the
  extension it now contradicts.
- A paramset assigning through an alias (`.res = 4.0` with `aliasparam res = r`) is
  refused as "assigns 'res', which module 'psa' does not declare"; LRM 6.4 is silent on
  aliases in a paramset, so this is a choice, but the message could say so.
- `@(cross($abstime - 1e-6, +1))` fires at 1.0368 µs in a `tran 0.3u 3u` — the
  crossing is caught at the first evaluation past it (the compiler's own warning on a
  time-tolerance argument says as much; a `ttol` of 1 ns changes nothing, `@(above)` is
  the same, `$bound_step(1e-8)` brings it to 1.0092 µs), where `@(timer(1e-6))` lands at
  1e-6 exactly and `last_crossing` of the same expression interpolates to 1e-6 exactly.
  A crossing whose expression is a function of time alone could be scheduled like a
  timer.
- `$stop` anywhere, and `$finish` inside `@(final_step)`, do nothing and say nothing;
  `$finish` at the start of a transient ends it with a note and the control script
  goes on (the documented choice). A one-line note for the two silent forms would
  tell the author the call was seen.
- `$fwrite` to descriptor 0, −1 or 999, to the 0 a failed `$fopen("/no/such/dir/x")`
  returns, or after `$fclose`, is ignored in silence (no crash — good — but no word
  either; `$fwrite(1, …)` reaches stdout as Verilog says).
- An unconditional `$discontinuity(0)` in the analog block makes every accepted time
  point a breakpoint: `tran 1u 10u` takes 10001 points instead of 59 (the same call
  under a never-true condition: 59; `$bound_step(1e-7)` alone: 108). The LRM reserves
  the call for the moment a discontinuity happens; a lint on a call that no condition
  guards would catch the idiom before it costs a 170× slowdown.
- Compile time grows steeply with the number of branches that share one node: a
  star of 125 / 250 / 500 internal nodes each tied to both ports compiles in 2.3 / 5.4
  / **40** s, while a chain of 500 takes 7.5 s and of 1000 takes 17 s, and 500
  contributions on a single branch take 0.1 s. The 09-07 hunt's F4 (quadratic in an
  array's length) is the same family.

## Coverage, honestly

Probed and clean this hour: everything under "What was measured and holds" above.
Not probed: `$fopen`/`$fwrite` beyond bad descriptors (the 09-08 hunt's F6 covers
the stream semantics), genvar/generate (09-14), paramset selection beyond a value
from a function, an alias and an array (the 09-15 hunt), `zi_*` filters (09-04 F8),
the statistics of the distributions and `osdimc` (09-05; only their degenerate
arguments were tried here), KLU (09-06), multi-module elaboration beyond parameter
overrides, named-port and instance-array forms (all worked), `--print-expansion` /
`--dump-json`, the C `verilogae` API. Every probe is a two-port module on a 1 V
source; nothing here exercises large circuits or transient accuracy beyond the
timing checks listed. The wall clock ran from 08:07 to 08:56 of probing, the rest
of the hour went to this document.
