# arrayport_examples — name-then-range net/port declarations (Enhancement-89)

The unpacked-array form of a vectored net/port (LRM 3.6/3.7, page 45):
`output out[0:3]; electrical out[0:3];` — the name-then-range alternative to
Enhancement-3's range-then-name `output [0:3] out;`. Purely syntactic; a
textual pre-pass normalizes it to the range-then-name form.

`arrayport.va` (`tapbuf`) is the E-3 4-tap buffer re-declared name-then-range;
each output tap out[k] = 0.25*(k+1)*gain*V(in), pinned at runtime. The verify
also checks a name-then-range input port compiles and that the two forms are
equivalent. Run: `python3 verify_arrayport.py` (7 checks).
