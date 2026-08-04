# Enhancement-411 — the bus that looked consistent and was wired backwards

```
nd1 d[3:0] 0 mm          // model declares: inout [3:0] a;
```

Both sides say `[3:0]`. It compiles clean, simulates clean, and the terminals
are connected in **reverse order**. Nothing said so.

## Two conventions that disagree

**The compiler declares a bus port's terminals in ascending bit order**, whatever
direction the declaration is written with. `hir_def`'s item_tree lowering sorts
the endpoints and loops upward:

```rust
let (lo, hi) = if msb >= lsb { (lsb, msb) } else { (msb, lsb) };
// declare from lsb to msb (ascending), matching natural bit order;
// direction of the original [msb:lsb] only affects range checks
for bit in lo..=hi {
```

So `inout [3:0] a` and `inout [0:3] a` produce the **same** positional terminal
list — a[0], a[1], a[2], a[3]. Writing `[3:0]` does not make a[3] the first
terminal; it only decides which indices are legal.

**The netlist does honour direction.** Enhancement-221 expands `d[3:0]` to
`d[3] d[2] d[1] d[0]`, and `d[0:3]` to `d[0] d[1] d[2] d[3]`.

Since the instance line's Nth node binds to the model's Nth terminal, a
descending node list reverses the mapping — and the spelling that looks most
*consistent*, `[3:0]` on both sides, is precisely the reversed one.

## Measured, not argued

Each bit carries a distinct conductance (a[k] → (k+1) mS), so the current at a
node identifies the bit it really landed on:

| model declares | instance line | d[0] | d[1] | d[2] | d[3] | |
| --- | --- | --- | --- | --- | --- | --- |
| `[3:0]` | `d[0:3]` | 1 | 2 | 3 | 4 | in order |
| `[3:0]` | **`d[3:0]`** | 4 | 3 | 2 | 1 | **reversed** |
| `[0:3]` | `d[0:3]` | 1 | 2 | 3 | 4 | in order |
| `[0:3]` | **`d[3:0]`** | 4 | 3 | 2 | 1 | **reversed** |

The two halves are identical: **the model's own declaration makes no difference
at all.** Only the instance line decides.

## The diagnostic

```
Warning: descending bus range "d[3:0]" binds nodes to terminals in REVERSE order
    in line: nd1 d[3:0] 0 mm
  a Verilog-A bus port declares its terminals in ascending bit order whatever
  direction it is written with, so [hi:lo] on both sides is a reversal, not a match;
  write the ascending form or list the nodes explicitly
  (`set nobusdirwarn` in .spiceinit silences this; a `set` inside .control is too late,
  because bus ranges expand while the netlist is read)
```

## Where it deliberately stays quiet

The scope came from scanning what the shipped suite actually does with
descending buses, not from taste. Three kinds of use turned up, and only one is
the trap:

| case | reports? | why |
| --- | --- | --- |
| element instance line, `nd1 d[3:0] 0 mm` | **yes** | node order binds to terminals |
| any built-in element, `rr d[1:0] 1k` | **yes** | same |
| `.subckt sub p[1:0]` port list | no | a descending interface is a deliberate choice — E-221 documents it and `busnodes_examples` tests it |
| `.save` / `.print` / `.ic` | no | the order binds nothing there |
| `e[99999999999999999999:0]` | no | never expands (E-338's width guard), so the binding never happened |
| explicit node lists, `d[2:2]` | no | nothing is reversed |

Verilog-A **part-selects** (`v[3:2]`, `.i(v[1:0])`) live in the compiler, not the
netlist reader, and are untouched.

## The opt-out had to be corrected

It was first documented as `set nobusdirwarn`. Testing it inside `.control`
showed it **does not work there** — bus ranges expand while the netlist is being
read, long before `.control` runs. It works from `.spiceinit`, verified in both
directions (present → 0 warnings, removed → 1). The message now says so, rather
than pointing at a path that silently fails.

## Verification

* **`examples/busdir_examples` 20/20**, and **13/20 on the pre-411 binary**.
* The example pins the binding itself as well as the diagnostic, including that
  `[3:0]` and `[0:3]` declarations behave identically — so if the compiler ever
  changed that convention, the example would catch it rather than quietly
  agreeing.
* **Full regression 327/327**, and the warning fires **0 times** across the whole
  suite, so any future firing is signal. `busnodes` (which relies on a
  descending `.subckt` port list), `busoverflow` and `partselect` all stay
  silent.
* The compiler is untouched — this release is entirely ngspice-side, and adds a
  diagnostic without changing any binding.

## Found by

A user asking what an earlier bug-hunt note meant. Reproducing it to explain it
turned the note into a measurement, and the measurement into this warning.
