# opvarmsg_examples — Enhancement-601

Reading an operating-point variable through the model name answered with the
instance-parameter message ("declared (* type="instance" *) ...") for something
that is not a parameter; a write got "no such parameter" for a name that exists.
The read-only entries of the instance table are named as what they are now, on
the model and on the instance, read and write. And the range refusal shows the
value for an integer (the rounded one) and a string as it did for a real. The
duplicate-plus-alias line closed by Enhancement-597 is pinned here too.

Run: `python3 verify_opvarmsg.py` (10 checks per solver, both solvers).
