# derivednature_examples — derived natures & discipline-derived natures (Enhancement-39)

Demonstrates **derived natures** — `nature X : Parent;` and
`nature X : electrical.flow / electrical.potential;` (LRM 3.4.1.3) — using
**the committed** `openvaf-r` and `ngspice-46`.

## What was broken

The complete inheritance machinery (parent chains, units/ddt/idt inheritance,
attribute lookup, access-function compatibility) existed in `hir_ty::NatureTy` but
was **unreachable**: the parser emitted a `NAME_REF` node for the `: parent`
clause while the AST accessor looked for a `Path` child, so the parent link was
silently always `None`. Consequences:

- `nature TightCurrent : Current; abstol = 1e-15;` — the canonical
  tighten-the-tolerance pattern — rejected the inherited access function
  (`I(a,c)` → "illegal access of branch");
- `nature X : electrical.flow;` did not parse at all (plus a validation gate that
  only whitelisted `ddt_nature`/`idt_nature` as qualified segments);
- `ddt_nature = electrical.potential;` **hard-panicked** the OSDI
  nature-descriptor builder.

## The fixes

Parse the parent as a **path** (one line lights up all the dormant machinery);
whitelist `potential`/`flow` in the nature-path validation; resolve
discipline-qualified `ddt_nature`/`idt_nature` to the underlying nature's index
in the OSDI descriptor builder instead of panicking. See `../Enhancement-39.md`.

## Run

```
python3 verify_derivednature.py
```

Checks (ALL PASS): the 5-module matrix compiles (three constructs used to
fail/crash); exact runtime conductances prove the inherited access functions
resolve end-to-end (inherited `I`, discipline-derived natures, own access `I2`,
two-level chain); the discipline-qualified `ddt_nature` descriptor builds and
loads.
