# Enhancement-490 — mixing shorthand and written-out bits on a bus port

**Files:** `src/spicelib/parser/inp2n.c`, `src/frontend/subckt.c`,
`src/include/ngspice/inpdefs.h`.

**Suite:** `examples/busmixed_examples/` — 46 checks.

## Why

`.option autobus` (Enhancement-444) lets one netlist token stand for a whole
Verilog-A bus port. It fires on a token count equal to the **port** count.
Positional binding covers the other complete form, a count equal to the
**terminal** count. A line that leaves one port in shorthand while writing
another port's bits out is **neither**:

```
N1 a b[0:2] bmix          for   inout [0:4] a;  inout [0:2] b;
```

so it fell through both and bound positionally against the flat terminal list.
Measured on a model whose eight bits each carry a different conductance:

| token | bound to | conductance seen | intended |
|---|---|---|---|
| `a` | `a[0]` | 1 | 1 |
| `b[0]` | `a[1]` | ½ | 1/32 |
| `b[1]` | `a[2]` | ¼ | 1/64 |
| `b[2]` | `a[3]` | ⅛ | 1/128 |

Every node one or more terminals off. The only thing said was Enhancement-402's
warning naming the terminals left over at the tail — the symptom, not the cause.
A user who supplies the two nodes it asks for still has a circuit wired entirely
wrong, and now with no warning at all.

Enhancement-445's diagnostic exists for exactly this mistake —

> *"already carries an index, so it cannot be expanded as the bus port '%s';
> write the bits out individually"*

— but it sits **inside** the port-count check, so it could never reach the line
that needed it. The guard and the failure were one `if` apart.

## Nothing here is ambiguous

The fix does not guess. It walks the ports left to right and lets each token
declare which form it is in:

* a **bare** name on a bus port is shorthand for that port's bits;
* a token **already carrying an index** — or **ground**, which E-445 established
  can never be indexed — means that port was written out, so take one token per
  bit.

`N1 a 0 0 0 bmix` reads correctly under the same rule: shorthand for `a`, three
explicit grounds for `b`.

The rewrite is accepted only when the walk consumes **exactly** the tokens the
line has. The walk is also bounded by that count, because `gettok_instance`
cannot tell where the node tokens end — without the bound, a port claiming more
bits than the line has left would swallow the model name and report against it.

## Where no reading exists, it refuses

If the counts do not reconcile, the bits written do not match the width the model
declares and no reading can repair it. Refusing happens there, where the port and
both counts are still in hand to say so:

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

This replaces a wrong answer, not a working deck. The alternative — warn and bind
anyway — is the shape Enhancement-485 had to go back and undo eight times in one
round: *detect, announce, then use the bad value regardless.*

## One rule, one reader

Deciding the mixed form needs to know whether a token already carries a bit
index, and that question is spelling-dependent: `a[0]` always, `a_0_` only while
`.option autobus=kicad` is on. `subckt.c` already answered it for `.subckt`
formals. A second copy in `inp2n.c` would have been free to disagree about the
KiCad spelling — the two-readers-of-one-rule shape Enhancement-454 had to repair
in this same option — so the rule moved to `INPbusTokenIndexed`, beside
`INPbusBitSuffix`, and `subckt.c` now delegates to it.

## Two smaller fixes in the same option

**`.option autobus=1` reported a style that does not exist.** The style check's
on-word list was `true`/`yes`/`on`; `1` was missing, though it is the mirror of
the `0` in the off-word list and `autobus_enabled` already honours it. The
comment on the early return explains how: *"bare flag, or `=1`: a NUMBER, not a
string"* — true of `set autobus=1`, but a deck `.option autobus=1` card publishes
a **string**, so it reached the check and a perfectly good on-word was reported as
an error. The feature still worked; the message was simply wrong.

**Enhancement-445's own message named a terminal where a port was meant.** Its
caller has only the terminal name to hand, so a port declared `[0:2]` was reported
as *"the bus port 'b[0]'"* — an index the user never wrote and could not act on.
It now names `b`. This is the same defect the new message had in its first draft
and was caught the same way.

## What this deliberately does not change

* **With `.option autobus` off, nothing moves.** The whole path is gated on it, so
  a mixed line still binds positionally and still gets E-402's warning.
* **An all-shorthand line** and **an all-explicit line** take the paths they
  always did; the new branch is an `else` to the first and is only reached when
  the count is between the two.
* **A short line with no shorthand token** — every bit written out, trailing
  terminals omitted — is untouched. That is the `$port_connected` idiom E-402 was
  careful to preserve, and E-402's warning still describes it.
* **E-445's two refusals** still fire on a full-width line, unchanged apart from
  the port name.

## Verification

```
python3 examples/busmixed_examples/verify_busmixed.py    # 46/46
python3 examples/run_regression.py                       # 404/404
```

**20/46** against the pre-fix binary, so **26 of 46 checks discriminate**; the
other twenty are controls that must not move, and do not.


Eighteen further shapes were measured during the survey that preceded this change
and needed no fix: ports of unequal width, descending `[4:0]` and non-zero-based
`[1:5]` ranges, a 16-bit port, three buses of sizes 2/3/4, bus/scalar/bus
interleaving, one token feeding two ports (which superposes exactly), uppercase
tokens, `.option autobus` placed after the instance, two instances in parallel,
`m=` multipliers, all four subcircuit shapes including reversed formals,
`autobus=kicad` on unequal widths, and too-many-nodes as a hard error. A `[0:0]`
port connects correctly in both spellings; its node is named `a` rather than
`a[0]`, which is inherent — at a full token count a width-1 bus is
indistinguishable from a scalar.
