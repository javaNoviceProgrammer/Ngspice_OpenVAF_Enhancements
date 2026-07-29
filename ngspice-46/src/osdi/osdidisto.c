/* Enhancement-352: distortion (Volterra) analysis for OSDI / Verilog-A devices.
 *
 * ngspice's `.disto` is a Volterra-series analysis: it needs each device's
 * Taylor expansion of I(v) to THIRD order, not just the operating-point
 * linearisation the Jacobian provides. Built-in devices hand-code those
 * coefficients (`diodset.c` computes `id_x2`, `id_x3`, ...), which is why only
 * four of ~58 of them implement DEVdisto at all.
 *
 * Enhancement-359 obtains the coefficients for any Verilog-A model by
 * differencing the model's own analytic Jacobian at the operating point (see
 * osdidistonum.c); nothing is needed from the compiler and no ABI beyond what
 * every OSDI >= 0.4 object already has. This file is the generic consumer --
 * written ONCE, it gives every OSDI model distortion analysis.
 *
 * WHY THERE IS NO 3-VARIABLE CEILING HERE
 * ---------------------------------------
 * ngspice's own framework caps out at three controlling variables: `Dderivs`
 * holds derivatives "w.r.t 3 variables" and the DF* helpers take up to 27
 * scalar arguments with no fourth-variable form. That cap is a property of the
 * hard-coded helpers, not of the mathematics. The Volterra contraction is just
 * a symmetric tensor contraction, so this file performs it directly over
 * however many model inputs the device has, and never calls the D1x/DFx
 * helpers. The formulas below are the N-variable generalisation of exactly
 * those helpers (D1x, DFx) -- see DISTO_VOLTERRA_FORMULATION.md, which records each mode
 * together with its N=1 reduction back to the hard-coded form it must match.
 *
 * CONVENTION
 * ----------
 * OpenVAF emits RAW partial derivatives; the 1/n! and the multinomial
 * multiplicity are applied here (`taylor_c2`/`taylor_c3` below). That keeps the
 * ABI free of a convention a reader would have to infer, and it is checked
 * against `diodset.c`, which stores `g2 = 0.5*gd/vte` = (1/2)d2I/dV2 and
 * `g3 = g2/(3*vte)` = (1/6)d3I/dV3.
 */

#include "ngspice/ngspice.h"

#include "ngspice/cktdefs.h"
#include "ngspice/devdefs.h"
#include "ngspice/distodef.h"
#include "ngspice/sperror.h"

#include "osdi.h"
#include "osdidefs.h"
#include "osdidistonum.h"

/* ------------------------------------------------------------------ complex */
typedef struct { double re, im; } dcomplex;

static inline dcomplex cx(double re, double im)
{
    dcomplex z; z.re = re; z.im = im; return z;
}
static inline dcomplex cadd(dcomplex a, dcomplex b)
{
    return cx(a.re + b.re, a.im + b.im);
}
static inline dcomplex cmul(dcomplex a, dcomplex b)
{
    return cx(a.re * b.re - a.im * b.im, a.re * b.im + a.im * b.re);
}
static inline dcomplex cscale(dcomplex a, double s)
{
    return cx(a.re * s, a.im * s);
}
static inline dcomplex cconj(dcomplex a)
{
    return cx(a.re, -a.im);
}


/* Enhancement-359: the numerical tensors are evaluated at the DC operating
 * point, so they are frequency-independent: built once at D_SETUP and reused by
 * every mode and every frequency.
 *
 * The cache is PER MODEL TYPE, not global. `DEVdisto` is dispatched once per
 * device type (cktdisto.c walks DEVices[]), and every distinct .osdi is its own
 * type -- so a circuit using two Verilog-A models calls this whole routine twice
 * for each mode, D_SETUP included. A single global cache cleared at D_SETUP
 * therefore had the second model wipe the first model's tensors, and every model
 * but the last silently contributed ZERO distortion. That is precisely the
 * quietly-wrong result this feature exists to avoid, so the cache is keyed by
 * descriptor and each model only ever clears its own entries. */
