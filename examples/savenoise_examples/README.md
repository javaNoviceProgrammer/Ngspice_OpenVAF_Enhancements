# savenoise_examples — Enhancement-594

`.option saveused` (Enhancement-469) refused every noise analysis with
"no data saved for Noise analysis; analysis not run", and pruned an sp
analysis to nothing of its own: neither plot holds a node, so the inferred
save list could never name their vectors. The option now saves everything for
those two analyses (a `save all` restricted to each, invisible to every
other analysis); a hand-written `save S_2_1` matches the mixed-case vector
the sp analysis publishes; and a second `save all` that differs only in its
analysis restriction is no longer dropped.

Run: `python3 verify_savenoise.py` (built-in devices only; 10 checks).
