# paramcycle_examples — Enhancement 844

[E-844](../../enhancements_doc/Enhancement-844.md), F7 of the
[2026-10-10 robustness and correctness campaign](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

A parameter declared without a type takes the type of its default, so typing a read of it means
inferring that parameter's body. When the body read the parameter itself, in its default or its
range, the inference asked for its own result. A parameter that read a later one which read it
back did the same. openvaf-r died on the query cycle with exit 101 and the crash banner. With a
type, the same reads were already errors: "references itself" (Enhancement-414) and "defined
afterwards". Such a read is now typed as an error, and those messages are what is reported.

- **[1]** `parameter p = p;`, `p = 2*p + 1`, `p = 1 from [0:p]`, `localparam l = l + 1;`,
  `p = q; q = p`, a cycle through an `aliasparam`, and the fuzz's `parameter p p = 1;`: each
  is reported, with exit 65 and no crash.
- **[2]** The typed spellings, reported as before (control).
- **[3]** Untyped parameters that read earlier ones compile and keep their defaults' types:
  an integer chain divides as integers (control).

Run: `python3 verify_paramcycle.py` (12 checks; the 7 in [1] fail on the E-840 compiler).
