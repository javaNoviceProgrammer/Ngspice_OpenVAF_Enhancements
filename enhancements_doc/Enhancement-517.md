# Enhancement-517: data types and parameters, audited against the LRM

**Scope:** Accellera VAMS-2023 clauses 3.1–3.5 (value types, output
variables, strings, parameters, aliases), from the full LRM conformance
audit (`docs/audits/2026-08-31_LRM-conformance-audit.html`). One bug, two
missing features, two alias rules under-enforced, one deviation made
audible, and one real-world regression caught and fixed along the way.

**Suite:** [`examples/lrmdata_examples/`](../examples/lrmdata_examples/) —
20 checks, both solvers. The `alias`, `paramarray`, `blockparam`, `opvar`,
`localparam`, `strparam` and `varinit` suites all still pass.

## Block-level output variables leaked (LRM 3.2.1)

"Units and descriptions specified for block-level variables shall be
ignored by the simulator." They were not: `sim_back::module_info` *meant*
to skip block-scoped variables by comparing `to_path(name)` against the
bare name — but `RecDeclarations::next` never pushes block names onto its
path, so the two were always equal and the filter never fired. Every
`(* desc *)` variable in a named block was exported as an OSDI opvar under
its bare name; two blocks declaring the same-named variable produced
*duplicate* opvar descriptors, and ngspice warned about parameters
"differing only in case". The fix asks the declaration walker directly
(`in_block()`); module-scope opvars are untouched.

## String literals convert to integers (LRM 3.3)

"A string literal can be assigned to a string or an integral type. If
their size differs, the literal is right justified and either truncated on
the left or zero filled on the left." `integer i = "A";` was a hard type
error. The literal now packs its character codes — `"A"` = 65, `"AB"` =
0x4142, `"ABCDE"` keeps its last four bytes — on both the declaration-init
and assignment paths (they type-check through different code: the
initializer flows through `infere_assignment`, which never consults the
`satisfies` table, so the conversion lives there). Only the *literal*
converts: a string **value** assigned to an integer stays the error the
LRM requires.

## Whole-array parameter overrides at instantiation (LRM 3.4.4 / 3.4.8)

Array parameters expand to per-element OSDI scalars, individually
overridable from SPICE — but the LRM's own 3.4.8 example overrides a
multi-dimensional array *at instantiation* with an assignment pattern,
and that form was rejected as "names no parameter". `#(.cf('{9,8,7}))`
now distributes the pattern to the per-element parameters, 1-D and
multi-dimensional, with 3.4.4's "the sizes shall match" enforced (wrong
element count names both sizes; a scalar override asks for a pattern).
The `lrm_examples` crosstalk pin was updated: the array-literal override
is no longer on its limitation list.

## The aliasparam error rules (LRM 3.4.7)

"It shall be an error to specify an override for a parameter by its
original name and one or more aliases, or by more than one alias,
regardless of how the override is done." ngspice (E-395) detected the
conflict but issued a *warning* and let one value win — last-wins on model
cards, first-wins for instance defaults, deliberately unspecified. Both
the `.model` card and the instance line are errors now; setting the *same*
spelling twice stays the E-395 warning. And "the alias_identifier shall
not occur anywhere else in the module": an alias referenced in module
equations silently resolved to its target's value — now a targeted
compile error naming the alias and the clause. `$param_given` through the
alias (the advertised E-59 extension) still works.

## The frozen-type deviation, made audible (LRM 3.4.1)

"If the type of a parameter is not specified, it is derived from the type
of the final value assigned to the parameter, after any value overrides
have been applied." A compiled OSDI descriptor declares exactly one type
per parameter, so `parameter untyped = 1;` freezes as *integer* and a
netlist override of 2.5 is rounded — that cannot change and is now
documented in the handbook's limitations chapter. What could change: the
round was **silent**. The netlist parser's integer path (the E-399/E-509
site) now raises a flag when rounding alters the value, and both the
`.model`-card and instance-line appliers print a warning naming the
parameter. Integral values stay silent.

## The regression the fixes caught: BSIM4 stopped compiling

E-515 made "a string spanning a raw newline" an error (LRM 2.7). This
area's verification ran the big-model battery and found **BSIM4 failing
with 17 of those errors**: it splits long `$strobe` messages with
backslash-newline — a construct every real-world Verilog-A compiler
accepts and SystemVerilog legalizes outright. The validator now treats an
*escaped* newline as a line continuation, and the unescaper drops the
pair entirely (it used to keep the newline, which would have cut BSIM4's
messages mid-sentence — each ends with its own explicit `\n`). A bare
newline stays the E-515 error. All thirteen big CMC models compile clean.

## Documented, not changed

- **Default-range exemption** (3.4.2) and **non-resizable array
  parameters** (3.4.4): already-documented deliberate deviations; the
  compliance doc keeps them flagged.
- **Untyped string/array parameters** (3.4.1 makes their type mandatory):
  leniently accepted with the type inferred from the default — now
  recorded in the compliance doc.
- The compliance doc's paramset citation was corrected (3.4.6 → 6.4).

## What the regression battery caught

The first cut of the string-literal conversion added a general
`satisfies` arm (string literal acceptable wherever an integer is
expected). That was too broad — it would have accepted `min("A", 2)` —
and was withdrawn for the assignment-path-only special case before
anything shipped. The ngspice alias error's first cut double-freed
`parm` on the instance-line path (the `quit` label frees it too); caught
by inspection, fixed before commit.
