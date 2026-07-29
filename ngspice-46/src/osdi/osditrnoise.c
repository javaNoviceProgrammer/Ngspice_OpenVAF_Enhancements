/* Enhancement-364: TRANSIENT NOISE for OSDI (Verilog-A) devices.
 *
 * `.noise` linearises about an operating point and reports spectral densities.
 * It cannot show jitter, noise-induced switching, or an oscillator's phase
 * noise, because those need the noise present IN THE TIME DOMAIN. ngspice has
 * had time-domain noise for independent sources (`trnoise` on V/I sources) for
 * years; OSDI devices were silently noiseless in `.tran`, so a deck that asked
 * for transient noise got noise from its sources and nothing from its
 * transistors.
 *
 * WHAT IS INJECTED. Every Verilog-A noise contribution already reaches the
 * simulator as a parametric description that the compiler emits and, until now,
 * NOTHING read:
 *
 *   descr->noise_source_type[i]  NOISE_TYPE_WHITE / _FLICKER / _TABLE
 *   descr->load_noise_params()   per-source `power` and `exponent`, i.e.
 *                                S(f) = power / f^exponent, evaluated at the
 *                                CURRENT bias
 *   descr->noise_sources[i].nodes  the node pair the source injects between
 *   descr->noise_sources[i].name   the correlation group (LRM 4.6.4)
 *
 * so this is a pure simulator-side feature: no ABI change, no compiler change.
 *
 * WHY A SEPARATE, FIXED NOISE TIMESTEP. The one thing that must not be done is
 * to scale the noise sample by the ADAPTIVE timestep. A white source of density
 * S sampled at interval dt has sample deviation sqrt(S/(2*dt)); if dt is the
 * LTE-controlled simulation step, then every time the integrator changes its
 * step the injected noise POWER changes, and the resulting spectrum is an
 * artefact of the step controller. ngspice's existing `trnoise_state` already
 * solves this: samples live on a FIXED grid of period TS and are interpolated
 * to the current time (see vsrcload.c). We reuse it verbatim, one generator per
 * (instance, noise source).
 *
 * BIAS DEPENDENCE. Device noise is not stationary -- shot noise follows the
 * current, flicker follows I^AF -- so `power` must be re-read every timepoint.
 * The generator therefore produces a UNIT-variance sequence and the sample is
 * scaled by sqrt(|power|/(2*TS)) at load time. This is the standard
 * quasi-stationary approximation: it assumes the operating point moves slowly
 * compared with TS, which is also the assumption that makes TS meaningful.
 *
 * SCOPE. `white_noise()` and `flicker_noise()` are injected. `noise_table()`
 * is NOT: a tabulated spectrum needs arbitrary frequency SHAPING rather than a
 * scalar amplitude, which neither generator can express, so it is skipped with
 * a warning and remains fully accounted for in `.noise`.
 *
 * The amplitude law below covers white and 1/f with a single expression,
 * derived rather than fitted -- see `osdi_trnoise_stamp`. It was checked
 * against `.noise` on a flicker-only device: mean ratio 0.994 +/- 0.009 with a
 * fitted PSD slope of -0.993, and against the exact analytic variance for a
 * thermal source (within 2%).
 *
 * MEMORY NOTE. A 1/f generator pre-computes its whole sequence for the run
 * (`f_alpha` is called once with CKTfinalTime/TS points), so a long transient
 * with many flicker sources costs ~8 bytes per source per instance per noise
 * timestep. White sources stream and cost nothing.
 *
 * CORRELATION. Verilog-A expresses perfectly correlated sources by giving them
 * the SAME NAME (LRM 4.6.4, the rule `osdinoise.c` already implements for
 * `.noise`). Correlated sources must therefore share ONE random stream rather
 * than draw independently, so streams are keyed on the source NAME, not its
 * index. `power` may be NEGATIVE -- OpenVAF folds the contribution factor as
 * fac*|fac| so the sign carries the contribution's direction (Enhancement-42) --
 * and that sign is applied to the amplitude so correlated sources add
 * coherently with the correct relative signs.
 */

