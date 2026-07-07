/* Enhancement-94: the 'pyplot' command -- plot vectors via matplotlib.
   Like com_gnuplot(), but the output file base name is OPTIONAL (E-95): the
   first word is treated as a file name only when it is not itself a plot
   expression (it contains no '(' and does not name a vector); otherwise the
   base name defaults to "pyplot" and every word is a plot argument. */

#include <stddef.h>
#include <string.h>

#include "ngspice/ngspice.h"
#include "ngspice/bool.h"
#include "ngspice/wordlist.h"
#include "ngspice/fteext.h"

#include "plotting/plotit.h"
#include "../misc/mktemp.h"

#include "com_pyplot.h"


/* matplotlib [file] plotargs */
void
com_pyplot(wordlist *wl)
{
    char *fname = NULL;
    char defname[] = "pyplot";
    bool tempf = FALSE;

    if (!wl)
        return;

    /* The first word is an output file name only if it is not itself a plot
       expression -- i.e. it has no '(' (as in v(out), db(...)) and does not
       name an existing vector (as a bare node name would). Otherwise the base
       name defaults to "pyplot" and all words are plot arguments. */
    {
        const char *w = wl->wl_word;
        bool is_expr = (strchr(w, '(') != NULL) || (vec_get(w) != NULL);
        if (!is_expr) {
            fname = wl->wl_word;
            wl = wl->wl_next;
        }
    }

    if (!fname)
        fname = defname;

    if (cieq(fname, "temp") || cieq(fname, "tmp")) {
        fname = smktemp("py");
        tempf = TRUE;
    }

    if (!wl) /* no plot arguments left */
        return;

    (void) plotit(wl, fname, "pyplot");

    if (tempf)
        tfree(fname);
}
