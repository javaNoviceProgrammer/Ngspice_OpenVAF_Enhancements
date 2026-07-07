# filemacro_examples — `` `__FILE__ `` / `` `__LINE__ `` (Enhancement-85, F4)

The LRM's predefined source-location macros, previously "macro has not
been declared" errors. `srcloc.va` strobes its location once directly and
once through a `` `define `` body; the verify script pins:

- `` `__FILE__ `` expands to the file's **basename** (the expansion is
  baked into the compiled `.osdi`, so it must stay machine-portable);
- `` `__LINE__ `` at the direct use reports that exact line;
- a use inside a `` `define `` body reports the **definition site**
  (textual pre-pass semantics — documented deviation from C-style
  line-of-use).

Run: `python3 verify_filemacro.py` (5 checks).
