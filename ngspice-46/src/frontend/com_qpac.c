/**********
Enhancement-137: two-tone small-signal QPAC (quasi-periodic AC) -- `qpac <f_in>`.

Injects a small signal at frequency f_in around the QPSS operating point retained by a
prior `qpss <expr> <f1> <f2> hb`, and reports the response at every sideband
f_in + k1*f1 + k2*f2 -- the two-tone analogue of PAC. The quasi-periodic operating point
mixes the small signal to the sidebands through the same 2-D conversion matrix the QPSS
Newton used as its Jacobian. The heavy lifting is QPACanalyze() (spicelib/analysis/
dcpss.c); this command parses f_in and runs it.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/fteext.h"
#include "ngspice/wordlist.h"
#include "ngspice/cpextern.h"

#include "com_qpac.h"

static double qpacnum(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}

void
com_qpac(wordlist *wl)
{
    CKTcircuit *ckt;
    double f_in;
    int    verbose, err;

    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "Error: qpac: there is no circuit loaded.\n");
        return;
    }
    ckt = ft_curckt->ci_ckt;

    if (!wl || !wl->wl_word) {
        fprintf(cp_err, "Usage: qpac <f_in>   (run `qpss <expr> <f1> <f2> hb` first)\n");
        return;
    }
    f_in = qpacnum(wl->wl_word);
    if (f_in <= 0.0) {
        fprintf(cp_err, "Error: qpac: need f_in > 0.\n");
        return;
    }

    verbose = cp_getvar("qpac_verbose", CP_BOOL, NULL, 0);
    err = QPACanalyze(ckt, f_in, verbose ? 1 : 0);
    if (err != OK)
        fprintf(cp_err, "qpac: quasi-periodic AC did not complete (error %d).\n", err);
}
