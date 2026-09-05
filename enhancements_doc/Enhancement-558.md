# Enhancement-558: the range error says the declared range and what moved it, quoted file names are unquoted, `.save` takes a model card's parameter

**Scope:** F9, F10 and F11 of the
[bug hunt of 2026-09-05](../docs/bug_hunts/2026-09-05_strings-mcexpr-and-osdimc-distributions.md).
The compiler's HIR (`openvaf/hir/src/lib.rs`), its parameter analysis
(`openvaf/sim_back/src/{lib,module_info}.rs`) and OSDI export
(`openvaf/osdi/src/{lib,metadata}.rs`); the simulator's registry and
range check (`src/osdi/{osdiregistry.c,osdisetup.c}`,
`src/include/ngspice/osdiitf.h`), the deck reader and the file-writing
commands (`src/frontend/{inp.c,postcoms.c,com_gnuplot.c}`), and `.save`
(`src/frontend/outitf.c`). **Compiler and ngspice together** for F9; ngspice
alone for F10 and F11.

**Suites:** [`paramgiven_examples`](../examples/paramgiven_examples/) 16 → 18
(the message with the moved bound's value; the model-card save; its F2 checks
updated to the longer message),
[`rawfstring_examples`](../examples/rawfstring_examples/) 18 → 19 (quoted
names with a space through `wrdata`, `write` and `source`; the missing-file
text), both solvers; the eleven adjacent suites pass; full sweep 459 of 459;
compiler tests unchanged; the model corpus compiles with every model's range
text rendered. Handbook [§3.2](../docs/handbook/03-ngspice-workflows.md),
[§3.6](../docs/handbook/03-ngspice-workflows.md) and
[§3.10](../docs/handbook/03-ngspice-workflows.md), README_OSDI, the
[compiler internals](../docs/internals/openvaf_internals/OpenVAF_compiler_internals.md).

## What was wrong

**F9.** `Parameter l of 'mm' is out of bounds (value 1.2)!` named the
parameter that did *not* move. Under `parameter real l = 1.2 from [lmin:inf)`
an `altermod mm lmin=1.5` is the whole story, and the message gave no way to
see it: not the declared range, not the bound's current value, not which
parameter set it. E-555 had just made such a default *judged* when its range
moves; the judgement's message stayed the old one.

**F10.** `wrdata "o3.txt" v(out)` wrote a file literally named `"o3.txt"`,
quotes and all; `write "w2.raw"` did the same, and `source "sub1.cir"` failed
with *`"sub1.cir": Inappropriate ioctl for device*: the wrong file, and an
errno text left over from an earlier call rather than the missing file's own.
A quoted name is the spelling for a path with a space, and what an f-string
with whitespace in it yields (E-556), so the new forms inherited the defect:
`wrdata f"o{1+1}.txt"` wrote `"o2.txt"`. `cd "sp dir"` unquoted; the others
did not.

**F11.** `.save @mm[s]` of a model card's parameter was refused — *no such
device, so this vector will stay empty* — while `print @mm[s]` and
`montecarlo -expr @mm[s]` read it, and `.save @n1[r]` of an instance
parameter worked.

## What changed

* **The compiler exports each parameter's range as the source spells it.**
  `Parameter::bounds_source` renders `from`/`exclude`, the brackets and the
  bound expressions from the body's source map; sim_back interns the texts
  (the codegen's string constant looks a literal up and does not create one)
  and the osdi crate exports `OSDI_PARAM_RANGE_COUNTS` / `OSDI_PARAM_RANGES`,
  one C string per parameter in `param_opvar` order, NULL for a parameter
  without a range. The descriptor ABI is unchanged; an object without the
  symbol gives the old message.
* **The simulator's message says the range and what moved it.** The registry
  slices the texts per descriptor; the out-of-bounds message appends the text
  and the current value of every parameter it names, read where the failing
  parameter lives — `Parameter l of 'mm' is out of bounds (value 1.2; range
  from [lmin:inf), lmin = 1.5)!`; `(value 2; range from (0:w], w = 1)` for a
  per-instance range; `(value -5; range from (0:inf))` for a static one.
* **`wrdata`, `write` and `source` unquote their file names**, and `source`
  probes a file it could not open once more and reports *that* errno:
  `nosuch.cir: No such file or directory`.
* **`.save` accepts a model card's parameter.** A name that resolves to a
  model card is accepted at save time, checked against the card's parameters
  (an unknown one warns), and read per point through the resolver `print`
  uses.

## Verification

| check | result |
|---|---|
| `altermod mm lmin=1.5`, `op` (`l = 1.2 from [lmin:inf)`) | *Parameter l of 'mm' is out of bounds (value 1.2; range from [lmin:inf), lmin = 1.5)!* |
| the per-instance and the static range | *(value 2; range from (0:w], w = 1)*, *(value -5; range from (0:inf))* |
| an object from a compiler without the symbol | the old message, unchanged |
| `wrdata "q 1.txt" v(out)`, `write "q 2.raw" v(out)`, `source "sub deck.cir"` | `q 1.txt`, `q 2.raw` written, the sub-deck sourced; no file with quotes in its name |
| `source nosuch.cir` | *nosuch.cir: No such file or directory* |
| `.save @mm[s]`, `tran` | the card's parameter recorded per point; `.save @mm[nosuch]` warns |
| `paramgiven_examples`, `rawfstring_examples`; full sweep | 18 / 18, 19 / 19; 459 of 459 |