typedef struct { const void *inst; OsdiNumDisto nd; } OsdiNumCacheEnt;

typedef struct {
    const OsdiDescriptor *descr;
    OsdiNumCacheEnt *ent;
    uint32_t n, cap;
} OsdiNumModelCache;

static OsdiNumModelCache *numcaches = NULL;
static uint32_t numcaches_n = 0, numcaches_cap = 0;

static OsdiNumModelCache *numcache_for(const OsdiDescriptor *descr, bool create)
{
    uint32_t i;
    for (i = 0; i < numcaches_n; i++)
        if (numcaches[i].descr == descr)
            return &numcaches[i];
    if (!create)
        return NULL;
    if (numcaches_n == numcaches_cap) {
        numcaches_cap = numcaches_cap ? numcaches_cap * 2 : 8;
        numcaches = TREALLOC(OsdiNumModelCache, numcaches, numcaches_cap);
    }
    numcaches[numcaches_n].descr = descr;
    numcaches[numcaches_n].ent = NULL;
    numcaches[numcaches_n].n = numcaches[numcaches_n].cap = 0;
    return &numcaches[numcaches_n++];
}

/* drop only THIS model's entries */
static void numcache_reset(OsdiNumModelCache *mc)
{
    uint32_t i;
    for (i = 0; i < mc->n; i++)
        osdi_numdisto_free(&mc->ent[i].nd);
    mc->n = 0;
}

static OsdiNumDisto *numcache_push(OsdiNumModelCache *mc, const void *inst)
{
    if (mc->n == mc->cap) {
        mc->cap = mc->cap ? mc->cap * 2 : 32;
        mc->ent = TREALLOC(OsdiNumCacheEnt, mc->ent, mc->cap);
    }
    mc->ent[mc->n].inst = inst;
    memset(&mc->ent[mc->n].nd, 0, sizeof(OsdiNumDisto));
    return &mc->ent[mc->n++].nd;
}

/* kernel of distinct-global-node `k`: in node coordinates the variable IS the
 * node voltage, so there is no hi/lo pair to unpick */
static dcomplex node_kernel(const OsdiNumDisto *nd, uint32_t k,
                            const double *re, const double *im)
{
    uint32_t g = nd->gnodes[k];
    return cx(re[g], im[g]);
}

/* --------------------------------------------------------------- kernels */
/* The kernel of model input `i` at a given harmonic slot: the node difference
 * of that slot's solution vector across the input's node pair. Mirrors what
 * `diodisto.c` does by hand for the diode's single branch voltage. */
static dcomplex input_kernel(const OsdiDescriptor *descr, const uint32_t *node_mapping,
                             uint32_t i, const double *re, const double *im)
{
    uint32_t n1 = descr->inputs[i].node_1;
    uint32_t n2 = descr->inputs[i].node_2;
    uint32_t m1 = (n1 == UINT32_MAX) ? 0 : node_mapping[n1];
    uint32_t m2 = (n2 == UINT32_MAX) ? 0 : node_mapping[n2];
    double r = re[m1] - re[m2];
    double x = im[m1] - im[m2];
    return cx(r, x);
}

/* Taylor coefficient from the RAW partial derivative, folding in 1/n! and the
 * multinomial multiplicity for repeated indices (see the header comment). */
static inline double taylor_c2(double raw, uint32_t a, uint32_t b)
{
    return (a == b) ? 0.5 * raw : raw;
}
static inline double taylor_c3(double raw, uint32_t a, uint32_t b, uint32_t c)
{
    if (a == b && b == c)
        return raw / 6.0;              /* 1/3!            */
    if (a == b || b == c || a == c)
        return 0.5 * raw;              /* multiplicity 3 / 3! */
    return raw;                        /* multiplicity 6 / 3! */
}

