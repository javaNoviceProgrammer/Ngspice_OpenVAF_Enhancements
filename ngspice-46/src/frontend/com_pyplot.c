/* Enhancement-94: the 'pyplot' command -- plot vectors via matplotlib.
   Mirrors com_gnuplot(): the first word is the output file base name, the
   rest are the plot arguments handed to plotit() with the "pyplot" backend. */

#include <stddef.h>

#include "ngspice/ngspice.h"
#include "ngspice/bool.h"
#include "ngspice/wordlist.h"

#include "plotting/plotit.h"
#include "../misc/mktemp.h"

#include "com_pyplot.h"


/* matplotlib file plotargs */
void
com_pyplot(wordlist *wl)
{
    char *fname = NULL;
    bool tempf = FALSE;

    if (wl) {
        fname = wl->wl_word;
        wl = wl->wl_next;
    }

    if (!wl)
        return;

    if (cieq(fname, "temp") || cieq(fname, "tmp")) {
        fname = smktemp("py");
        tempf = TRUE;
    }

    (void) plotit(wl, fname, "pyplot");

    if (tempf)
        tfree(fname);
}
