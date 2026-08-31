# Enhancement-521: analog user-defined functions, audited against the LRM

**Scope:** Accellera VAMS-2023 clause 4.7 (analog user-defined functions),
from the full LRM conformance audit. Two compiler crashes, one silent
semantic deviation, the LRM's own example failing to parse, and the
document corrections the audit's doc-half demanded. (Two further findings
of this area — the string-function ICE and the missing `return` statement
— were already fixed and released in
[E-520](Enhancement-520.md).)

**Suite:** [`examples/lrmudf_examples/`](../examples/lrmudf_examples/) —
15 checks, both solvers. The `funcarray`, `arrayout`, `arrayret`,
`argcheck`, `argguard`, `paramset`, `paramsetguard`, `paramsethsp`,
`localparam` and `blockparam` suites all still pass.

## Function-local parameters crashed codegen (LRM 4.7.1)

Syntax 4-5 lists `parameter_declaration` among the analog function items,
and the clause defines the scoping rule that depends on it: "if a
locally-defined parameter with the specified name does not exist, then the
module-level parameter of the specified name will be used." Declaring one
— `parameter real k = 3.0;` inside a function — compiled through the
front end and aborted code generation with "internal error: attempted to
read undefined value".

The mechanism: a parameter read lowers to a `ParamKind::Param` slot, and
those slots are bound to OSDI parameters collected by the module
declaration walk — which descends into named *blocks* but never into
*function* scopes. A function-local parameter therefore had a MIR slot
nothing ever defined.

The fix follows what the parameter *is*: a pure compile-time local, never
an OSDI parameter, never netlist-settable. A read of one now inlines its
**default expression** at the call site. Module-parameter references
inside that default resolve to real OSDI parameter slots — which is
exactly the clause's rule, verified from the netlist side: overriding a
module parameter the function reads (directly or through a local's
default) changes the function's value; overriding a module parameter the
function *shadows* does not. Chained locals (`parameter real k2 = k1 +
1.0;`) recurse through the same path. A function-local parameter *array*
remains a clean located error rather than a crash.

### The latent bug this exposed

`$param_given` on a function-local parameter must answer a constant false
(there is no given-flag slot). The first cut answered `iconst(0)` — and
crashed the MIR constant folder: `ParamGiven` is *bool*-typed, so
inference records a bool→int cast at integer-assignment sites, and a
`bicast` over an INT constant hits the folder's unreachable arm. The
E-398 **paramset** path had the identical latent bug (`iconst(1)` for a
paramset-bound parameter) waiting for anyone to write `g =
$param_given(x)` through a paramset. Both arms now return proper BOOL
constants, which the folder handles.

## Output arrays had inout semantics (LRM 4.7.2.3)

"All output arguments of an analog user-defined function are initialized,
zero (0) if numeric … which in turn means that the argument passed to it
is reset to zero (0) … accordingly." The *scalar* path conformed exactly.
The whole-array path took the Enhancement-18 early branch, which copied
the caller's elements in **regardless of direction** — so a pure `output`
array behaved like `inout`: the body read the caller's values where the
LRM mandates zeros, and an unassigned output array left the caller
unchanged where the LRM mandates the reset.

Array formals now check the direction first: input/inout arrays copy in
(E-18/E-33 semantics untouched, literals included), pure output arrays
zero-initialize element-wise, exactly like the scalar path — and the
existing unconditional copy-out turns that zero-init into precisely the
caller reset the LRM prescribes. The audit's failing case reads 100 now
(it read 1256); a mixed test pins partial assignment (`{6,0}`) next to an
untouched inout (`{8,8}`) in one call.

## The LRM's own array-argument spelling was a parse error (4.7.1 Example 3)

Example 3 writes array formals with the range on the *direction* line:

```verilog
analog function real arrayadd;
    inout [0:1]a;
    input [0:1]b;
    real a[0:1], b[0:1];
    ...
```

That was "unexpected token `[`; expected identifier" — the LRM's own
example did not compile. Worse, the compiler's **namerange elaboration
pass rewrites** the name-then-range spelling (`output o[0:1];`) into
exactly this range-then-name form, generating syntax its own parser then
refused: the pipeline was inconsistent with itself.

`func_arg` accepts the range now (after the direction and after an
optional combined type, one position covering both). The argument's array
dimensions come from its mandatory data-type block-item declaration —
which Example 3 carries, making the direction-line range the same
dual-declaration redundancy the LRM itself writes. Example 3 compiles
verbatim and computes exactly (816); both range spellings pass the
output-array semantics checks; the namerange round-trip is healed.

## Documented

The compliance doc's analog-functions section carried a nonexistent
clause number ("LRM 5.11" — user-defined functions are clause 4.7) and a
blanket pass over both crashes; it is rewritten with the fixes and the
recorded relaxations: **named blocks inside function bodies** stay
accepted (4.7.1 forbids them, but pre-2023 early exit *needs*
`begin : b … disable b` — the very idiom `return` replaced), **UDF calls
in constant contexts** stay accepted and constant-evaluated (4.7.3
restricts calls to the analog context), and the untyped-formal default,
ANSI header, and array-return forms are labeled the OpenVAF extensions
they are. A stale handbook bullet still claiming "break/continue don't
exist in Verilog-A" — missed by E-520's doc pass — was caught and fixed.
