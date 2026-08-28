/**********
Enhancement-155: RC network reduction (TICER) for post-layout parasitics.

  reduce <fmax> [factor <f>] [file <fname>] [name <subckt>] [keep <node> ...]

Reduces the circuit's linear R/C network to a small, electrically equivalent one
that preserves the port behaviour over DC..<fmax>, by eliminating interior RC-only
nodes (TICER Schur-complement elimination, kept realizable as R's and C's). Ports
(nodes to keep) are auto-detected as every node touched by a non-R/C device, plus
ground and any user-named `keep` nodes. Writes a `.subckt` of R's and C's.

Engine: spicelib/analysis/rcreduce.c (CKTreduceRC).
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/fteext.h"
#include "ngspice/wordlist.h"
#include "ngspice/cpextern.h"

#include "circuits.h"
#include "com_reduce.h"

static double rednum(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}

static int red_node(CKTcircuit *ckt, const char *name)
{
    int numNames = 0, i, num = 0;
    IFuid *nameList = NULL;
    if (CKTnames(ckt, &numNames, &nameList) != OK || !nameList)
        return 0;
    for (i = 0; i < numNames; i++)
        if (nameList[i] && strcmp((const char *) nameList[i], name) == 0) { num = i + 1; break; }
    tfree(nameList);
    return num;
}

void
com_reduce(wordlist *wl)
{
    CKTcircuit *ckt;
    double fmax, factor = 5.0;
    const char *fname = "reduced.sp", *subname = "reduced";
    int keep[256], nkeep = 0, r, maxdeg = 12;
    wordlist *w;

    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "Error: reduce: there is no circuit loaded.\n");
        return;
    }
    ckt = ft_curckt->ci_ckt;

    if (!wl || !wl->wl_word) {
        fprintf(cp_err, "Usage: reduce <fmax> [factor <f>] [maxdeg <d>] [file <fname>] "
                        "[name <subckt>] [keep <node> ...]\n");
        return;
    }

    /* Enhancement-502: the `<= 0.0` test caught 0, a negative band and junk --
     * and admitted NaN and inf, because every comparison with NaN is false and
     * inf is genuinely > 0. Either one then made every TICER time constant
     * compare false, so nothing was eliminated: `reduce nan` reported
     * "26 nodes -> 26 nodes (1.0x)" and wrote a file called reduced.sp that
     * reduced nothing, with no error and no hint that the band was the problem. */
    if (!ft_argpos("reduce", "<fmax> (band of interest, Hz)", wl->wl_word, &fmax))
        return;

    for (w = wl->wl_next; w; w = w->wl_next) {
        const char *k = w->wl_word;
        if (strcasecmp(k, "factor") == 0 && w->wl_next) {
            /* Enhancement-502: `factor nan` left the comparison false and
             * reduced nothing; `factor 0` and `factor -2` were clamped up to
             * 1.0 and reduced MORE aggressively than the default (13.0x against
             * 8.7x) -- in silence, in both directions. */
            if (!ft_argpos("reduce", "factor", w->wl_next->wl_word, &factor))
                return;
            w = w->wl_next;
        } else if (strcasecmp(k, "maxdeg") == 0 && w->wl_next) {
            if (!ft_argcount("reduce", "maxdeg", w->wl_next->wl_word, 3, 100000, &maxdeg))
                return;
            w = w->wl_next;
        } else if (strcasecmp(k, "file") == 0 && w->wl_next) {
            fname = w->wl_next->wl_word; w = w->wl_next;
        } else if (strcasecmp(k, "name") == 0 && w->wl_next) {
            subname = w->wl_next->wl_word; w = w->wl_next;
        } else if (strcasecmp(k, "keep") == 0) {
            while (w->wl_next && nkeep < 256) {
                const char *nx = w->wl_next->wl_word;
                if (strcasecmp(nx, "factor") == 0 || strcasecmp(nx, "file") == 0 ||
                    strcasecmp(nx, "name") == 0 || strcasecmp(nx, "keep") == 0 ||
                    strcasecmp(nx, "maxdeg") == 0)
                    break;                          /* next keyword: stop consuming */
                {
                    int nd = red_node(ckt, nx);
                    if (nd > 0) keep[nkeep++] = nd;
                    else fprintf(cp_err, "Warning: reduce: keep node '%s' not found.\n", nx);
                }
                w = w->wl_next;
            }
        } else {
            fprintf(cp_err, "Warning: reduce: unknown option '%s' ignored.\n", k);
        }
    }
    if (factor < 1.0) {
        fprintf(cp_err, "Error: reduce: factor is the time-constant ratio a node "
                        "must beat to be eliminated and must be >= 1 (got %g); "
                        "1 eliminates the most, larger values fewer\n", factor);
        return;
    }

    r = CKTreduceRC(ckt, fmax, factor, maxdeg, keep, nkeep, fname, subname);
    if (r < 0)
        fprintf(cp_err, "reduce: reduction did not complete.\n");
}
