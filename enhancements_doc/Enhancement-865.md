# Enhancement-865: `^` associates left to right in `let`, as everywhere else — `let` gave 2^3^2 = 512 where the netlist gives 64

**Scope:** F10 of the
[third robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-third-robustness-campaign.md).

ngspice: `frontend/parse-bison.y`: `'^'` is `%left`.

`examples/powassoc_examples/` (new). **ngspice only.**

**Suites:**
- [`powassoc_examples`](../examples/powassoc_examples/): 5 of 5 per solver. On the E-863
  binaries 2 fail; [3], [4] and [5] are controls.
- The full sweep: 571 of 571.

## What was wrong

| | `.param` | B-source | `let` on E-863 | Verilog-A (openvaf-r) |
|---|---|---|---|---|
| `2^3^2` | 64 | 64 | 512 | 64 (`2.0**x**2.0`, x = 3) |
| `2^0.5^2` | 2 | 2 | 1.189 | — |
| `-2^2` | −4 | −4 | −4 | 4 (`-2.0**2.0`) |

The manual (§2.11.5) says equal-precedence binary operators evaluate left to right, so 2^3^2 is
(2^3)^2 = 64. The `.param` and the B-source do that, and so does Verilog-A: its LRM associates
every binary operator left to right. `let`'s grammar had `'^'` `%right` and gave 512.
The campaign page said Verilog-A associates right to left; openvaf-r, following the LRM, gives
64.

The manual's precedence table also lists unary minus (precedence 1) above `**` (2), which would
make −2^2 = 4. That is Verilog-A's rule, where unary operators bind tightest. All three of
ngspice's parsers put unary minus below `^`: the B-source's grammar has `NEG` below `'^'`, `let`'s
the same, and numparam takes a sign's operand to be the power chain after it
([Enhancement-857](Enhancement-857.md)). The table is what is wrong. It is in the shipped manual
PDF; the handbook now gives the order the parsers use.

## The change

`'^'` is `%left` in `let`'s grammar. 2^3^2 is 64, 2^0.5^2 is 2, and 2^2^3 is 64, the `.param`'s
and the B-source's values to the bit. A sign inside a chain is unchanged: 2^-3^2 is 2^(−(3^2)) =
2⁻⁹ in all three. The grammar's conflicts are resolved by precedence as before, so `%expect`
is unchanged.

A control script that wrote a chain of powers meaning right to left changes. It writes the
parentheses now.

## The checks

`powassoc_examples`, each expression through a `.param`, a B-source and `let`:
- **[1]** `let` 2^3^2 is 64 (512 on E-863).
- **[2]** 2^0.5^2, 2^2^3, 3^2^0.5: the three agree to the bit.
- **[3]** (control) 2^-3^2 is 2⁻⁹ in all three.
- **[4]** (control) −2^2 and −(2)^2 are −4, (−2)^2 is 4, in all three.
- **[5]** (control) The `.param`'s `**` and `^` chains are 64.
