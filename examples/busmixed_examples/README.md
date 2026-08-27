# Enhancement-490 — mixing shorthand and written-out bits on a bus port

```
python3 verify_busmixed.py
```

46 checks, a few seconds. **20/46** against the pre-fix binary —
**26** checks discriminate.

## What it is

`.option autobus` ([Enhancement-444](../../enhancements_doc/Enhancement-444.md))
lets one netlist token stand for a whole Verilog-A bus port:

```
N1 a b bmix        ->  N1 a[0] a[1] a[2] a[3] a[4] b[0] b[1] b[2] bmix
```

It fires on a token count equal to the **port** count. Positional binding covers
the other complete form, a count equal to the **terminal** count. A line that
leaves one port in shorthand while writing another port's bits out is **neither**:

```
N1 a b[0:2] bmix          for   inout [0:4] a;  inout [0:2] b;
```

so it fell through both and bound positionally against the flat terminal list.

## What it did instead

`busmixed.va` gives every one of the eight bits its own conductance, so a
misbinding by a single terminal changes every current. Measured before the fix,
driving each node at 2 V:

| token | bound to | conductance seen | intended |
|---|---|---|---|
| `a` | `a[0]` | 1 | 1 |
| `b[0]` | `a[1]` | ½ | 1/32 |
| `b[1]` | `a[2]` | ¼ | 1/64 |
| `b[2]` | `a[3]` | ⅛ | 1/128 |

Every node one or more terminals off. The only thing said was
[E-402](../../enhancements_doc/Enhancement-402.md)'s warning naming the terminals
left over at the tail — the symptom, not the cause. Supply the two nodes it asks
for and the circuit is still wired entirely wrong, now with no warning at all.

[E-445](../../enhancements_doc/Enhancement-445.md)'s diagnostic exists for exactly
this mistake — *"already carries an index, so it cannot be expanded as the bus
port"* — but sits **inside** the port-count check, one `if` from the line that
needed it.

## Nothing here is ambiguous

The fix does not guess. It walks the ports left to right and lets each token
declare which form it is in:

* a **bare** name on a bus port is shorthand for that port's bits;
* a token **already carrying an index** — or **ground**, which E-445 established
  can never be indexed — means that port was written out, so take one token per
  bit.

`N1 a 0 0 0 bmix` reads correctly under the same rule: shorthand for `a`, three
explicit grounds for `b`. Checks for that, for both mixed orderings, for bits
written one by one, and for the KiCad spelling `b_0_` are all differentials
against the same circuit written out in full.

The rewrite is accepted only when the walk consumes **exactly** the tokens the
line has. Where the counts do not reconcile, the bits written do not match the
width the model declares and no reading can repair it, so it is refused where the
port and both counts are still in hand to say so:

```
Error: instance n1: this line mixes a bus port written in shorthand with
       another port's bits written out, and the two do not add up.
       Model 'bmix' has 8 terminals in 2 ports, and the line writes 6 node
       tokens. Reading them port by port -- 'a' in shorthand for its 5 bits,
       then one token per bit for each port written out -- uses only some of them.
       Write every bus port the same way: 2 tokens (each bus in shorthand)
       or 8 (every bit written out). A range written here may also be the
       wrong width for the port it feeds.
```

## The controls

Most of the suite is checks that must **not** move, because this change sits in
the middle of a parser path five other enhancements share:

* `.option autobus` **off** — a mixed line binds positionally and gets E-402's
  warning, exactly as before.
* an **all-shorthand** line and an **all-explicit** line.
* a short line with **no shorthand token** — every bit written out, trailing
  terminals omitted. That is the `$port_connected` idiom E-402 was careful to
  preserve.
* E-445's two refusals on a full-width line, now naming the port `a` rather than
  the terminal `a[0]`.
* every on-word and off-word of the option, including `autobus=1`, which used to
  report a style that does not exist, and `autobus=bogus`, which still must.

## The models

`busmixed.va` holds three: `bmix` (`[0:4]` and `[0:2]`, unequal widths), `bscal`
(a bus beside a scalar port, so the scalar is pinned to one token), and `bdesc`
(a descending `[4:0]` beside a non-zero-based `[1:3]`, so the generated bits are
proved to come from the model's own terminal names rather than a counter).
