# Enhancement-816: a paramset's `.$mfactor = 8` no longer draws L036 — the `$paramset$mfactor` it warned about is the compiler's own hidden localparam, not a name the author wrote

**Scope:** found while folding [E-814](Enhancement-814.md). openvaf:
- `sim_back/src/module_info.rs`: `is_paramset_sysfun_name`; `check_exported_names` leaves
  those names out of L036 (`dollar_in_exported_name`).

`examples/exportname_examples/` (check [14b]). **openvaf only.**

**Suites:** [`exportname_examples`](../examples/exportname_examples/) 21 of 21 per solver (the
new check fails on the E-813 binaries; the other 20 pass there). The workspace tests. The
full sweep, 541 of 541.

## What was wrong

Enhancement-44 turns each hierarchical system parameter a paramset binds into a hidden
real localparam named `$paramset$<name>`:

```verilog
paramset quad rbase;
  .r = 2e3;
  .$mfactor = 8;        // becomes localparam $paramset$mfactor = 8
endparamset
```

The `$` spelling is deliberate: no user identifier can collide with it, and it stays apart
from the OSDI built-in `$mfactor`, so ngspice's `m=` still means the instance's own
multiplier. The parameter is exported as a localparam (`PARA_FLAG_FIXED`), so the simulator
refuses any write to it. `showmod` lists it, as `_paramset$mfactor 8`.

L036 (`dollar_in_exported_name`, E-652/E-665) reported it all the same:

```
warning[L036]: model parameter '$paramset$mfactor' has a `$` in its name, which ngspice's
expression parser cannot read
   |   .$mfactor = 8;
   |   ^^^^^^^^^^^^^^ write-only from ngspice
   = help: rename it in the Verilog-A source of module 'quad'
```

There was one warning per binding: `.$mfactor`, `.$xposition`, `.$angle` and the others. It
was model-level for a constant binding, and instance-level for one that reads the paramset's
own instance parameter (`.$mfactor = nf`). The help asked the author to rename a name they
never wrote, on a correct deck. E-652 already exempted the other name a paramset
synthesizes, the `x$<paramset>` twin of a redeclared variable. These hidden parameters were
not covered, because their name after the last `$` is a system parameter, not a module.

## The change

`is_paramset_sysfun_name` recognises exactly the hidden spelling: `$paramset` followed by one
of the six hierarchical system parameter names (`$mfactor`, `$xposition`, `$yposition`,
`$angle`, `$hflip`, `$vflip`). L036 skips those names, as it skips the twins. An author's
`$` is still reported, including an escaped `\$paramset$foo`.

The parameters stay exported as they were: fixed, and listed by `showmod` and `devhelp`,
where they show what the paramset binds.

## The checks

`exportname_examples` [14b] compiles two paramsets of one module:
- `.$mfactor = 8` and `.$xposition = 2.0`;
- `.$mfactor = nf` over a paramset instance parameter.

The module compiles with no L036, and the bindings still act: an instance with `m=3` draws
24 mA (3 × 8 × 1 mA), and `nf=4` draws 4 mA. Checks [11]–[13] still report an author's `$`
in a model parameter, an operating-point variable, an instance parameter and an alias.
