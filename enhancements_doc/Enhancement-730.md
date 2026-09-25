# Enhancement-730: under `.option autobus` a line with fewer tokens than ports feeds the leading ports, a bus port in shorthand expanding to its bits, and leaves the trailing terminals absent — `N1 a busdev` had bound the bare `a` as a scalar node onto the terminal `a[0]`, so the deck's `a[0]` drove nothing the device touched and E-402 named four bits of the very port the token stands for as absent; a written-out multi-bit port followed by the tokens running out stays E-490's refusal

**Scope:** F2 of the
[five-options dig of 2026-09-25](../docs/bug_hunts/2026-09-25_five-options-dig.md).
**ngspice only.** `src/spicelib/parser/inp2n.c` (`INP2N`: the port walk of
[E-490](Enhancement-490.md) runs for fewer tokens than ports too; `written_multi`; the
acceptance of a walk whose tokens ran out at a port boundary).
[`examples/autobus_examples/`](../examples/autobus_examples/) (section E-730, 7 checks,
19 per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt page.

**Suites:** `autobus` 19 of 19 per solver, both solvers (15 of 19 on the E-728
binaries); `busmixed` 46 of 46, `busmix` 13 of 13, `busname` 30 of 30, `busportsub` 9 of
9, `subbus` 16 of 16, `autobusopt` 27 of 27, `silentports` 24 of 24, `groundports` 59 of
59, `portconnected`, `autoopts` 43 of 43 unchanged; no new build warnings; full sweep,
run alone.

## What was wrong

`busdev` has the ports `a[0:4]` and `b`; under `.option autobus`, `V1 a[0] 0 1` and

```
N1 a busdev
```

gave `i(v1) = 0` and

```
Warning: instance n1: 5 of the 6 terminals of model type 'busdev' are not connected.
         terminal 2 ('a[1]') is absent  …  terminal 6 ('b') is absent
Warning: no DC path from node 'a' to ground; gmin (1e-12 S) installed to provide one
```

The shorthand of [E-444](Enhancement-444.md) fires on a token count equal to the port
count; E-490's walk, which lets each token say which form it is in, ran for more tokens
than ports; the one-bit trap of [E-572](Enhancement-572.md) covers a count equal to
the terminal count. A line with *fewer* tokens than ports — the `$port_connected`
shape of [E-402](Enhancement-402.md), a trailing port left absent, with the bus in
shorthand — matched none of them and fell through to positional binding, where a
bracket-free token on a bus port is just a name: `a` was bound as the scalar node `a`
onto the terminal `a[0]`, a different node from the deck's `a[0]`, and the warning
listed four bits of the port the token names.

## What changed

**The walk runs for fewer tokens than ports as well.** The tokens feed the leading
ports left to right as E-490 reads them — a bare name on a bus port stands for its
bits, an indexed token or ground means the port is written out and takes one token per
bit — and when the tokens run out at a port boundary with no multi-bit port written out
before, the rewrite is accepted for the terminals it fed and the trailing terminals are
absent, as on any short line. E-402 then names them:

```
N1 a busdev          ->  a[0] a[1] a[2] a[3] a[4], b absent
N1 a b bustwo        ->  a[0] a[1] b[0] b[1] b[2], c absent
Warning: instance n1: 1 of the 6 terminals of model type 'busdev' are not connected.
         terminal 6 ('b') is absent
```

`.option silentports=ground` grounds the absent terminal as it does for any short
line. A line with no shorthand (`N1 a[0] a[1] bustwo`) is left to positional binding
as before; with the option off nothing changes, the shorthand being opt-in.

**A written-out multi-bit port and then the tokens running out stays E-490's refusal**
("the reading runs out before every port is fed"). `N1 a b[0] b[1] b[2] bustwo`, with
`c` absent, reads exactly like `N1 a b[0] b[1] c bustwo` to the walk, whose `c` is
swallowed as `b[2]` — the misbinding E-490 exists to stop — and the two cannot be told
apart. Write every bus port the same way: `N1 a b bustwo` says the same thing in
shorthand.

## Verification

`autobus` section E-730: `N1 a busdev` with `b` absent and grounded by `silentports`
reads `i(v1) = −1e-3`, equal to the written-out `a[0] … a[4]` (0 on the E-728 binaries,
`a` a scalar node); without `silentports` E-402 names `b` alone, not the bits of `a`,
and no "no DC path from node 'a'" is printed; `N1 a b bustwo` with `c` absent reads as
the written-out five bits and E-402 names `c` alone; `N1 a b[0] b[1] b[2] bustwo` is
still refused with "runs out before every port is fed"; `N1 a[0] a[1] bustwo` is bound
positionally with the four absent named; with the option off `N1 a busdev` is the
positional short line it always was. Four of the seven fail on the E-728 binaries.

By hand: the hunt's harness A [A9] decks on both binaries, and the same with
`silentports=ground`; `N1 a[0] a[1] b bustwo`; the eleven suites; the sweep.

## What this does not do

- `N1 a[0] a[1] b bustwo` — three tokens for three ports, the first already indexed —
  is [E-445](Enhancement-445.md)'s case, not this one: the shorthand reading is refused
  with "already carries an index, so it cannot be expanded as the bus port 'a'; write
  the bits out individually", and the line is then bound positionally, `b` onto
  `b[0]`, with E-402 naming `b[1]`, `b[2]` and `c`. It is warned twice and unchanged
  here.
- A written-out port that is short of bits is still not read as a partial port: the
  walk takes one token per bit, so a bare token in a bit position is a bit's node name,
  as it is positionally.
- Nothing changes without the option, or on a line with as many tokens as terminals.
