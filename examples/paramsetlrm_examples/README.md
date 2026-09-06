# paramsetlrm_examples — paramsets per LRM 6.4 (Enhancement-563)

The paramset gaps the
[coverage audit of *A Practical Guide to Verilog-A*](../../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md)
§3.3 recorded (and the compiler crash of §3.1), closed and pinned through
**the committed** `openvaf-r` and `ngspice-46`, both solvers.

## What was missing

Enhancement-21's paramset bound a module's parameters from its own, and no
more. The chapter's idioms — every one of them also in the LRM's own examples —
were refused, or worse:

* a paramset parameter **named like the module's** (`parameter real L = 3u;
  .L = L;`): *'L' was already declared in this scope*;
* a **paramset of a paramset** assigning the parent's own parameters:
  *definition of 'MAT' references parameter 'KIND' defined afterwards*;
* an **`aliasparam`** in a paramset (and a module's alias in an instance
  override): *'.LL' names no parameter*;
* **variables and statements** computing output variables from the module's
  (`pdis = .reff * 1e-6;`): a parse error;
* a **hierarchical reference to another module's `localparam`** in an override
  (`.RSH = fab.rsh_poly * fab.bias;`, the "constant module" idiom): a compiler
  crash in code generation;
* and a paramset **instantiated inside a module** rendered the module at its
  defaults — the bindings were silently lost.

## What the models show

`vres_ps.va` holds one resistor module `vres` (`reff = RSH (L−DL)/(W−DW)`), a
constant module `fab`, and four paramsets:

| paramset | construct | check |
|---|---|---|
| `rp vres` | own `L`, `W`, `KIND` reusing the module's names; `.RSH = fab.rsh_eff` (a localparam computed from two others); `.$mfactor = 2` | `reff` exact at the defaults and with `L=6u W=2u` on the card; `RSH=5` on the card is not settable |
| `rmetal rp` | a paramset of `rp`: `.KIND = "metal"; .L = LEN;` with `aliasparam LL = LEN;` | `reff` exact; `LL=5u` on the card reaches `L` |
| `rpd vres` | `(* desc *) real pdis, fig; real scratch;` and statements `scratch = .reff * 1e-6; pdis = scratch * 2.0; fig = .reff / 100.0;` | `pdis` and `fig` as computed; the paramset's `fig` replaces the module's `−1` |
| `divider` | `rmetal #(.LL(LA)) ra`, `rp #(.W(WA), .L(LA), .$mfactor(3)) rb`, `rpd #(.WID(2u)) rc` instantiated in a module | `i(vin)`, `v(out)`, `ra__reff`, `rb__reff` (m = 2·3 on `rb`), `rc__pdis`, `rc__fig` all exact |
| `refused/*.va` | a contribution, an event control, a named block and an access function in a paramset statement; a paramset parameter named like a net of the module; assigning a `localparam` or a parameter an earlier paramset fixed; a reference to a non-local parameter of another module; an instance overriding a parameter its paramset fixes | each refused with the named diagnostic |

Inside the compiled twin module a module declaration whose name the paramset
reuses lives as `name$paramset`; the module's text is read through that map,
so the two namespaces stay apart exactly as LRM 6.4 keeps them. The hidden
declaration never reaches the netlist (`print @n1[reff]` reads the module's
`reff`; `@n1[fig]` the paramset's).

## Run

```
python3 verify_paramsetlrm.py
```

22 checks per solver, all PASS.