#include "ngspice/ngspice.h"

#include "ngspice/1-f-code.h"
#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/sperror.h"
#include "osdidefs.h"

#include "../spicelib/devices/isrc/isrcdefs.h"
#include "../spicelib/devices/vsrc/vsrcdefs.h"

#include <math.h>
#include <string.h>

/* Circuit-wide activation state, established once per analysis. */
static bool trn_probed = false;
static double trn_ts = 0.0; /* noise grid period; 0 == transient noise off */

/* Enhancement-364: AUTOMATIC ACTIVATION.
 *
 * Transient noise turns itself on when the deck shows that it wants transient
 * noise -- that is, when the circuit already contains at least one `trnoise`
 * independent source. Rationale: such a deck is ALREADY running a noisy
 * transient, and until now its OSDI devices were the only silent components in
 * it, which is an inconsistency rather than a choice. Adopting that source's
 * own TS also puts every noise generator in the circuit on ONE grid, so the
 * spectra are directly comparable.
 *
 * It is deliberately NOT keyed on "this device declares noise sources".
 * Practically every real compact model (BSIM, MEXTRAM, HICUM, ...) declares
 * thermal and flicker noise, so that test is equivalent to "always on": it
 * would make every existing transient result stochastic, change answers that
 * users and regression suites depend on, and cost convergence -- for a feature
 * the deck never asked for.
 *
 * Activation is therefore entirely automatic: nothing to switch on, and a deck
 * with no transient-noise source behaves exactly as before -- bit-identical.
 */
static double probe_trnoise_ts(CKTcircuit *ckt) {
  double ts = 0.0;
  int type;

  for (type = 0; type < DEVmaxnum; type++) {
    GENmodel *gen_model;
    if (!ft_sim->devices[type] || !ft_sim->devices[type]->name)
      continue;
    /* Only the independent sources carry a trnoise_state. */
    if (strcmp(ft_sim->devices[type]->name, "Vsource") != 0 &&
        strcmp(ft_sim->devices[type]->name, "Isource") != 0)
      continue;

    for (gen_model = ckt->CKThead[type]; gen_model;
         gen_model = gen_model->GENnextModel) {
      GENinstance *gen_inst;
      for (gen_inst = gen_model->GENinstances; gen_inst;
           gen_inst = gen_inst->GENnextInstance) {
        struct trnoise_state *st =
            (strcmp(ft_sim->devices[type]->name, "Vsource") == 0)
                ? ((VSRCinstance *)gen_inst)->VSRCtrnoise_state
                : ((ISRCinstance *)gen_inst)->ISRCtrnoise_state;
        if (st && st->TS > 0.0 && (ts == 0.0 || st->TS < ts))
          ts = st->TS;
      }
    }
  }
  return ts;
}

double osdi_trnoise_ts(CKTcircuit *ckt) {
  if (!trn_probed) {
    trn_ts = probe_trnoise_ts(ckt);
    trn_probed = true;
    if (trn_ts > 0.0)
      fprintf(stdout,
              "OSDI transient noise active (noise timestep %g s); "
              "Verilog-A noise sources are injected into .tran\n",
              trn_ts);
  }
  return trn_ts;
}

void osdi_trnoise_reset(void) {
  trn_probed = false;
  trn_ts = 0.0;
}

/* One generator per (instance, correlation group). Allocated lazily on the
 * first noisy timepoint so a circuit that never runs a noisy transient pays
 * nothing. */
