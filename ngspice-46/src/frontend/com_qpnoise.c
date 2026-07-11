/**********
Enhancement-138: two-tone small-signal QPnoise (quasi-periodic noise) --
`qpnoise <output_node> <f_in>`.

Around the QPSS operating point retained by a prior `qpss <expr> <f1> <f2> hb`, folds
every device's noise through the ADJOINT of the 2-D conversion matrix over all sidebands
to the output at f_in -- the two-tone analogue of pnoise. A mixer/PA's device noise at
each sideband f_in + k1*f1 + k2*f2 is converted (folded) to the output. The engine is
QPnoiseAnalyze() (spicelib/analysis/dcpss.c); this command resolves the output node and
runs it.
**********/

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/cktdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/fteext.h"
#include "ngspice/wordlist.h"
#include "ngspice/cpextern.h"
#include "ngspice/ifsim.h"

#include "com_qpnoise.h"

static double qpnnum(const char *w)
{
    char *s = (char *) w;
    double v = 0.0;
    if (ft_numparse(&s, FALSE, &v) < 0)
        v = atof(w);
    return v;
}

/* resolve a node name to its 1-based CKT node number via the name list, else 0 */
static int qpn_node(CKTcircuit *ckt, const char *name)
{
    int numNames = 0, i, num = 0;
    IFuid *nameList = NULL;
    if (CKTnames(ckt, &numNames, &nameList) != OK || !nameList)
        return 0;
    for (i = 0; i < numNames; i++)
        if (nameList[i] && strcmp((const char *) nameList[i], name) == 0) {
            num = i + 1;
            break;
        }
    tfree(nameList);
    return num;
}

void
com_qpnoise(wordlist *wl)
{
    CKTcircuit *ckt;
    double f_in;
    int    outNode, verbose, err;

    if (!ft_curckt || !ft_curckt->ci_ckt) {
        fprintf(cp_err, "Error: qpnoise: there is no circuit loaded.\n");
        return;
    }
    ckt = ft_curckt->ci_ckt;

    if (!wl || !wl->wl_next) {
        fprintf(cp_err, "Usage: qpnoise <output_node> <f_in>   "
                        "(run `qpss <expr> <f1> <f2> hb` first)\n");
        return;
    }
    outNode = qpn_node(ckt, wl->wl_word);
    if (outNode <= 0) {
        fprintf(cp_err, "Error: qpnoise: unknown output node '%s'.\n", wl->wl_word);
        return;
    }
    f_in = qpnnum(wl->wl_next->wl_word);
    if (f_in <= 0.0) {
        fprintf(cp_err, "Error: qpnoise: need f_in > 0.\n");
        return;
    }

    verbose = cp_getvar("qpnoise_verbose", CP_BOOL, NULL, 0);
    err = QPnoiseAnalyze(ckt, outNode, f_in, verbose ? 1 : 0);
    if (err != OK)
        fprintf(cp_err, "qpnoise: quasi-periodic noise did not complete (error %d).\n", err);
}
