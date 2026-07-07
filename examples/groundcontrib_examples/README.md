# groundcontrib_examples — clean diagnostic for a ground contribution (Enhancement-97)

Contributing to a branch that is entirely the `ground` reference
(`V(gnd) <+ ...`) used to **panic** the compiler (an `unreachable!()` in the
MIR lowering). It is now a clean, located `hir_ty` diagnostic ("contribution to
a ground node"). A real node-to-ground branch (`V(a, gnd) <+ ...`) is
unaffected.

`gcontrib.va` is a valid node-to-ground source; the verify drives it
(`v(p) = 1.5`) and confirms `V(gnd) <+ 0` is rejected cleanly (no ICE) while
`V(a, gnd) <+ 1` is not a false positive. Run: `python3 verify_gcontrib.py`
(5 checks).
