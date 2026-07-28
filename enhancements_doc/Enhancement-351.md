# Enhancement-351 — `sens` no longer kills ngspice on an OSDI model with an internal node

```
ngspice -> sens v(out)
Internal Error: node allocation in DEVsetup() during sensitivity analysis,
this will cause serious troubles !, please report this issue !
ERROR: fatal error in ngspice, exit(1)
```

Any OSDI model carrying an internal node did this. That is not an exotic
category: **every production compact model has one** — BSIM, HICUM, PSP and EKV
all allocate internal nodes for their terminal resistances. So `.sens` was
effectively unusable with real Verilog-A models, and it failed by taking the
session down rather than refusing.

---

## How it was found

A campaign built on the observation that the previous OSDI sweep (83/83 clean)
was lopsided: 40 `dc` and 22 `ac` checks against only 2 `sens`, 2 `disto` and 4
`pz`. Those thin three are exactly where an OSDI device is most likely to differ
from a built-in, because they do not merely solve the circuit — they consume the
**derivatives** the model hands back.

The new campaign ran three axes: OSDI vs the equivalent built-in on both
solvers, Sparse vs KLU on the same OSDI deck, and repeat-invariance. It came
back **181/184**, and all three failures were the same bug, on the one model in
the set with an internal node.

## The cause

`cktsens.c` re-invokes every model's `DEVsetup()` to stamp the perturbation
matrix, and requires that doing so allocate no nodes:

```c
CKTnode* node = ckt->CKTlastNode;
fn(delta_Y, sg->model, ckt, &ckt->CKTnumStates);
if (node != ckt->CKTlastNode) {
    fprintf(stderr, "Internal Error: node allocation in DEVsetup() ...");
    controlled_exit(EXIT_FAILURE);
}
```

The requirement is reasonable, and every built-in device meets it by guarding
its allocation on *"not already allocated"*. The inductor is the clearest case:

```c
if (here->INDbrEq == 0) {                       /* indsetup.c */
    error = CKTmkCur(ckt, &tmp, here->INDname, "branch");
    here->INDbrEq = tmp->number;
}
```

and `INDunsetup()` sets `INDbrEq = 0` again, so the guard is armed for the next
real setup. **OSDI had no such guard.** Its setup called `CKTmkVolt`/`CKTmkCur`
for each internal node unconditionally, so the second call — the one `sens`
makes on a circuit that is still set up — allocated a fresh set and tripped the
check.

The check was right. It was firing on a real inconsistency, and the defect is
upstream of it.

## The fix

The same idiom the built-ins use. Each instance now records the node numbers its
internal nodes were given, and a later setup reuses them:

```c
bool reuse_nodes = (extra_inst_data->int_node_ids != NULL &&
                    extra_inst_data->int_node_count == num_nodes);
...
if (reuse_nodes) {
    node_ids[i] = extra_inst_data->int_node_ids[i];
    continue;
}
```

`OSDIunsetup()` deletes those nodes, so it also clears the record — the OSDI
counterpart of `INDunsetup()` zeroing `INDbrEq`. Without that, a genuine
re-setup after teardown would hand out numbers for nodes that no longer exist;
the example asserts a `reset` → `sens` → `reset` cycle explicitly for it.

Reuse is conditional on the node **count** matching, because node collapsing
depends on parameters that `alter` can move; if it changes, the record is
dropped and the nodes are allocated afresh.

## Not merely non-fatal — correct

The risk in a fix like this is making the analysis *run* while returning
nonsense. Two independent checks, because "it no longer crashes" proves nothing:

An internal-node model (`os_rs`, r=3000 + rs=10) and a plain one (`os_plain`,
r=3010) are the **same circuit** — the operating points agree to 14 digits. Their
sensitivity to the shared built-in `R1` must therefore be identical, and is:

| | `r1` = d v(out)/dR1 |
|---|---|
| internal-node model | `-1.8718770344518e-04` |
| no-internal-node model | `-1.8718770344518e-04` |
| closed form `-RL/(R1+RL)²` | `-1.87187890622571e-04` |

Identical to every printed digit between the two decks, and within 1e-6 of
closed form — that residue being the sensitivity method's own perturbation step,
not the fix. The model's own parameter agrees too: `n1_r = 6.21886087563079e-05`
against a closed form of `6.21886679809205e-05`.

## Verification

| | |
|---|---|
| campaign (OSDI x analyses x solvers x repeat) | **184/184**, from 181/184 |
| `sens` on an internal-node model | completes on **both** solvers |
| sensitivities vs an equivalent deck | identical; and match closed form |
| `sens` twice in one session | 41 values, bit-identical |
| `reset` → `sens` → `reset` | operating point returns to `7.50623441396507e-01` |
| every other analysis on the same model | 7/7 unaffected |
| regression | 283/283 |

`examples/osdisens_examples/` is a proven trigger: on the pre-fix binary **5 of
its 7 checks fail**, and the two that pass are precisely the ones that should —
the model without an internal node, and the analyses other than `sens`.
