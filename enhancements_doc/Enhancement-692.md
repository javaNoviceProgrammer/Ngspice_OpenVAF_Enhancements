# Enhancement-692: the setup no longer walks the node list for every internal node of every OSDI instance — E-690's collapsed-twin test cost instances × internal nodes × circuit nodes, nine seconds before a photonic chip's sweep started

**Scope:** not a hunt finding — reported by the user on version12 right after the E-691
sync ("it will take some time for the simulation to start"). ngspice: `src/osdi/osdisetup.c`
(the deck nodes a collapsed internal node may be bound to are collected once per setup call
and matched to the instances by name; one node fetched per match), `src/osdi/osdiload.c`
(`OSDIuicSeed`: only the instance's residual entries are cleared, not two whole vectors per
instance). `examples/internalnode_examples/` (two checks, 28), `examples/analyses_examples/`
(one check, 37). **ngspice only.**

**Suites:** [`internalnode_examples`](../examples/internalnode_examples/) 28 of 28 per
solver, both solvers (both new checks fail on the E-691 binaries: 1.7–1.9 s and a 13–16×
ratio); [`analyses_examples`](../examples/analyses_examples/) 37 of 37 (the new check pins
the seeding at scale and passes on E-691, whose cost there was a fraction of a second); the
user's chip deck 11.6 s → 2.26 s with identical output (the E-680 build: 2.4 s); full sweep
531 of 531.

## What was wrong

Two loops folded the same morning, both linear per instance in the size of the circuit.

- **E-690's collapsed-twin test.** To bind an analysis-invented `<inst>#<node>` to the node
  the model collapsed it into, `OSDIsetup` looked at every internal node of every OSDI
  instance and fetched its node struct by number with `CKTnum2nod`, which walks the node
  list from its head; for a collapsed one it walked the list again by name. Instances ×
  internal nodes × circuit nodes, at every setup. Sampling the user's run during the pause
  put 85 percent of the samples in `CKTnum2nod` under `OSDIsetup`:

  | deck | E-680 build | E-691 build | this fix |
  |---|---|---|---|
  | the user's chip (wavelength sweep) | 2.4 s | 11.6 s | 2.26 s |
  | 1000 instances of a 40-internal-node module (42k nodes), `op` | — | 1.5 s | 0.06 s |
  | 250 instances of the same | — | 0.11 s | 0.03 s |

- **E-689's seeding pass.** `OSDIuicSeed` cleared two full residual vectors per instance
  before each of its two evaluations, per round: instances × matrix size. 3000 instances
  under `uic`: 0.37 s → 0.17 s. Not what the user hit (the deck has no `uic`), but the same
  shape.

## What changed

- The candidate deck nodes — a parse-time node whose name carries `#` and that no device
  line named, or one bound at an earlier setup — are collected **once per `OSDIsetup` call**
  (one walk of the node list per model type). The set is empty in almost every deck, and
  then the per-instance loop does nothing. When it is not, each candidate is matched to an
  instance by name (`<inst>#`), the suffix looked up among the module's internal nodes, a
  built (adopted) node recognised by its number, and the one node fetched by number is the
  collapse target of a match. Same bindings, same Note, same `sens` re-setup reuse.
- The seeding pass zeroes both vectors once at allocation and, before each evaluation, only
  the entries at the instance's own nodes — the only ones read.

## Verification

| check | result |
|---|---|
| the user's deck (no `uic`, no `.probe`, no internal-node outputs) on the fixed build | 2.26 s; output identical to the E-680 run |
| 1000 instances × 40 internal nodes: the `op` within 1 s, the value right | 0.07 s (E-691: 1.7–1.9 s) |
| four times the instances cost less than eight times the 250-instance run | ratio 2.2 (E-691: 13–16) |
| 3000 seeded instances under `uic`: the Note, every node at 0.5 | pass on both builds |
| E-690's own checks (the collapsed twin as the first command, after an op) | unchanged |
| full sweep | 531 of 531 |

## What this does not do

- `CKTnum2nod` itself stays a linear walk; it is now called once per actual match, which is
  rare.
- E-608's adoption lookup (`INPmkTerm`'s string compare inside `CKTmkSignal`) is the
  pre-existing per-node cost visible in the profile at about half a percent; untouched.
- E-691's explicit-probe pass scans the deck once per explicit probe; untouched.
