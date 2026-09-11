# barevalue_examples — Enhancement-597

A parameter name without a value on an instance line or a `.model` card's
instance default (`n1 a 0 im w=2 m`, `.model im istr w`) was applied as zero in
silence; a bare word straight after the model name was taken as the model and
the card it hid commented out. Now the line is refused and the message names the
parameter, the shape (nothing after the name, a token that is not a number, an
integer that does not fit) and the fix. `istr.va` carries a real, an integer and
a string instance parameter.

Run: `python3 verify_barevalue.py` (21 checks per solver, both solvers).