/* stamp a complex current into the RHS at the residual row's node, with the
 * sign convention diodisto.c uses */
static inline void stamp(CKTcircuit *ckt, const uint32_t *node_mapping,
                         uint32_t row, dcomplex v)
{
    uint32_t n = node_mapping[row];
    if (n == 0)
        return;                        /* ground row: nothing to stamp */
    ckt->CKTrhs[n] -= v.re;
    ckt->CKTirhs[n] -= v.im;
}

/* ------------------------------------------------------------------ driver */
extern int OSDIdisto(int mode, GENmodel *inModel, CKTcircuit *ckt)
{
    GENmodel *gen_model;
    GENinstance *gen_inst;
    DISTOAN *job = (DISTOAN *)ckt->CKTcurJob;

    OsdiRegistryEntry *entry = osdi_reg_entry_model(inModel);
    const OsdiDescriptor *descr = entry->descriptor;

    /* Enhancement-359: the tensors are differenced from the model's analytic
     * Jacobian at runtime, so all this needs is machinery every OSDI >= 0.4
     * object already has -- eval, the jacobian entry table and the resistive
     * jacobian array. No taylor fields, no version floor, and models compiled
     * before any of this work still get distortion without being recompiled. */
    if (getenv("OSDI_DISTO_DEBUG"))
        fprintf(stderr, "DISTODBG %s mode=%d nodes=%u jac=%u\n",
                descr->name, mode, descr->num_nodes, descr->num_jacobian_entries);

    if (!descr->eval || !descr->write_jacobian_array_resist ||
        descr->num_jacobian_entries == 0 || descr->num_nodes == 0) {
        /* Cannot difference the jacobian, so this device contributes nothing.
         * Registering DEVdisto removed cktdisto.c's blanket warning, so silence
         * here would be the quietly-wrong zero Enhancement-62 added a warning
         * to prevent. Report it, but only when the device looks nonlinear --
         * more jacobian entries than nodes -- so linear models stay quiet. */
        if (mode == D_SETUP && descr->num_jacobian_entries > descr->num_nodes) {
            fprintf(stderr,
                "Warning: Verilog-A (OSDI) device '%s' does not expose the jacobian\n"
                "         array needed for distortion; .disto will NOT include its\n"
                "         nonlinearities.\n",
                descr->name);
        }
        return OK;
    }

    if (mode == D_SETUP) {
        /* Enhancement-359: build the tensors numerically, once per instance.
         * distoan.c has already run CKTop + CKTload here, so CKTrhsOld holds the
         * converged operating point. The flags mirror a DC operating-point eval
         * so the device sees the context it converged in; osdidistonum.c clears
         * the limiter for its own probe steps. Being evaluated at the operating
         * point, the tensors are frequency-independent and every frequency point
         * below reuses them. */
        OsdiNumModelCache *mc = numcache_for(descr, true);
        numcache_reset(mc);
        OsdiSimInfo sim_info = {
            .paras = get_simparams(ckt),
            .abstime = 0.0,
            .prev_solve = ckt->CKTrhsOld,
            .prev_state = ckt->CKTstates[0],
            .next_state = ckt->CKTstates[0],
            .flags = CALC_RESIST_JACOBIAN | CALC_RESIST_RESIDUAL | CALC_OP |
                     CALC_RESIST_LIM_RHS | ENABLE_LIM | ANALYSIS_DC |
                     ANALYSIS_STATIC,
        };
        for (gen_model = inModel; gen_model; gen_model = gen_model->GENnextModel) {
            void *model = osdi_model_data(gen_model);
            for (gen_inst = gen_model->GENinstances; gen_inst;
                 gen_inst = gen_inst->GENnextInstance) {
                void *inst = osdi_instance_data(entry, gen_inst);
                const uint32_t *nmap =
                    (const uint32_t *)(((const char *)inst) + descr->node_mapping_offset);
                OsdiNumDisto *nd = numcache_push(mc, inst);
                osdi_numdisto_build(ckt, descr, gen_inst, inst, model, nmap,
                                    &sim_info, nd);
                if (getenv("OSDI_DISTO_DEBUG"))
                    fprintf(stderr, "DISTODBG build %s K=%u n2=%u n3=%u\n",
                            gen_inst->GENname, nd->K, nd->n2, nd->n3);
            }
        }

        return OK;                     /* coefficients are read per mode below */
    }


    const OsdiNumModelCache *mc = numcache_for(descr, false);
    uint32_t ci = 0;
    for (gen_model = inModel; gen_model; gen_model = gen_model->GENnextModel) {
        void *model = osdi_model_data(gen_model);

        for (gen_inst = gen_model->GENinstances; gen_inst;
             gen_inst = gen_inst->GENnextInstance) {
            void *inst = osdi_instance_data(entry, gen_inst);
            const uint32_t *node_mapping =
                (const uint32_t *)(((const char *)inst) + descr->node_mapping_offset);
            const OsdiNumDisto *nd;

            if (!mc || ci >= mc->n || mc->ent[ci].inst != inst)
                continue;                  /* setup did not cover this instance */
            nd = &mc->ent[ci++].nd;
            if (nd->n2 == 0 && nd->n3 == 0)
                continue;                  /* linear device: nothing to add */

            /* Which kernel slots this mode needs. H1 = f1, H2 = f2 (conjugated
             * for the difference modes), K11 = 2f1, K1m2 = f1-f2. */
            const double *re1 = job->r1H1ptr, *im1 = job->i1H1ptr;
            const double *re2 = job->r1H2ptr, *im2 = job->i1H2ptr;
            const double *reK11 = job->r2H11ptr, *imK11 = job->i2H11ptr;
            const double *reK12 = job->r2H1m2ptr, *imK12 = job->i2H1m2ptr;

            /* Two passes: the resistive tensor, then the reactive one. The
             * reactive result is rotated by j*omega, exactly as diodisto.c does
             * (`temp += -omega*Im(...)`, `itemp += +omega*Re(...)`). */
            uint32_t pass;
            for (pass = 0; pass < 2; pass++) {
                double omega = ckt->CKTomega;
                if (pass == 1u && omega == 0.0)
                    continue;

                uint32_t e;
                /* ---- second-order contributions ---------------------------- */
                for (e = 0; e < nd->n2; e++) {
                    double raw = pass ? nd->t2[e].react : nd->t2[e].resist;
                    if (raw == 0.0)
                        continue;
                    uint32_t row = nd->t2[e].row;
                    uint32_t a = nd->t2[e].c1;
                    uint32_t b = nd->t2[e].c2;
                    double c2 = taylor_c2(raw, a, b);
                    dcomplex acc = cx(0.0, 0.0);

                    switch (mode) {
                    case D_TWOF1: {
                        dcomplex ha = node_kernel(nd, a, re1, im1);
                        dcomplex hb = node_kernel(nd, b, re1, im1);
                        acc = cmul(ha, hb);
                        break;
                    }
                    case D_THRF1: {
                        dcomplex ha = node_kernel(nd, a, re1, im1);
                        dcomplex hb = node_kernel(nd, b, re1, im1);
                        dcomplex ka = node_kernel(nd, a, reK11, imK11);
                        dcomplex kb = node_kernel(nd, b, reK11, imK11);
                        acc = cadd(cmul(ha, kb), cmul(hb, ka));
                        break;
                    }
                    case D_F1PF2:
                    case D_F1MF2: {
                        dcomplex ha = node_kernel(nd, a, re1, im1);
                        dcomplex hb = node_kernel(nd, b, re1, im1);
                        dcomplex ga = node_kernel(nd, a, re2, im2);
                        dcomplex gb = node_kernel(nd, b, re2, im2);
                        if (mode == D_F1MF2) {   /* -f2 -> conjugate */
                            ga = cconj(ga);
                            gb = cconj(gb);
                        }
                        /* The reference halves this: D1nF12 returns
                         * 0.5*S2vF12, and S2vF12 already sums both orderings.
                         * So the mixed-tone 2nd-order response is c*H1*H2, not
                         * 2*c*H1*H2 -- without the 0.5 both f1+f2 and f1-f2 come
                         * out exactly 2x, and the f1-f2 error then propagates
                         * into IM3 through the K1m2 kernel. */
                        acc = cscale(cadd(cmul(ha, gb), cmul(hb, ga)), 0.5);
                        break;
                    }
                    case D_2F1MF2: {
                        dcomplex ha = node_kernel(nd, a, re1, im1);
                        dcomplex hb = node_kernel(nd, b, re1, im1);
                        dcomplex ga = cconj(node_kernel(nd, a, re2, im2));
                        dcomplex gb = cconj(node_kernel(nd, b, re2, im2));
                        dcomplex ka = node_kernel(nd, a, reK11, imK11);
                        dcomplex kb = node_kernel(nd, b, reK11, imK11);
                        dcomplex qa = node_kernel(nd, a, reK12, imK12);
                        dcomplex qb = node_kernel(nd, b, reK12, imK12);
                        acc = cadd(cscale(cadd(cmul(ha, qb), cmul(hb, qa)), 2.0),
                                   cadd(cmul(ga, kb), cmul(gb, ka)));
                        acc = cscale(acc, 1.0 / 3.0);
                        break;
                    }
                    default:
                        continue;
                    }

                    acc = cscale(acc, c2);
                    if (pass == 1u)
                        acc = cx(-omega * acc.im, omega * acc.re);
                    stamp(ckt, node_mapping, row, acc);
                }

                /* ---- third-order contributions ----------------------------- */
                for (e = 0; e < nd->n3; e++) {
                    double raw = pass ? nd->t3[e].react : nd->t3[e].resist;
                    if (raw == 0.0)
                        continue;
                    uint32_t row = nd->t3[e].row;
                    uint32_t a = nd->t3[e].c1;
                    uint32_t b = nd->t3[e].c2;
                    uint32_t c = nd->t3[e].c3;
                    double c3 = taylor_c3(raw, a, b, c);
                    dcomplex acc = cx(0.0, 0.0);

                    switch (mode) {
                    case D_THRF1: {
                        dcomplex ha = node_kernel(nd, a, re1, im1);
                        dcomplex hb = node_kernel(nd, b, re1, im1);
                        dcomplex hc = node_kernel(nd, c, re1, im1);
                        acc = cmul(cmul(ha, hb), hc);
                        break;
                    }
                    case D_2F1MF2: {
                        dcomplex ha = node_kernel(nd, a, re1, im1);
                        dcomplex hb = node_kernel(nd, b, re1, im1);
                        dcomplex hc = node_kernel(nd, c, re1, im1);
                        dcomplex ga = cconj(node_kernel(nd, a, re2, im2));
                        dcomplex gb = cconj(node_kernel(nd, b, re2, im2));
                        dcomplex gc = cconj(node_kernel(nd, c, re2, im2));
                        acc = cadd(cadd(cmul(cmul(ha, hb), gc), cmul(cmul(ha, hc), gb)),
                                   cmul(cmul(hc, hb), ga));
                        acc = cscale(acc, 1.0 / 3.0);
                        break;
                    }
                    default:
                        continue;      /* 3rd order contributes only to 3f1, 2f1-f2 */
                    }

                    acc = cscale(acc, c3);
                    if (pass == 1u)
                        acc = cx(-omega * acc.im, omega * acc.re);
                    stamp(ckt, node_mapping, row, acc);
                }
            }
        }
    }

    return OK;
}