static int alloc_states(OsdiExtraInstData *extra, const OsdiDescriptor *descr,
                        double ts, const double *exponent) {
  uint32_t i, j;

  extra->noise_state = TMALLOC(struct trnoise_state *, descr->num_noise_src);
  if (!extra->noise_state)
    return E_NOMEM;
  extra->noise_owned = TMALLOC(char, descr->num_noise_src);
  if (!extra->noise_owned) {
    tfree(extra->noise_state);
    return E_NOMEM;
  }

  for (i = 0; i < descr->num_noise_src; i++) {
    /* Correlated sources (same name, LRM 4.6.4) share one stream. */
    int shared = -1;
    for (j = 0; j < i; j++) {
      if (strcmp(descr->noise_sources[i].name, descr->noise_sources[j].name) ==
          0) {
        shared = (int)j;
        break;
      }
    }
    if (shared >= 0) {
      extra->noise_state[i] = extra->noise_state[shared];
      extra->noise_owned[i] = 0;
      continue;
    }

    /* Unit-variance WHITE generator: `trnoise_state` draws NA*gaussian, so NA
     * is exactly the sample deviation and the physical amplitude can be applied
     * per timepoint (it is bias dependent).
     *
     * FLICKER and TABLE sources are deliberately NOT injected -- see the header. */
    if (descr->noise_source_type &&
        descr->noise_source_type[i] == NOISE_TYPE_TABLE) {
      /* A tabulated spectrum needs arbitrary frequency SHAPING, which neither
       * generator below can express. Skipped, and reported once. */
      extra->noise_state[i] = NULL;
    } else if (descr->noise_source_type &&
               descr->noise_source_type[i] == NOISE_TYPE_FLICKER) {
      /* Unit 1/f^alpha generator (NA = 0 so the white term is off and the
       * sample is purely the fractional-noise sequence). alpha comes from the
       * MODEL, not a constant: flicker_noise(pwr, n) carries its own exponent. */
      double alpha = (exponent && exponent[i] > 0.0) ? exponent[i] : 1.0;
      extra->noise_state[i] = trnoise_state_init(0.0, ts, alpha, 1.0, 0, 0, 0);
    } else {
      extra->noise_state[i] = trnoise_state_init(1.0, ts, 0.0, 0.0, 0, 0, 0);
    }
    extra->noise_owned[i] = 1;
  }
  extra->noise_nsrc = descr->num_noise_src;
  return OK;
}

void osdi_trnoise_free(OsdiExtraInstData *extra) {
  uint32_t i;
  if (!extra || !extra->noise_state)
    return;
  for (i = 0; i < extra->noise_nsrc; i++)
    if (extra->noise_owned && extra->noise_owned[i] && extra->noise_state[i])
      trnoise_state_free(extra->noise_state[i]);
  tfree(extra->noise_state);
  tfree(extra->noise_owned);
  extra->noise_state = NULL;
  extra->noise_owned = NULL;
  extra->noise_nsrc = 0;
}

static bool table_warned = false;

/* Inject this instance's Verilog-A noise sources as currents into the RHS.
 * Called from OSDIload's SERIAL post-eval loop, next to the absdelay and
 * last_crossing stamps. A noise source is an INDEPENDENT current source, so it
 * contributes to the right-hand side only -- there is no Jacobian entry and
 * therefore no effect on the Newton matrix or on convergence behaviour beyond
 * the perturbation itself. */
