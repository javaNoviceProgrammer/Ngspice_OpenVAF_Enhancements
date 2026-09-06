# genhier_examples — hierarchical names into generate blocks (Enhancement-564)

The generate-naming gaps the
[coverage audit of *A Practical Guide to Verilog-A*](../../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md)
§3.4 recorded (chapter 18), closed and pinned through **the committed**
`openvaf-r` and `ngspice-46`, both solvers.

## What was missing

Generate blocks elaborated, but nothing could name what they declared: `V(blk.x)`
for a named `if`-block was *'blk' was not found*, `V(g1[0].z)` for a loop
iteration a parse error, and the implicit `genblk<n>` names of LRM 6.6.3 did
not exist at all — so the book's chapter-18 examples, which are about those
names, were unreachable. A generate branch without `begin`/`end` (`if (c)
electrical a; else electrical b;`, the shape the LRM's own example uses)
mis-parsed and swallowed the items after it, which is why a `case` following
one failed at its `default`.

## What the model shows

`genhier.va` declares, in one module, every kind of generated scope and reads
each back through its LRM 6.7 hierarchical name from the analog block:

| construct | name | declares |
|---|---|---|
| `if (sw) begin : blk … end` | `blk.x` | a net driven to 1 V |
| `if (genblk2) electrical y; else electrical y;` with `localparam integer genblk2` declared | `genblk02.y` | the 6.6.3 leading-zero rule: the second construct would be `genblk2`, which is taken |
| `for (i …) begin : g1 … end` | `g1[0].z`, `g1[1].z` | 4 V and 8 V |
| `if (1) begin … end` inside the loop | `g1[0].genblk1.w`, `g1[1].genblk1.w` | 0.5 V and 1 V |
| `case (sel) … 2: begin : two … end` | `two.q` | 16 V |
| `leaf r1(a, b)` inside the loop | `g1[0].r1.mid`, `g1[1].r1.mid` | a child instance's internal net |

The device current is the sum of those voltages (32.5 mA plus the leaves'
terms), exact at two bias points. `refused/` pins the two errors: a member the
block does not declare, and a loop index the loop never took, each naming the
block and what it does declare.

Every generate construct of a scope is numbered in textual order; a block
without a label is `genblk<n>`; the elaborator records the flat name of
everything each block declares under its hierarchical path and rewrites the
module's references to those names — the longest matching prefix, so
`g1[0].r1.mid` becomes `r1_0.mid` for the instantiation pass to resolve.

## Run

```
python3 verify_genhier.py
```

5 checks per solver, all PASS.
