/**********
Enhancement-134: Harmonic Balance -- `hb <f0> <K> [points] [maxiter]`.

Single-tone harmonic balance: find the periodic steady state in the FREQUENCY
domain by Newton, instead of integrating in time. Each node voltage is a truncated
Fourier series V(t)=sum_{k=-K..K} V_k e^{jk w0 t}; the KCL residual at each
node/harmonic is driven to zero with the E-121 conversion matrix as the Jacobian.
The heavy lifting is in HBanalyze() (spicelib/analysis/dcpss.c, which reuses the
conversion matrix + dense complex solver); this command parses the arguments,
makes sure the circuit is built, and runs it.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/fteext.h"
#include "ngspice/wordlist.h"
#include "ngspice/cpextern.h"

#include "circuits.h"
#include "com_hb.h"

static double hbnum(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}

void
com_hb(wordlist *wl)
{
    CKTcircuit *ckt;
    double f0, tol = 1e-10;
    int    K, P = 0, maxiter = 50, verbose, err;

    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "Error: hb: there is no circuit loaded.\n");
        return;
    }
    ckt = ft_curckt->ci_ckt;

    if (!wl || !wl->wl_next) {
        fprintf(cp_err, "Usage: hb <f0> <K> [points] [maxiter]\n");
        return;
    }
    f0 = hbnum(wl->wl_word);
    K  = (int) hbnum(wl->wl_next->wl_word);
    if (wl->wl_next->wl_next) {
        P = (int) hbnum(wl->wl_next->wl_next->wl_word);
        if (wl->wl_next->wl_next->wl_next)
            maxiter = (int) hbnum(wl->wl_next->wl_next->wl_next->wl_word);
    }
    if (f0 <= 0.0 || K < 1) {
        fprintf(cp_err, "Error: hb: need f0 > 0 and K >= 1.\n");
        return;
    }

    /* Honor `.option klu`: a bare `hb` builds the circuit here rather than via
     * cktdojob (which is where a normal analysis copies task->TSKkluMODE), so pull
     * the KLU mode from the task before CKTsetup wires the matrix -- else the matrix
     * defaults to Sparse and the `.option klu` request is silently ignored. */
#ifdef KLU
    if (ft_curckt->ci_defTask &&
        (ckt->CKTmatrix == NULL || SMPmatSize(ckt->CKTmatrix) <= 0))
        ckt->CKTkluMODE = ft_curckt->ci_defTask->TSKkluMODE;
#endif

    /* make sure the circuit is built (matrix + states allocated) */
    if (ckt->CKTmatrix == NULL || SMPmatSize(ckt->CKTmatrix) <= 0) {
        if ((err = CKTsetup(ckt)) != OK || (err = CKTtemp(ckt)) != OK) {
            fprintf(cp_err, "Error: hb: circuit setup failed.\n");
            return;
        }
    }

    verbose = cp_getvar("hb_verbose", CP_BOOL, NULL, 0);
    ft_curckt->ci_curTask = ft_curckt->ci_defTask;
    ckt->CKTcurJob = ft_curckt->ci_defTask ? ft_curckt->ci_defTask->jobs : NULL;

    err = HBanalyze(ckt, f0, K, P, maxiter, tol, verbose ? 1 : 0);
    if (err != OK)
        fprintf(cp_err, "hb: harmonic balance did not complete (error %d).\n", err);
}
