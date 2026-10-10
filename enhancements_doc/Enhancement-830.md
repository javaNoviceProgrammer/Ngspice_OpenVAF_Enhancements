# Enhancement-830: E-543's BJT limiting needs a polarity parameter, not only terminals named c, b, e

**Scope:** F14 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `osdi/osdiload.c`: `osdi_lim_apply` leaves a module of the BJT family without simulator-side
  limiting unless it has a parameter `type`.
- `set osdilim_verbose` says so.

`examples/limfinal_examples/` (section [2], four checks). **ngspice only.**

**Suites:** [`limfinal_examples`](../examples/limfinal_examples/) 14 of 14 per solver (3 of the
4 checks in [2] fail on the E-828 binaries; the fourth is the control with `type`).
[`osdilimit_examples`](../examples/osdilimit_examples/) and
[`opamp741_examples`](../examples/opamp741_examples/), whose `bjt741` module is limited, are
unchanged. The full sweep, 546 of 546.

## What was wrong

Enhancement-543 gives an OSDI module the built-ins' Newton limiting when its terminals read
like a MOSFET's (`d,g,s[,b]`) or a BJT's (`c,b,e[,s]`), and its model does not call `$limit`.
A *linear* three-terminal resistor network was enough:

```verilog
module rnet(c, b, e);
  analog begin I(c,b) <+ V(c,b)/1k; I(b,e) <+ V(b,e)/1k; I(c,e) <+ V(c,e)/10k; end
endmodule
```

With `vc c 0 100` and `rb b 0 1meg`:

| | op iterations | gmin stepping | v(b) |
|---|---|---|---|
| default | **577** | dynamic gmin stepping | 49.975 V |
| `.option noosdilim` | 3 | none | 49.975 V |

`DEVpnjlim` limits a junction voltage to a few thermal voltages per step above its critical
voltage. On a non-junction 50 V away it crawls. A transient of a 0 → 100 V pulse took 40 %
more Newton iterations. The answer was right; a large circuit of such modules could fail to
converge.

## The change

A transistor model names its polarity. The corpus BJTs do: MEXTRAM's `TYPE`, HICUM's `type`,
and `bjt741` in `opamp741_examples`, which E-543's limiting does reach. The limiter already
reads that parameter for the type-normalized frame (`lim_type_param`). A module of the BJT
family without one now gets no simulator-side limiting. With `set osdilim_verbose` it is
reported once:

```
no simulator-side limiting: its terminals are a BJT's (c,b,e[,s]) but it has no polarity
parameter `type`, the mark of a transistor model
```

The MOSFET family is unchanged. Its linear twin, a `d,g,s,b` resistor network, cost 6
iterations against 3.

## The checks

`limfinal_examples` [2]:
- The linear `c,b,e` network, op at 100 V: the iteration count of `.option noosdilim` (3), no
  gmin stepping, v(b) = 49.975 V (was 577).
- `set osdilim_verbose` gives the reason.
- The same network with `parameter integer type = 1` (control): still given the BJT limiting.
- A 0 → 100 V pulse through the network: the transient's Newton iterations equal the
  `noosdilim` run's (were 40 % more).

## Limits

- The rule is still a name: a linear `c,b,e` module that declares `type` is limited, and a BJT
  module without `type` is not. Such a model can call `$limit` itself, which E-543 always
  respects.
