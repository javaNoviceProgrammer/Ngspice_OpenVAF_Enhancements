# hiername_examples — $root + hierarchical names (Enhancement-49)

Demonstrates **hierarchical names** — instance paths (`u1.u2.m`), named-block
paths (`outer.inner.w`), and the `$root`-anchored/top-qualified spellings —
plus the **`transition()` real-input fix**, using the committed
`openvaf-r` and `ngspice-46`.

## What was broken

- **References into flattened instances didn't resolve**: `V(u1.m)` / `u1.r`
  failed with "'u1' was not found in the current scope". The E-5 elaboration
  flattens instances into prefixed locals (`u1__m`) but never rewrote
  parent-side references. A token-level path scanner now rewrites instance
  chains (`u1.m`, deep `u1.u2.x`, instance-array `u1[2].m`, and the
  `$root.<top>.`/`<top>.` anchored spellings) to the flattened names,
  composing prefixes segment by segment at every hierarchy level.
- **Nested named-block paths failed**: `outer.inner.w` errored "'w' was not
  found in 'inner'" — after the resolver redirected into a nested block's def
  map, the *final* name lookup still probed the original map (`self.scopes`
  instead of `current_map.scopes`; a one-token aliasing bug).
- **`transition()` rejected real inputs** — its signature table typed the
  input `Integer`, breaking the LRM's canonical comparator (`real vcout; ...
  transition(vcout, td, tr, tf)`). The input is Real per LRM 4.5.7 (integers
  still promote implicitly). The accompanying audit of every builtin
  signature table also caught `DIST_2_ARG_CONST_SEED` typing its middle
  argument Real while its three siblings say Integer.

## Run

```
python3 verify_hiername.py
```

Checks (ALL PASS, exact): a two-level hierarchy (`hier` → `u1` → `u2`) read
through plain, `$root`-anchored and top-qualified paths — hierarchical
parameter + deep net probes sum to 557 exactly; nested named-block paths
(3.75, previously an error); and the LRM comparator compiles and switches
(+1/0 on the sine halves).
