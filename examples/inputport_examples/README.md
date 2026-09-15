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

Run: `python3 verify_inputport.py` (6 checks per solver, both solvers).
