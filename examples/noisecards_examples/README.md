# noisecards_examples — Enhancement-603

A noise analysis publishes two plots in sequence -- the spectral densities
(noise1) and the integrated totals (noise2) -- and the save list a `.print
noise ...` card registers was applied to each plot on its own. `.print noise
onoise_spectrum` lost the totals plot ("no data saved for Noise analysis;
analysis not run", after two false "can't parse" warnings); `.print noise
onoise_total` lost the whole analysis, the densities being opened first; and a
card that reached both plots printed "vector ... is not available" from the
plot that did not hold an item. The analysis now tells the front end how many
plots follow: within the sequence a plot the saves do not reach is kept whole,
a saved name is reported missing once and only when no plot held it, and a
`.print` on a type with several plots prints from each plot what it holds.

Run: `python3 verify_noisecards.py` (21 checks per solver, both solvers).
