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
#include "plotting/pyplot.h" /* ft_pyplot_eye() */
#include "../misc/mktemp.h"
#include "../misc/util.h" /* ngdirname() */

#include "com_pyplot.h"
#include "com_eye.h" /* com_eye() -- for the -eye flag (Enhancement-208) */


/* matplotlib [file] plotargs */
void
com_pyplot(wordlist *wl)
{
    char *fname = NULL;
    char *fullname = NULL;
    wordlist *wl_owned = NULL;     /* E-217/E-218: filtered copy we (not the caller) own */
    char defname[64] = "pyplot";
    bool tempf = FALSE;
    /* Enhancement-183: successive default-named plots must get DISTINCT base
       names. In window (interactive) mode pyplot launches the Python viewer in
       the BACKGROUND, so two plots that share the "pyplot" base race on the
       same pyplot.py/pyplot.data: the second call overwrites the files before
       the first viewer has read them, and both windows end up showing the
       second plot (its title, its data). A per-session counter keeps the first
       default plot named "pyplot" (unchanged) and names later ones
       "pyplot-2", "pyplot-3", ... so each viewer reads its own files. */
    static unsigned int autoseq = 0;
    /* Enhancement-208: `pyplot [name] -eye <expr> -ui <T> [opts]` renders an eye
       diagram. `eye_args` (set when a -eye marker is found) points at the `eye`
       command's own arguments -- the expression and its flags. */
    bool is_eye = FALSE;
    wordlist *eye_args = NULL;
    /* Enhancement-217: `pyplot [name] -hist <sig> ...` renders each listed signal's
       value distribution as a histogram. Unlike -eye (a distinct analysis), -hist is
       just a render mode over the normal signal list, so the marker is stripped and
       the rest dispatched to plotit's histogram device.
       Enhancement-218: `pyplot [name] -contour <z> <x> <y>` renders a 2-D contour
       map of z over the (x, y) plane -- likewise a render mode over the signal
       list, dispatched to plotit's contour device. */
    bool is_hist = FALSE;
    bool is_contour = FALSE;
    bool is_smith = FALSE;
    bool is_fft = FALSE;    /* Enhancement-297: `-fft` magnitude spectrum */
    /* Enhancement-298: complex-aware AC views. */
    bool is_bode = FALSE, is_nyquist = FALSE, is_polar = FALSE;

    if (!wl)
        return;

    /* E-208: detect the -eye marker anywhere in the argument list; the tokens
       after it belong to the `eye` command. A single bare token before -eye is
       taken as the output base name (`pyplot myeye -eye v(rx) -ui 0.5n`). */
    {
        wordlist *w, *marker = NULL;
        for (w = wl; w; w = w->wl_next)
            if (w->wl_word && eq(w->wl_word, "-eye")) { marker = w; break; }
        if (marker) {
            is_eye = TRUE;
            strcpy(defname, "eye");
            if (wl != marker && wl->wl_word)
                fname = wl->wl_word;
            eye_args = marker->wl_next;
            if (!eye_args || !eye_args->wl_word) {
                fprintf(cp_err, "Usage: pyplot [name] -eye <expr> -ui <T> "
                        "[-tstart t0] [-threshold vth] [-window frac]\n");
                return;
            }
        }
    }

    /* E-217/E-218: detect a `-hist` or `-contour` render-mode marker (anywhere in
       the list).  The marker has to be removed before the rest goes to plotit, but
       `wl` is the command's own argument list -- owned and freed by the command loop.
       Mutating or freeing its nodes here corrupts it: freeing the head node (when the
       marker was the FIRST word) double-freed the whole argument list on return. So
       build a filtered COPY without the marker and use that; `wl` is left untouched. */
    if (!is_eye) {
        wordlist *w;
        bool found = FALSE;
        for (w = wl; w; w = w->wl_next) {
            if (w->wl_word && eq(w->wl_word, "-hist"))         { is_hist = TRUE;    found = TRUE; }
            else if (w->wl_word && eq(w->wl_word, "-contour")) { is_contour = TRUE; found = TRUE; }
            else if (w->wl_word && eq(w->wl_word, "-smith"))   { is_smith = TRUE;   found = TRUE; }
            else if (w->wl_word && eq(w->wl_word, "-fft"))     { is_fft = TRUE;     found = TRUE; }
            else if (w->wl_word && eq(w->wl_word, "-bode"))    { is_bode = TRUE;    found = TRUE; }
            else if (w->wl_word && eq(w->wl_word, "-nyquist")) { is_nyquist = TRUE; found = TRUE; }
            else if (w->wl_word && eq(w->wl_word, "-polar"))   { is_polar = TRUE;   found = TRUE; }
        }
        if (found) {
            wordlist *tail = NULL;
            for (w = wl; w; w = w->wl_next) {
                if (w->wl_word && (eq(w->wl_word, "-hist") || eq(w->wl_word, "-contour")
                                   || eq(w->wl_word, "-smith") || eq(w->wl_word, "-fft")
                                   || eq(w->wl_word, "-bode") || eq(w->wl_word, "-nyquist")
                                   || eq(w->wl_word, "-polar")))
                    continue;                         /* drop the marker word */
                wordlist *nw = TMALLOC(wordlist, 1);
                nw->wl_word = copy(w->wl_word ? w->wl_word : "");
                nw->wl_next = NULL;
                nw->wl_prev = tail;
                if (tail) tail->wl_next = nw; else wl_owned = nw;
                tail = nw;
            }
            wl = wl_owned;                            /* the filtered copy (may be NULL) */
        }
        if (is_contour)
            strcpy(defname, "contour");
        if (is_smith)
            strcpy(defname, "smith");
        if (is_fft)
            strcpy(defname, "fft");
        if (is_bode)
            strcpy(defname, "bode");
        if (is_nyquist)
            strcpy(defname, "nyquist");
        if (is_polar)
            strcpy(defname, "polar");
        if (!wl)                                      /* marker with no signals */
            goto done;
    }

    /* The first word is an output file name only if it is not itself a plot
       expression -- i.e. it has no '(' (as in v(out), db(...)) and does not
       name an existing vector (as a bare node name would). Otherwise the base
       name defaults to "pyplot" and all words are plot arguments. */
    if (!is_eye) {
        const char *w = wl->wl_word;
        bool is_expr = (strchr(w, '(') != NULL) || (vec_get(w) != NULL);
        if (!is_expr) {
            fname = wl->wl_word;
            wl = wl->wl_next;
        }
    }

    if (!fname) {
        if (autoseq > 0)
            (void) snprintf(defname, sizeof defname, "%s-%u",
                            is_eye ? "eye" : is_contour ? "contour"
                            : is_smith ? "smith" : is_fft ? "fft"
                            : is_bode ? "bode" : is_nyquist ? "nyquist"
                            : is_polar ? "polar" : "pyplot",
                            autoseq + 1);
        autoseq++;
        fname = defname;
    }

    if (cieq(fname, "temp") || cieq(fname, "tmp")) {
        fname = smktemp("py");
        tempf = TRUE;
    }

    /* Enhancement-183: write the .py/.data (and the .png) next to the CIRCUIT
       FILE, not in whatever directory ngspice happens to have been started
       from -- so a self-contained deck folder collects its own plot artifacts.
       Only when the user gave a bare base name (their own path, if any, is
       respected) and we know where the deck came from; a bare relative deck
       name (ci_filename dir == ".") is left in the cwd, exactly as before. */
    if (!tempf && ft_curckt && ft_curckt->ci_filename &&
            strchr(fname, DIR_TERM) == NULL && strchr(fname, '/') == NULL) {
        char *dir = ngdirname(ft_curckt->ci_filename);
        if (dir && dir[0] && !(dir[0] == '.' && dir[1] == '\0')) {
            fullname = tprintf("%s%s%s", dir, DIR_PATHSEP, fname);
            fname = fullname;
        }
        tfree(dir);
    }

    /* Enhancement-208: run the `eye` analysis (it folds the waveform and leaves
       eye_wave/eye_t + the scalar metrics in a fresh current 'eye' plot), then
       render that folded eye as a matplotlib eye diagram. */
    if (is_eye) {
        com_eye(eye_args);
        ft_pyplot_eye(fname, eye_args->wl_word);
        goto done;
    }

    if (!wl) /* no plot arguments left */
        goto done;

    (void) plotit(wl, fname,
                  is_contour ? "pyplotcontour" : is_hist ? "pyplothist"
                  : is_smith ? "pyplotsmith" : is_fft ? "pyplotfft"
                  : is_bode ? "pyplotbode" : is_nyquist ? "pyplotnyquist"
                  : is_polar ? "pyplotpolar" : "pyplot");

done:
    if (tempf)
        tfree(fname);
    if (fullname)
        tfree(fullname);
    if (wl_owned)
        wl_free(wl_owned);
}