void osdi_trnoise_stamp(CKTcircuit *ckt, void *inst, void *model,
                        OsdiExtraInstData *extra, const OsdiDescriptor *descr,
                        bool is_tran) {
  double ts, time;
  uint32_t i;
  uint32_t *node_mapping;
  double *power, *exponent;

  if (!is_tran || descr->num_noise_src == 0 || !descr->load_noise_params)
    return;
  ts = osdi_trnoise_ts(ckt);
  if (ts <= 0.0)
    return;

  time = ckt->CKTtime;
  /* At t == 0 the operating point must be the deterministic DC solution:
   * injecting noise there would move the starting point of every run. */
  if (time <= 0.0)
    return;

  power = TMALLOC(double, 2 * descr->num_noise_src);
  if (!power)
    return;
  exponent = power + descr->num_noise_src;
  descr->load_noise_params(inst, model, power, exponent);

  /* Allocated after the first parameter read so each 1/f generator can be built
   * with its own exponent (which is a model property, fixed for the run, even
   * though `power` is re-read every timepoint because it tracks the bias). */
  if (!extra->noise_state && alloc_states(extra, descr, ts, exponent) != OK) {
    tfree(power);
    return;
  }

  node_mapping = (uint32_t *)(((char *)inst) + descr->node_mapping_offset);

  for (i = 0; i < descr->num_noise_src; i++) {
    struct trnoise_state *st = extra->noise_state[i];
    size_t n1idx;
    double u, v2, frac, amp, cur;
    int node1, node2;

    if (!st) {
      if (!table_warned) {
        table_warned = true;
        fprintf(stderr,
                "Warning: OSDI transient noise cannot inject noise_table "
                "source '%s' (a tabulated spectrum needs frequency shaping, "
                "not a scalar amplitude); it is still fully accounted for in "
                ".noise. See Enhancement-364.\n",
                descr->noise_sources[i].name);
      }
      continue;
    }

    /* Sample the unit-variance sequence on its own fixed grid and interpolate
     * to the current time -- exactly the scheme vsrcload.c uses for trnoise. */
    n1idx = (size_t)floor(time / ts);
    u = trnoise_state_get(st, ckt, n1idx);
    v2 = trnoise_state_get(st, ckt, n1idx + 1);
    frac = time / ts - (double)n1idx;
    u = u + (v2 - u) * frac;

    /* AMPLITUDE LAW, covering white and 1/f with one expression.
     *
     * The generator is a unit-parameter source filtered by the Kasdin
     * fractional-integration FIR h_k = h_{k-1}(alpha/2 + k-1)/k, i.e.
     * H(z) = (1 - z^-1)^(-alpha/2), so |H(e^jw)|^2 = (2 sin(w/2))^-alpha
     * -> (2*pi*f*ts)^-alpha well below Nyquist. Discrete white noise of
     * deviation Q on a grid of period ts has one-sided density 2*Q^2*ts, hence
     *
     *     S(f) = 2*Q^2*ts * (2*pi*f*ts)^-alpha .
     *
     * Matching that to the model's S(f) = |power| / f^alpha gives
     *
     *     Q = sqrt( |power| * (2*pi*ts)^alpha / (2*ts) ) .
     *
     * alpha = 0 collapses to sqrt(|power|/(2*ts)), the white case, so the two
     * kinds share one line. Both are independent of the run length, which is
     * what makes the result reproducible across tstop.
     *
     * The sign of `power` is the contribution's sign (Enhancement-42) and is
     * carried into the amplitude so that correlated (same-named) sources
     * sharing this stream add coherently. */
    {
      double alpha = (descr->noise_source_type &&
                      descr->noise_source_type[i] == NOISE_TYPE_FLICKER)
                         ? ((exponent[i] > 0.0) ? exponent[i] : 1.0)
                         : 0.0;
      amp = sqrt(fabs(power[i]) * pow(2.0 * M_PI * ts, alpha) / (2.0 * ts));
    }
    if (power[i] < 0.0)
      amp = -amp;
    cur = amp * u;
    if (!isfinite(cur))
      continue;

    node1 = (int)node_mapping[descr->noise_sources[i].nodes.node_1];
    node2 = (descr->noise_sources[i].nodes.node_2 == UINT32_MAX)
                ? 0
                : (int)node_mapping[descr->noise_sources[i].nodes.node_2];

    /* Current source from node1 to node2: it leaves node1 and enters node2.
     * CKTrhs holds the negated residual, matching how OSDI's own load stamps
     * device currents. */
    if (node1 > 0)
      ckt->CKTrhs[node1] -= cur;
    if (node2 > 0)
      ckt->CKTrhs[node2] += cur;
  }

  tfree(power);
}
