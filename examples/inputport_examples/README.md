# inputport_examples — Enhancement-639

A contribution to a port declared `input` is warned: lint **L031
`contribution_to_input_port`** (warn) is the warning LRM 5.6.1 says an
implementation may issue — `input p; … I(p,n) <+ V(p,n)/1k;` used to compile
without a word and drive the port it declared it only reads. Every
contribution form (flow, potential, to ground, through a named branch) is
warned once, naming the port; probes (`V(p,n)`, `I(<p>)`) are not judged and
`inout`/`output` ports are not inputs. The build continues; the statement
attribute `(* openvaf_allow="contribution_to_input_port" *)`, `-A` and `-E`
work as for every lint. No bundled industry model trips it.

Run: `python3 verify_inputport.py` (11 checks per solver, both solvers).

Enhancement-686 (F4 of the 2026-09-21 hunt) adds two checks for lint **L037
`mfactor_double_scaling`** (warn): the LRM's `badres`, the variable route and a noise
contribution are each warned once at the `$mfactor` read (LRM 6.3.6); `parares`, a `?:`
condition, a potential contribution, a display and an opvar stay silent; the allow
attribute and `-A` silence it, `-E` makes it an error, `--lints` lists it as L037.

Enhancement-790 (F7 of the 2026-10-04 openvaf-r hunt) adds three: L037 reports `$mfactor`
carried as a factor — through `* / + -`, a negation, a `**` base, a `?:` arm, a variable and
the operators linear in their first argument (`ddt`, `idt`, `laplace_*`, `zi_*`, `absdelay`,
`transition`, `slew`, `white_noise`, `flicker_noise`) — and no longer any dependence: the CMC
mismatch rule (a sigma divided by `sqrt($mfactor * area)`), an `exp` of it, a user function and
a comparison are silent, and the corpus `r3_cmc` compiles without the ten warnings it drew. On
the E-788 binaries checks [10] and [11] fail.
