# baregenerate_examples — module-level `generate for` without keywords (Enhancement-96)

A `generate for`/`if`/`case` written at module scope **without** the optional
`generate`/`endgenerate` keywords (the LRM makes them optional) now parses and
elaborates. It used to fail (`unexpected token 'for'`) — or silently drop the
loop when a following analog block let error recovery resync — in two module
shapes: with a header **bus port**, and with **no analog block**.

`baregen.va` has both shapes. The verify drives each and confirms the loop was
actually applied (index-scaled bus currents; a divider bank giving
`i(vp) = -2 mA`, which would be 0 if the loop had been dropped). Run:
`python3 verify_baregen.py` (4 checks).
