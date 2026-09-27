# Enhancement-743: a current contribution to the implicit ground is a DC path — the `.option dcpath` walk joins an OSDI node whose resistive Jacobian column holds nothing but its own diagonal to ground, so an output stage written as `I(out) <+ (V(out) - y)/rout` is no longer named "without a DC path" and gmin-held

**Scope:** `src/osdi/osdisetup.c` (`OSDIdcpathEdges`: the diagonal-only-column
rule, applied in the resistive walk and in E-595's reactive walk),
`examples/dcpath_examples/` (four modules `gres.va`, `gctl.va`, `gddt.va`,
`pc_gnd.va`; section [12], nine checks). **ngspice only.** Requested by the
user after a discussion of their behavioural models, whose output stages are
written in this form and were being named by the check.

**Suites:** [`dcpath_examples`](../examples/dcpath_examples/) 84 of 84 per
solver, both solvers (77 of 84 on the E-742 binary); `floatnode`,
`silentports`, `groundports`, `oprobust`, `solvercore`, `acgminhold`,
`internalnode`, `singularname` unchanged; full sweep 532 of 532.

## What was wrong

E-575's walk reads an OSDI model's DC edges off its Jacobian pattern. An entry
(i, j) says equation i depends on unknown j; a path between two nodes needs
the symmetric pair a conductance stamps, and "a diagonal joins nothing new".
A voltage contribution `V(out) <+ y` is recognised as a branch to an implicit
ground through its flow unknown. A *current* contribution to that same ground,

```
I(out) <+ (V(out) - y) / rout;
```

the ordinary way to give an output stage a finite output resistance, has no
flow unknown and no second node: ground is not a node of the device, so the
conductance shows only as the diagonal (out, out), and the walk saw nothing
that joins `out` to anything. On a two-line module with a 1 S output stage:

| load on `out` | current form | potential form `V(out) <+ y` |
|---|---|---|
| a capacitor | *no DC path from node 'out'*, gmin installed, held at DC only | silent |
| nothing | *no DC path from node 'out'*, gmin installed | silent |
| the next stage's probed input | both stages' outputs named and held | silent |
| a 1 kΩ resistor | silent, the resistor is the path | silent |

The operating point was exact in every row — the installed 1 pS sits twelve
orders under the model's own conductance — so the harm was the message on
every such instance, and under `.option dcpath=error` a refusal of the deck.
The model form is legitimate Verilog-A; rewriting it to the potential form
makes the output ideal and loses `rout`.

## What changed

The pattern does say where that current goes. The diagonal on a node k is the
sum over k's branches of ∂I/∂V(k); a branch (k, b) whose current depends on
V(k) also puts an entry (b, k) in k's column, because b's equation then
depends on V(k) too. So a resistive diagonal on a *voltage* node whose column
holds no other resistive entry is a conductance whose other end is ground —
there is no device node the V(k)-dependent current could be flowing to. Such
a node is joined to ground, with the same evidence the walk already accepts
from a symmetric pair. `set ngdebug` reports it: *node out: a diagonal and
nothing else in its column -- a conductance to ground*.

The rule is applied with the walk's flag set, so the reactive walk gets it
too: a `ddt()` to ground alone, `I(out) <+ ddt(c*V(out))`, is now a reactive
path — held at DC only and released in tran and ac, as a capacitor to ground
is under E-595 — where it was held in every mode.

What the rule does not touch:

* a controlled current with no dependence on the node's own voltage,
  `I(out) <+ f(V(in))`, has no diagonal and stays unreached: a current source
  alone fixes no voltage;
* a node whose column has other resistive entries stays with the symmetric
  rule, since its diagonal may be nothing but branch shares;
* a terminal the instance line left out: E-719's guard runs after the rule
  and still holds the node, whatever the pattern says, because the model's
  `$port_connected` guard zeroes the row at run time.

## Verification

Section [12] of `verify_dcpath.py`, under both solvers, with the four new
modules compiled in [0]:

| check | result |
|---|---|
| the 1 S output stage driving a capacitor | silent, v(out) = 0.6 to 1e-9, 3 iterations |
| the same with nothing on `out` | silent, 0.6 |
| a chain of two stages (the first drives the second's probed input) | silent, v(c) = 1.2 |
| a cubic ground conductance, v + 0.1 v³ = 0.6 | silent, 0.580444 |
| the deck under `.option dcpath=error` | runs (refused before) |
| a controlled current into ground with no V(out) term, capacitor load | still held and named, released outside DC, v = −I/gmin |
| a `ddt()` to ground alone | held at DC only (held in every mode before), v = I/gmin |
| a guarded ground conductance on a terminal left off the line | still held and named as an unconnected terminal, 3 iterations |
| the same terminal connected to a lone net | silent, its live conductance is the path |

On the E-742 binary seven of the nine fail; the controlled-current and the
open-terminal checks pass there too, since they pin behaviour the rule leaves
as it was. The suite's count moved from 71 to 84 per solver (four compile
checks and nine of section [12]); its README had said 69.

## What this does not do

* A ground conductance beside a branch to another device node — `I(out) <+
  V(out)/r; I(out, n) <+ (V(out) - V(n))/r2` with `n` floating — is still
  named for `out`, because the pattern cannot separate the diagonal's ground
  share from its branch share. The symmetric rule joins `out` to `n`, and the
  pair is reached whenever `n` is.
* The check stays topological, as Spectre's is: a ground conductance whose
  parameter is set to zero at run time is structurally present and is
  trusted, the way a resistor of 1e30 Ω is.
* Nothing changes for built-in devices, which come from E-575's per-type
  tables, or for XSPICE port kinds.
* The potential form `V(out) <+ y` was a path before and still is; nothing
  requires a model to choose one form over the other any more.
