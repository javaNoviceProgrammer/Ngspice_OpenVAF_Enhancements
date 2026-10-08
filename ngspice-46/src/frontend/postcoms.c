/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
**********/

/*
 * Various post-processor commands having to do with vectors.
 */

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/sim.h"
#include "ngspice/plot.h"
#include "ngspice/graph.h"
#include "ngspice/ftedbgra.h"
#include "com_display.h"

#include "completion.h"
#include "postcoms.h"
#include "variable.h"
#include "ngspice/stringskip.h"
#include "../misc/misc_time.h"
#include "parser/complete.h" /* va: throwaway */
#include "plotting/plotting.h"

#include "ngspice/compatmode.h"
#include "ngspice/dstring.h"
#include "numparam/general.h"

static void killplot(struct plot *pl);
static void DelPlotWindows(struct plot *pl);

/* check if the user want's to delete the scale vector of the current plot.
   This should not happen, because then redrawing the graph crashes ngspice */
static bool
is_scale_vec_of_current_plot(const char *v_name)
{
    if (!plot_cur) { /* no current plot */
        return FALSE;
    }

    const struct dvec * const pl_scale = plot_cur->pl_scale;
    if (!pl_scale) { /* no scale vector */
        return FALSE;
    }

    /* Test if this vector's name matches the scale vector's name */
    return cieq(v_name, pl_scale->v_name);
} /* end of function is_scale_vec_of_current_plot */


/* Remove vectors in the wordlist from the current plot */
void
com_unlet(wordlist *wl)
{
    for ( ; wl != (wordlist *) NULL; wl = wl->wl_next) {
        /* Don't delete the scale vector of the current plot */
        const char * const vector_name = wl->wl_word;
        if (is_scale_vec_of_current_plot(vector_name)) {
            /* If it is the scale vector of the current plot, print a
             * warning. Note that if it is true,  the scale vector name must
             * exist, so no part of plot_cur->pl_scale->v_name can be null. */
            fprintf(cp_err,
                    "\nWarning: Scale vector '%s' of the current plot "
                    "cannot be deleted!\n"
                    "Command 'unlet %s' is ignored.\n\n",
                    plot_cur->pl_scale->v_name, vector_name);
        }
        else {
            vec_remove(vector_name);
        }
    } /* end of loop over vectors to delete */
} /* end of function com_unlet */


/* Remove zero length vectors from the current plot */
void
com_remzerovec(wordlist* wl)
{
    NG_IGNORE(wl);
    
    struct dvec* ov;

    for (ov = plot_cur->pl_dvecs; ov; ov = ov->v_next) {
        if (ov->v_length == 0) {
            ov->v_flags &= ~VF_PERMANENT;
            /* Remove from the keyword list. */
            cp_remkword(CT_VECTOR, ov->v_name);
        }
    } /* end of loop over vectors to delete */
} /* end of function com_remzerovec */


/* Load in a file. */
void
com_load(wordlist *wl)
{
    char *copypath;
    if (!wl)
        ft_loadfile(ft_rawfile);
    else
        while (wl) {
            /*ft_loadfile(cp_unquote(wl->wl_word)); DG: bad memory leak*/
            copypath = cp_unquote(wl->wl_word);/*DG*/
            ft_loadfile(copypath);
            tfree(copypath);
            wl = wl->wl_next;
        }

    /* note: default is to display the vectors in the last (current) plot */
    com_display(NULL);
}


/* Print out the value of an expression. When we are figuring out what to
 * print, link the vectors we want with v_link2... This has to be done
 * because of the way temporary vectors are linked together with permanent
 * ones under the plot.
 */

void
com_print(wordlist *wl)
{
    struct dvec *v, *lv = NULL, *bv, *nv, *vecs = NULL;
    int i, j, ll, width = DEF_WIDTH, height = DEF_HEIGHT, npoints, lineno, npages = 0;
    struct pnode *pn, *names = NULL;
    struct plot *p;
    bool col = TRUE, nobreak = FALSE, noprintscale, plotnames = FALSE;
    bool optgiven = FALSE;
    char *s, *buf, *buf2; /*, buf[BSIZE_SP], buf2[BSIZE_SP];*/
    char numbuf[BSIZE_SP], numbuf2[BSIZE_SP]; /* Printnum buffers */
    int ngood;
    wordlist *strwl = NULL;                     /* Enhancement-798 */

    if (wl == NULL)
        return;

    buf = TMALLOC(char, BSIZE_SP);
    buf2 = TMALLOC(char, BSIZE_SP);

    if (eq(wl->wl_word, "col")) {
        col = TRUE;
        optgiven = TRUE;
        wl = wl->wl_next;
    } else if (eq(wl->wl_word, "line")) {
        col = FALSE;
        optgiven = TRUE;
        wl = wl->wl_next;
    }

    ngood = 0;

    /* Enhancement-798 (hunt 2026-10-08 D3): a string parameter is printed as
     * text here -- `@t3m[mode] = lin` -- since a vector cannot hold it; the
     * words that named nothing else are left out of the vector list. */
    if (ft_curckt && !ft_nutmeg) {
        wordlist *w;
        int dropped = 0;
        for (w = wl; w; w = w->wl_next)
            if (w->wl_word && w->wl_word[0] == '@' &&
                if_print_string_params(ft_curckt->ci_ckt, w->wl_word, cp_out))
                dropped++;
            else
                strwl = wl_cons(copy(w->wl_word), strwl);
        if (dropped) {
            strwl = wl_reverse(strwl);
            if (!strwl)
                goto done;
            wl = strwl;
        } else {
            wl_free(strwl);
            strwl = NULL;
        }
    }

    names = ft_getpnames_quotes(wl, TRUE);

    for (pn = names; pn; pn = pn->pn_next) {
        if ((v = ft_evaluate(pn)) == NULL)
            continue;
        if (!vecs)
            vecs = lv = v;
        else
            lv->v_link2 = v;
        for (lv = v; lv->v_link2; lv = lv->v_link2)
            ;
        ngood += 1;
    }

    if (!ngood)
        goto done;

    /* See whether we really have to print plot names. */
    for (v = vecs; v; v = v->v_link2)
        if (vecs->v_plot != v->v_plot) {
            plotnames = TRUE;
            break;
        }

    if (!optgiven) {
        /* Figure out whether col or line should be used... */
        col = FALSE;
        for (v = vecs; v; v = v->v_link2)
            if (v->v_length > 1) {
                col = TRUE;
                /* Improvement made to print cases @[sin] = (0 12 13 100K) */
                if ((v->v_plot->pl_scale && v->v_length != v->v_plot->pl_scale->v_length) && (*(v->v_name) == '@'))
                {
                    col = FALSE;
                }
                break;
            }
        /* With this I have found that the vector has less elements than the SCALE vector
         * in the linked PLOT. But now I must make sure in case of a print @vin[sin] or
         * @vin[pulse]
         * for it appear that the v->v_name begins with '@'
         * And then be in this case.
         */
    }

    out_init();
    if (!col) {
        if (cp_getvar("width", CP_NUM, &i, 0))
            width = i;
        if (width < 60)
            width = 60;
        if (width > BSIZE_SP - 2)
            buf = TREALLOC(char, buf, (size_t) width + 1);
        for (v = vecs; v; v = v->v_link2) {
            char *basename = vec_basename(v);
            if (plotnames)
                (void) sprintf(buf, "%s.%s", v->v_plot->pl_typename, basename);
            else
                (void) strcpy(buf, basename);
            tfree(basename);

            for (s = buf; *s; s++)
                ;
            s--;
            while (isspace_c(*s)) {
                *s = '\0';
                s--;
            }
            ll = 10;

            /* v->v_rlength = 1 when it comes to make a print @ M1 and does not want to come out on screen
             * Multiplier factor [m]=1
             *  @M1 = 0,00e+00
             * In any other case rlength not used for anything and only applies in the copy of the vectors.
             */
            if (v->v_rlength == 0) {
                if (v->v_length == 1) {
                    if (isreal(v)) {
                        printnum(numbuf, sizeof numbuf, *v->v_realdata);
                        out_printf("%s = %s\n", buf, numbuf);
                    } else {
                        printnum(numbuf, sizeof numbuf, realpart(v->v_compdata[0]));
                        printnum(numbuf2, sizeof numbuf2, imagpart(v->v_compdata[0]));
                        out_printf("%s = %s,%s\n", buf, numbuf, numbuf2);
                    }
                } else {
                    out_printf("%s = (  ", buf);
                    for (i = 0; i < v->v_length; i++)
                        if (isreal(v)) {

                            printnum(numbuf, sizeof numbuf, v->v_realdata[i]);
                            (void) strcpy(buf, numbuf);
                            out_send(buf);
                            ll += (int) strlen(buf);
                            ll = (ll + 7) / 8;
                            ll = ll * 8 + 1;
                            if (ll > width) {
                                out_send("\n\t");
                                ll = 9;
                            } else {
                                out_send("\t");
                            }
                        } else {
                            /*DG*/
                            printnum(numbuf, sizeof numbuf, realpart(v->v_compdata[i]));
                            printnum(numbuf2, sizeof numbuf2, imagpart(v->v_compdata[i]));
                            (void) sprintf(buf, "%s,%s", numbuf, numbuf2);
                            out_send(buf);
                            ll += (int) strlen(buf);
                            ll = (ll + 7) / 8;
                            ll = ll * 8 + 1;
                            if (ll > width) {
                                out_send("\n\t");
                                ll = 9;
                            } else {
                                out_send("\t");
                            }
                        }
                    out_send(")\n");
                } //end if (v->v_length == 1)
            }  //end  if (v->v_rlength == 1)
        }  // end for loop
    } else {    /* Print in columns. */
        if (cp_getvar("width", CP_NUM, &i, 0))
            width = i;
        if (width < 40)
            width = 40;
        if (width > BSIZE_SP - 2) {
            buf = TREALLOC(char, buf, (size_t) width + 1);
            buf2 = TREALLOC(char, buf2, (size_t) width + 1);
        }
        if (cp_getvar("height", CP_NUM, &i, 0))
            height = i;
        if (height < 20)
            height = 20;
        nobreak = cp_getvar("nobreak", CP_BOOL, NULL, 0);
        if (!nobreak && !ft_nopage)
            nobreak = FALSE;
        else
            nobreak = TRUE;
        noprintscale = cp_getvar("noprintscale", CP_BOOL, NULL, 0);
        bv = vecs;
    nextpage:
        npages++;
        /* Make the first vector of every page be the scale... */
        /* XXX But what if there is no scale?  e.g. op, pz */
        if (!noprintscale && bv->v_plot->pl_ndims)
            if (bv->v_plot->pl_scale && !vec_eq(bv, bv->v_plot->pl_scale)) {
                nv = vec_copy(bv->v_plot->pl_scale);
                vec_new(nv);
                nv->v_link2 = bv;
                bv = nv;
            }

        ll = 8;
        for (lv = bv; lv; lv = lv->v_link2) {
            if (isreal(lv))
                ll += 16;   /* Two tabs for real, */
            else
                ll += 32;   /* 4 for complex. */
            /* Make sure we have at least 2 vectors per page... */
            if ((ll > width) && (lv != bv) && (lv != bv->v_link2))
                break;
        }

        /* Print the header on the first page only, if 'option nopage'. */
        if (!ft_nopage || npages == 1) {
            /* print the header */
            p = bv->v_plot;
            j = (width - (int)strlen(p->pl_title)) / 2;    /* Yes, keep "(int)" */
            if (j < 0)
                j = 0;
            for (i = 0; i < j; i++)
                buf2[i] = ' ';
            buf2[j] = '\0';
            out_send(buf2);
            out_send(p->pl_title);
            out_send("\n");
            out_send(buf2);
            (void)sprintf(buf, "%s  %s", p->pl_name, p->pl_date);
            out_send(buf);
            out_send("\n");
        }
        for (i = 0; i < width; i++)
            buf2[i] = '-';
        buf2[width] = '\n';
        buf2[width+1] = '\0';
        out_send(buf2);
        (void) sprintf(buf, "Index   ");
        for (v = bv; v && (v != lv); v = v->v_link2) {
            if (isreal(v)) {
                (void) sprintf(buf2, "%-16.15s", v->v_name);
            } else {
                /* The frequency vector is complex but often with imaginary part = 0,
                 * this prevents to print two columns.
                 */
                if (eq(v->v_name, "frequency")) {
                    if (imagpart(v->v_compdata[0]) == 0.0)
                        (void) sprintf(buf2, "%-16.15s", v->v_name);
                    else
                        (void) sprintf(buf2, "%-32.31s", v->v_name);
                } else {
                    (void) sprintf(buf2, "%-32.31s", v->v_name);
                }
            }
            (void) strcat(buf, buf2);
        }
        lineno = 3;
        j = 0;
        npoints = 0;
        for (v = bv; (v && (v != lv)); v = v->v_link2)
            if (v->v_length > npoints)
                npoints = v->v_length;
    pbreak:     /* New page. */
        out_send(buf);
        out_send("\n");
        for (i = 0; i < width; i++)
            buf2[i] = '-';
        buf2[width] = '\n';
        buf2[width+1] = '\0';
        out_send(buf2);
        lineno += 2;
    loop:
        while ((j < npoints) && (lineno < height)) {
            out_printf("%d\t", j);
            for (v = bv; (v && (v != lv)); v = v->v_link2) {
                if (v->v_length <= j) {
                    if (isreal(v))
                        out_send("\t\t");
                    else
                        out_send("\t\t\t\t");
                } else {
                    if (isreal(v)) {
                        printnum(numbuf, sizeof numbuf, v->v_realdata[j]);
                        out_printf("%s\t", numbuf);
                    } else {
                        /* In case of a single frequency and have a real part avoids print imaginary part equals 0. */
                        if (eq(v->v_name, "frequency") &&
                            imagpart(v->v_compdata[j]) == 0.0)
                        {
                            printnum(numbuf, sizeof numbuf, realpart(v->v_compdata[j]));
                            out_printf("%s\t", numbuf);
                        } else {
                            printnum(numbuf, sizeof numbuf, realpart(v->v_compdata[j]));
                            printnum(numbuf2, sizeof numbuf2, imagpart(v->v_compdata[j]));
                            out_printf("%s,\t%s\t", numbuf, numbuf2);
                        }
                    }
                }
            }
            out_send("\n");
            j++;
            lineno++;
        }
        if ((j == npoints) && (lv == NULL)) /* No more to print. */
            goto done;
        if (j == npoints) { /* More vectors to print. */
            bv = lv;
            if(nobreak)
                out_send("\n");   /* return without form feed. */
            else
                out_send("\f\n");   /* Form feed. */
            goto nextpage;
        }

        /* Otherwise go to a new page. */
        lineno = 0;
        if (nobreak)
            goto loop;
        else
            out_send("\f\n");   /* Form feed. */
        goto pbreak;
    }
done:
    /* Get rid of the vectors. */
    free_pnode(names);
    wl_free(strwl);
    tfree(buf);
    tfree(buf2);
}


/* Write out some data into a ngspice raw file with 'write filename expr'.
 * If vectors (expr) from various plots are selected, they are written
 * out as seperate plots.  In any case, we have to be sure to write out
 * the scales for everything we write. If expr is omitted, all vectors
 * of the current plot are written.
 */
void
com_write(wordlist *wl)
{
    char *file, buf[BSIZE_SP];
    struct pnode *pn;
    struct dvec *d, *vecs = NULL, *lv = NULL, *end, *vv;
    static wordlist all = { "all", NULL, NULL };
    struct pnode *names = NULL;
    bool ascii = AsciiRawFile;
    bool scalefound, appendwrite, plainwrite = FALSE;
    struct plot *tpl, newplot;

    if (wl) {
        /* Enhancement-558 (hunt F10): `write "w2.raw"` made a file called
         * "w2.raw", quotes included; the name is unquoted like `source`'s. */
        char *u = cp_unquote(wl->wl_word);
        tfree(wl->wl_word);
        wl->wl_word = u;
        file = wl->wl_word;
        wl = wl->wl_next;
    } else {
        file = ft_rawfile;
    }

    if (cp_getvar("filetype", CP_STRING, buf, sizeof(buf))) {
        if (eq(buf, "binary"))
            ascii = FALSE;
        else if (eq(buf, "ascii"))
            ascii = TRUE;
        else
            fprintf(cp_err, "Warning: strange file type %s\n", buf);
    }
    appendwrite = cp_getvar("appendwrite", CP_BOOL, NULL, 0);

    plainwrite = cp_getvar("plainwrite", CP_BOOL, NULL, 0);

    /* If variable plainwrite is set, we do not expand equations, serve v vs vs etc.
       We offer plain writing of the vectors. This enables node names containing +, -, / etc. */
    if (!plainwrite) {
        if (wl)
            names = ft_getpnames_quotes(wl, TRUE);
        else
            names = ft_getpnames_quotes(&all, TRUE);

        if (names == NULL) {
            fprintf(stderr, "Error during 'write': no writable vector found.\n");
            return;
        }

        for (pn = names; pn; pn = pn->pn_next) {
            d = ft_evaluate(pn);
            if (!d)
                goto done;
            if (vecs)
                lv->v_link2 = d;
            else
                vecs = d;
            for (lv = d; lv->v_link2; lv = lv->v_link2)
                ;
        }
    }
    else {
        wordlist* wli;
        if (!wl)
            wl = &all;
        for (wli = wl; wli; wli = wli->wl_next) {
            d = vec_get(wli->wl_word);
            if (!d) {
                fprintf(stderr, "Error during 'write': vector %s not found\n", wli->wl_word);
                goto done;
            }
            if (vecs)
                lv->v_link2 = d;
            else
                vecs = d;
            for (lv = d; lv->v_link2; lv = lv->v_link2)
                ;
        }
    }

    /* Now we have to write them out plot by plot. */

    while (vecs) {
        tpl = vecs->v_plot;
        tpl->pl_written = TRUE;
        end = NULL;
        memcpy(&newplot, tpl, sizeof(struct plot));
        scalefound = FALSE;

        /* Figure out how many vectors are in this plot. Also look
         * for the scale, or a copy of it, which may have a different
         * name.
         */
        for (d = vecs; d; d = d->v_link2) {
            if (d->v_plot == tpl) {
                char *basename = vec_basename(d);
                vv = vec_copy(d);
                /* Note that since we are building a new plot
                 * we don't want to vec_new this one...
                 */
                txfree(vv->v_name);
                vv->v_name = basename;

                if (end)
                    end->v_next = vv;
                else
                    end = newplot.pl_dvecs = vv;
                end = vv;

                if (vec_eq(d, tpl->pl_scale)) {
                    newplot.pl_scale = vv;
                    scalefound = TRUE;
                }
            }
        }
        end->v_next = NULL;

        /* Maybe we shouldn't make sure that the default scale is
         * present if nobody uses it.
         */
        if (!scalefound) {
            newplot.pl_scale = vec_copy(tpl->pl_scale);
            newplot.pl_scale->v_next = newplot.pl_dvecs;
            newplot.pl_dvecs = newplot.pl_scale;
        }

        /* Now let's go through and make sure that everything that
         * has its own scale has it in the plot.
         */
        for (;;) {
            scalefound = FALSE;
            for (d = newplot.pl_dvecs; d; d = d->v_next) {
                if (d->v_scale) {
                    for (vv = newplot.pl_dvecs; vv; vv = vv->v_next)
                        if (vec_eq(vv, d->v_scale))
                            break;
                    if (!vv) {
                        /* We have to grab it... */
                        vv = vec_copy(d->v_scale);
                        vv->v_next = newplot.pl_dvecs;
                        newplot.pl_dvecs = vv;
                        scalefound = TRUE;
                    }
                }
            }

            if (!scalefound)
                break;
            /* Otherwise loop through again... */
        }

        raw_write(file, &newplot, appendwrite, !ascii);

        for (vv = newplot.pl_dvecs; vv;) {
            struct dvec *next_vv = vv->v_next;
            vv->v_plot = NULL;
            vec_free(vv);
            vv = next_vv;
        }

        /* Now throw out the vectors we have written already... */
        for (d = vecs, lv = NULL;  d; d = d->v_link2)
            if (d->v_plot == tpl) {
                if (lv) {
                    lv->v_link2 = d->v_link2;
                    d = lv;
                } else {
                    vecs = d->v_link2;
                }
            } else {
                lv = d;
            }
        /* If there are more plots we want them appended... */
        appendwrite = TRUE;
    }

done:
    free_pnode(names);
}


/* Enhancement-64: write an N-port Touchstone v1 file (.sNp) directly from
   the S_i_j vectors of the current .sp plot. Layout per the Touchstone 1.x
   spec: `# Hz S RI R <Rbase>` option line; for N >= 3 the matrix is
   row-major with at most FOUR complex pairs per data line and every matrix
   row starting on a new line (the first row follows the frequency value);
   a 1-port is a single pair per line. (The classic 2-port S11 S21 S12 S22
   column order is handled by the original spar_write() path.) */
/* Enhancement-744 (Touchstone-import hunt F3, with F4's message and F8): the
   reader is version-aware, as E-741 made the pre_snp converter. Before, a
   line that was not `#` or `!` was scanned for numbers with sscanf, which
   stops at a `[`, so every Touchstone 2 keyword line was dropped whole: the
   frame count came out right, but `[Two-Port Data Order] 12_21` was never
   seen and S12 and S21 came back swapped, `[Reference]` was lost and Rbase
   fell back to the option line's R or 50, and a v2 Y or Z file, which the
   v2 specification stores un-normalized, would have been divided or
   multiplied by Rbase as if v1. Now the keywords are read ([Version],
   [Number of Ports], [Two-Port Data Order], [Number of Frequencies],
   [Number of Noise Frequencies], a per-port [Reference] continued over
   lines, [Matrix Format] Full/Lower/Upper, [Begin Information]..[End
   Information], [Network Data], [Noise Data], [End]); [Mixed-Mode Order],
   the G and H types and an unknown keyword are refused by name; a count
   that is not a whole number of frames names the count, the frame size and
   the two usual causes (a wrong port count, or v1 noise-parameter rows,
   which the reader does not read); a v1 file's Y and Z are de-normalized as
   before, a v2 file's taken as given; per-port references are published as
   the vector `Zref`, with `Rbase` port 1's; the port count comes from a
   `.yNp`/`.zNp` extension as well as `.sNp`; and a file with no option line
   is read with the specification's default, GHz S MA R 50, which the
   converter has always applied, where this reader assumed Hz S RI. */
static const char *
rdsnp_keyword(const char *p, char *kw, size_t kwlen)
{
    const char *rb = strchr(p, ']');
    size_t n = 0;
    int sp = 0;
    if (!rb)
        return NULL;
    for (p++; p < rb; p++) {
        if (isspace_c(*p)) { sp = 1; continue; }
        if (sp && n && n + 1 < kwlen) kw[n++] = ' ';
        sp = 0;
        if (n + 1 < kwlen) kw[n++] = tolower_c(*p);
    }
    kw[n] = '\0';
    return rb + 1;
}

/* Enhancement-750: one line of any length into a growable buffer (a 16-port
   frame on one line is over 8 KB; the fixed 4 KB buffer cut a number in two).
   Returns 0 at end of file. */
static int
rdsnp_getline(FILE *fp, char **buf, size_t *cap)
{
    size_t len = 0;
    if (!*buf) {
        *cap = 4096;
        *buf = TMALLOC(char, *cap);
    }
    (*buf)[0] = '\0';
    for (;;) {
        if (!fgets(*buf + len, (int) (*cap - len), fp))
            return len > 0;
        len += strlen(*buf + len);
        if (len == 0 || (*buf)[len - 1] == '\n' || len + 1 < *cap)
            return 1;
        *cap *= 2;
        *buf = TREALLOC(char, *buf, *cap);
    }
}

/* append the numbers on `q` (at most `limit`, or all when limit < 0) */
static int
rdsnp_numbers(const char *q, double **data, size_t *ndata, size_t *adata, int limit)
{
    double v;
    int i, added = 0;
    while ((limit < 0 || added < limit) && sscanf(q, " %lg%n", &v, &i) == 1) {
        if (*ndata == *adata) {
            *adata = *adata ? 2 * *adata : 1024;
            *data = TREALLOC(double, *data, *adata);
        }
        (*data)[(*ndata)++] = v;
        q += i;
        added++;
    }
    return added;
}

void
com_read_sparam(wordlist *wl)
{
    FILE *fp;
    char *line = NULL;
    size_t linecap = 0;
    char *file;
    int nports = 0, argports = 0, extports = 0;
    double fscale = 1e9, rbase = 50.0;      /* the specification's default: GHz S MA R 50 */
    char fmt = 'm', param = 's';
    bool have_opt_line = FALSE;
    int version = 1, order = 0, mformat = 0, kw_nports = 0, kw_nfreq = -1;
    int in_info = 0, in_data = 1, want_zref = 0, lineno = 0, in_noise = 0;
    double *zref = NULL;
    size_t nzref = 0, azref = 0;
    double *data = NULL;
    size_t ndata = 0, adata = 0;
    double *nz = NULL;            /* Enhancement-749: the noise-parameter rows */
    size_t nnz = 0, anz = 0;
    struct plot *netplot = NULL;
    int npairs, per_block, npts, i, j, k;
    struct plot *new;
    struct dvec *freqv, *last;

    if (!wl) {
        fprintf(stderr, "Error: rdsnp requires a file name\n");
        return;
    }
    file = wl->wl_word;
    if (wl->wl_next)
        argports = atoi(wl->wl_next->wl_word);
    {
        /* the extension: .sNp, and (Enhancement-744) .yNp / .zNp as wrsnp writes them */
        char *dot = strrchr(file, '.');
        if (dot && dot[1] && strchr("sSyYzZ", dot[1]) && file[strlen(file) - 1] == 'p') {
            extports = atoi(dot + 2);
            if (extports > 512)
                extports = 0;
        }
    }

    if ((fp = fopen(file, "r")) == NULL) {
        perror(file);
        return;
    }

    while (rdsnp_getline(fp, &line, &linecap)) {
        char *t, *bang;
        lineno++;
        bang = strchr(line, '!');
        if (bang)
            *bang = '\0';               /* a comment, leading or trailing */
        t = skip_ws(line);
        if (*t == '\0')
            continue;
        if (*t == '[') {
            char kw[64];
            const char *rest = rdsnp_keyword(t, kw, sizeof kw);
            if (!rest) {
                fprintf(stderr, "Error: %s line %d: unclosed '[' keyword\n", file, lineno);
                goto bad;
            }
            if (in_info) {
                if (eq(kw, "end information"))
                    in_info = 0;
                continue;
            }
            if (version == 1) {
                version = 2;
                in_data = 0;
            }
            want_zref = 0;
            if (eq(kw, "version")) {
                /* 2.0 and 2.1 read alike here */
            } else if (eq(kw, "number of ports")) {
                kw_nports = atoi(rest);
                if (kw_nports <= 0 || kw_nports > 512) {
                    fprintf(stderr, "Error: %s line %d: [Number of Ports] must be 1 to 512\n", file, lineno);
                    goto bad;
                }
            } else if (eq(kw, "two-port data order")) {
                if (strstr(rest, "12_21"))
                    order = 2;
                else if (strstr(rest, "21_12"))
                    order = 1;
                else {
                    fprintf(stderr, "Error: %s line %d: [Two-Port Data Order] must be 12_21 or 21_12\n", file, lineno);
                    goto bad;
                }
            } else if (eq(kw, "number of frequencies")) {
                kw_nfreq = atoi(rest);
            } else if (eq(kw, "number of noise frequencies")) {
                /* the noise block is not read */
            } else if (eq(kw, "reference")) {
                if (kw_nports <= 0) {
                    fprintf(stderr, "Error: %s line %d: [Reference] before [Number of Ports]\n", file, lineno);
                    goto bad;
                }
                want_zref = 1;
                (void) rdsnp_numbers(rest, &zref, &nzref, &azref, (int) ((size_t) kw_nports - nzref));
                if (nzref >= (size_t) kw_nports)
                    want_zref = 0;
            } else if (eq(kw, "matrix format")) {
                const char *m = skip_ws((char *) rest);
                if (ciprefix("full", m))
                    mformat = 0;
                else if (ciprefix("lower", m))
                    mformat = 1;
                else if (ciprefix("upper", m))
                    mformat = 2;
                else {
                    fprintf(stderr, "Error: %s line %d: [Matrix Format] must be Full, Lower or Upper\n", file, lineno);
                    goto bad;
                }
            } else if (eq(kw, "network data")) {
                in_data = 1;
            } else if (eq(kw, "noise data")) {
                in_noise = 1;               /* Enhancement-749: the rows follow */
            } else if (eq(kw, "end")) {
                break;
            } else if (eq(kw, "begin information")) {
                in_info = 1;
            } else if (eq(kw, "mixed-mode order")) {
                fprintf(stderr, "Error: %s line %d: [Mixed-Mode Order] -- mixed-mode S-parameters are not supported; "
                                "convert the file to single-ended (standard) order first\n", file, lineno);
                goto bad;
            } else {
                fprintf(stderr, "Error: %s line %d: unknown Touchstone keyword [%s]\n", file, lineno, kw);
                goto bad;
            }
            continue;
        }
        if (in_info)
            continue;
        if (*t == '#') {
            /* option line: [unit] [param] [format] [R n], any order */
            char tok[64];
            int pos = 1;
            while (sscanf(t + pos, " %63s%n", tok, &i) == 1) {
                pos += i;
                if (cieq(tok, "hz"))
                    fscale = 1.0;
                else if (cieq(tok, "khz"))
                    fscale = 1e3;
                else if (cieq(tok, "mhz"))
                    fscale = 1e6;
                else if (cieq(tok, "ghz"))
                    fscale = 1e9;
                else if (cieq(tok, "s") || cieq(tok, "y") || cieq(tok, "z"))
                    param = (char) tolower_c(tok[0]);
                else if (cieq(tok, "g") || cieq(tok, "h")) {
                    fprintf(stderr, "Error: %s line %d: option line parameter type %s (hybrid parameters) "
                                    "is not supported; use S, Y or Z\n", file, lineno, tok);
                    goto bad;
                }
                else if (cieq(tok, "ri"))
                    fmt = 'r';
                else if (cieq(tok, "ma"))
                    fmt = 'm';
                else if (cieq(tok, "db"))
                    fmt = 'd';
                else if (cieq(tok, "r")) {
                    if (sscanf(t + pos, " %lg%n", &rbase, &i) == 1)
                        pos += i;
                }
            }
            have_opt_line = TRUE;
            continue;
        }
        if (want_zref) {            /* [Reference] values continued on the following line(s) */
            (void) rdsnp_numbers(t, &zref, &nzref, &azref, (int) ((size_t) kw_nports - nzref));
            if (nzref >= (size_t) kw_nports)
                want_zref = 0;
            continue;
        }
        if (in_noise) {
            (void) rdsnp_numbers(t, &nz, &nnz, &anz, -1);
            continue;
        }
        if (!in_data) {
            fprintf(stderr, "Error: %s line %d: data before [Network Data]\n", file, lineno);
            goto bad;
        }
        /* data line: append every number */
        (void) rdsnp_numbers(t, &data, &ndata, &adata, -1);
    }
    (void) fclose(fp);
    fp = NULL;
    tfree(line);

    if (!have_opt_line)
        fprintf(stderr, "Warning: no '#' option line in %s; assuming the specification's default, GHz S MA R 50\n", file);

    if (version == 2) {
        if (kw_nports <= 0) {
            fprintf(stderr, "Error: %s is a Touchstone 2 file without [Number of Ports]\n", file);
            goto bad;
        }
        if (argports > 0 && argports != kw_nports) {
            fprintf(stderr, "Error: %s: [Number of Ports] %d disagrees with the %d given on the command\n",
                    file, kw_nports, argports);
            goto bad;
        }
        if (extports > 0 && extports != kw_nports) {
            fprintf(stderr, "Error: %s: [Number of Ports] %d disagrees with the file's extension (%d ports)\n",
                    file, kw_nports, extports);
            goto bad;
        }
        nports = kw_nports;
        if (nports == 2 && mformat == 0 && order == 0) {
            fprintf(stderr, "Error: %s is a Touchstone 2 two-port file without [Two-Port Data Order]\n", file);
            goto bad;
        }
        if (nzref > 0 && nzref < (size_t) nports) {
            fprintf(stderr, "Error: %s: [Reference] gives %zu impedances for %d ports\n", file, nzref, nports);
            goto bad;
        }
    } else {
        nports = argports > 0 ? argports : extports;
        order = 1;
    }
    if (nports <= 0) {
        fprintf(stderr,
                "Error: cannot infer the port count from '%s'; use rdsnp <file> <nports>\n",
                file);
        goto bad;
    }

    npairs = (mformat == 0) ? nports * nports : nports * (nports + 1) / 2;
    per_block = 1 + 2 * npairs;
    if (version == 1) {
        /* Enhancement-749: a Touchstone 1 noise-parameter block follows the
         * network data and is told by its frequency falling back below the
         * last frame's; what follows the frames goes to the noise rows */
        size_t r = 0;
        double prevf = -1.0;
        while ((r + 1) * (size_t) per_block <= ndata) {
            double f = data[r * (size_t) per_block];
            if (r > 0 && f <= prevf)
                break;
            prevf = f;
            r++;
        }
        if (r * (size_t) per_block < ndata) {
            size_t q, first = r * (size_t) per_block;
            for (q = first; q < ndata; q++) {
                if (nnz == anz) {
                    anz = anz ? 2 * anz : 64;
                    nz = TREALLOC(double, nz, anz);
                }
                nz[nnz++] = data[q];
            }
            ndata = first;
        }
    }
    if (ndata == 0 || ndata % (size_t) per_block != 0) {
        fprintf(stderr,
                "Error: %s holds %zu numbers of network data, not a whole number of %d-port frames of %d "
                "(frequency + %d pairs): a wrong port count, or a malformed file -- give the port count\n",
                file, ndata, nports, per_block, npairs);
        goto bad;
    }
    if (nnz % 5 != 0) {
        fprintf(stderr, "Error: %s: %zu numbers in the noise-parameter block, not a whole number of rows of five "
                        "(frequency, NFmin, |Gopt|, angle of Gopt, Rn)\n", file, nnz);
        goto bad;
    }
    npts = (int) (ndata / (size_t) per_block);
    if (kw_nfreq >= 0 && npts != kw_nfreq) {
        fprintf(stderr, "Error: %s: [Number of Frequencies] says %d, the file holds %d frames\n", file, kw_nfreq, npts);
        goto bad;
    }
    if (version == 2 && nzref == (size_t) nports)
        rbase = zref[0];

    /* build the plot (same pattern as com_linearize) */
    new = plot_alloc("sp");
    new->pl_name = tprintf("Touchstone import %s", file);
    new->pl_title = copy(file);
    plot_new(new);           /* E-345: this already inserts; the open-coded
                              * pl_next/plot_list lines that used to bracket it
                              * were redundant and have been removed */
    plot_setcur(new->pl_typename);

    freqv = dvec_alloc(copy("frequency"), SV_FREQUENCY, VF_REAL | VF_PERMANENT, npts, NULL);
    freqv->v_plot = new;
    for (k = 0; k < npts; k++)
        freqv->v_realdata[k] = data[(size_t) k * (size_t) per_block] * fscale;
    new->pl_scale = new->pl_dvecs = freqv;
    last = freqv;

    for (i = 0; i < nports; i++) {
        for (j = 0; j < nports; j++) {
            char nb[40];
            struct dvec *v;
            int pair;
            /* position of pair (i,j) within a frame: the v1 two-port order
               S11 S21 S12 S22 (and v2 21_12), v2 12_21 and every other port
               count row-major; a triangle mirrored (Enhancement-744) */
            if (mformat == 1) {                 /* lower: (r, c) with c <= r */
                int r = i >= j ? i : j, c = i >= j ? j : i;
                pair = r * (r + 1) / 2 + c;
            } else if (mformat == 2) {          /* upper: (r, c) with c >= r */
                int r = i <= j ? i : j, c = i <= j ? j : i;
                pair = r * nports - r * (r - 1) / 2 + (c - r);
            } else if (nports == 2 && order == 1) {
                static const int ord[2][2] = {{0, 2}, {1, 3}};
                pair = ord[i][j];
            } else {
                pair = i * nports + j;
            }
            (void) sprintf(nb, "%c_%d_%d", toupper_c(param), i + 1, j + 1);
            v = dvec_alloc(copy(nb), SV_NOTYPE, VF_COMPLEX | VF_PERMANENT, npts, NULL);
            v->v_plot = new;
            for (k = 0; k < npts; k++) {
                size_t base = (size_t) k * (size_t) per_block + 1 + 2 * (size_t) pair;
                double a = data[base], b = data[base + 1];
                double re, im;
                if (fmt == 'r') {
                    re = a;
                    im = b;
                } else {
                    double mag = (fmt == 'd') ? pow(10.0, a / 20.0) : a;
                    re = mag * cos(b * M_PI / 180.0);
                    im = mag * sin(b * M_PI / 180.0);
                }
                /* de-normalize back to absolute Y/Z: v1 files carry Y*R, Z/R;
                   a Touchstone 2 file stores them as they are (Enhancement-744) */
                if (version == 1 && param == 'y') {
                    re /= rbase;
                    im /= rbase;
                } else if (version == 1 && param == 'z') {
                    re *= rbase;
                    im *= rbase;
                }
                v->v_compdata[k].cx_real = re;
                v->v_compdata[k].cx_imag = im;
            }
            last->v_next = v;
            last = v;
        }
    }

    /* publish Rbase so the imported plot round-trips through wrsnp */
    {
        struct dvec *rv = dvec_alloc(copy("Rbase"), SV_NOTYPE, VF_REAL | VF_PERMANENT, 1, NULL);
        rv->v_plot = new;
        rv->v_realdata[0] = rbase;
        last->v_next = rv;
        last = rv;
    }
    /* Enhancement-744: a Touchstone 2 file's per-port references, as `Zref` */
    if (version == 2 && nzref == (size_t) nports) {
        struct dvec *zv = dvec_alloc(copy("Zref"), SV_NOTYPE, VF_REAL | VF_PERMANENT, nports, NULL);
        bool differ = FALSE;
        zv->v_plot = new;
        for (k = 0; k < nports; k++) {
            zv->v_realdata[k] = zref[(size_t) k];
            if (zref[(size_t) k] != zref[0])
                differ = TRUE;
        }
        last->v_next = zv;
        last = zv;
        if (differ)
            fprintf(stdout, "Note: %s gives every port its own reference impedance (the vector Zref); "
                            "Rbase is port 1's, and wrsnp, a Touchstone 1 writer, carries one value only\n", file);
    }

    fprintf(stdout, "%d-port %c-parameters (%d points) read from %s into plot '%s'%s\n",
            nports, toupper_c(param), npts, file, new->pl_typename,
            version == 2 ? " (Touchstone 2)" : "");
    netplot = new;

    /* Enhancement-749: the noise-parameter rows, a plot of their own (their
       frequencies are not the network data's): NFmin in dB, SOpt complex from
       its magnitude and angle, Rn in ohms (a v1 file stores it normalized to
       R, a v2 file absolute) -- the names the .sp noise analysis publishes.
       The network plot stays current. */
    if (nnz > 0) {
        int nn = (int) (nnz / 5);
        struct plot *np = plot_alloc("sp");
        struct dvec *fv, *nfv, *sov, *rnv;
        np->pl_name = tprintf("Touchstone noise import %s", file);
        np->pl_title = copy(file);
        plot_new(np);
        fv = dvec_alloc(copy("frequency"), SV_FREQUENCY, VF_REAL | VF_PERMANENT, nn, NULL);
        nfv = dvec_alloc(copy("NFmin"), SV_NOTYPE, VF_REAL | VF_PERMANENT, nn, NULL);
        sov = dvec_alloc(copy("SOpt"), SV_NOTYPE, VF_COMPLEX | VF_PERMANENT, nn, NULL);
        rnv = dvec_alloc(copy("Rn"), SV_NOTYPE, VF_REAL | VF_PERMANENT, nn, NULL);
        fv->v_plot = nfv->v_plot = sov->v_plot = rnv->v_plot = np;
        for (k = 0; k < nn; k++) {
            const double *row = nz + 5 * (size_t) k;
            fv->v_realdata[k] = row[0] * fscale;
            nfv->v_realdata[k] = row[1];
            sov->v_compdata[k].cx_real = row[2] * cos(row[3] * M_PI / 180.0);
            sov->v_compdata[k].cx_imag = row[2] * sin(row[3] * M_PI / 180.0);
            rnv->v_realdata[k] = (version == 1) ? row[4] * rbase : row[4];
        }
        np->pl_scale = np->pl_dvecs = fv;
        fv->v_next = nfv;
        nfv->v_next = sov;
        sov->v_next = rnv;
        fprintf(stdout, "%d noise-parameter point%s (NFmin, SOpt, Rn) read from %s into plot '%s'; plot '%s' stays current\n",
                nn, nn == 1 ? "" : "s", file, np->pl_typename, netplot->pl_typename);
        plot_setcur(netplot->pl_typename);
    }
    tfree(data);
    tfree(zref);
    tfree(nz);
    return;

bad:
    if (fp)
        (void) fclose(fp);
    tfree(line);
    tfree(data);
    tfree(zref);
    tfree(nz);
}


/* Enhancement-72: one complex value from an sp-plot vector. */
static void
spar_get(struct dvec *v, int k, double *re, double *im)
{
    if (isreal(v)) {
        *re = v->v_realdata[k];
        *im = 0.0;
    } else {
        *re = realpart(v->v_compdata[k]);
        *im = imagpart(v->v_compdata[k]);
    }
}

/* Enhancement-72: emit one network value in the requested Touchstone
   format (RI / MA / DB) after applying the v1 normalization for Y (x R)
   and Z (/ R) parameters. */
static void
spar_emit(FILE *fp, int prec, double re, double im, char fmt)
{
    if (fmt == 'r') {
        fprintf(fp, "  % .*e % .*e", prec, re, prec, im);
    } else {
        double mag = hypot(re, im);
        double ang = (mag > 0.0) ? atan2(im, re) * 180.0 / M_PI : 0.0;
        if (fmt == 'd')
            fprintf(fp, "  % .*e % .*e", prec,
                    20.0 * log10(mag > 0.0 ? mag : 1e-300), prec, ang);
        else
            fprintf(fp, "  % .*e % .*e", prec, mag, prec, ang);
    }
}

/* Enhancement-72: generalized Touchstone v1 writer -- any port count,
   RI/MA/DB formats, S/Y/Z parameters (Y/Z normalized to Rbase per the
   v1 spec), and Hz/kHz/MHz/GHz frequency units. The 2-port matrix uses
   the Touchstone-special S11 S21 S12 S22 column order on one line;
   N >= 3 is row-major with at most four pairs per data line and each
   matrix row on its own line; a 1-port is one pair per line. */
static void
spar_write_np(const char *file, int nports, double Rbaseval,
              char fmt, char param, double fscale, const char *funit)
{
    struct dvec *freqv = vec_get("frequency");
    struct dvec **sv;
    FILE *fp;
    int i, j, k, npts, prec, inrow;
    const char *fmt_str = (fmt == 'm') ? "MA" : (fmt == 'd') ? "DB" : "RI";
    char param_uc = (char) toupper_c(param);

    if (!freqv) {
        fprintf(stderr, "Error: no frequency vector (run a .sp analysis first)\n");
        return;
    }
    npts = freqv->v_length;
    prec = 6;

    sv = TMALLOC(struct dvec *, (size_t) (nports * nports));
    for (i = 0; i < nports; i++)
        for (j = 0; j < nports; j++) {
            char nb[40];
            (void) sprintf(nb, "%c_%d_%d", param_uc, i + 1, j + 1);
            sv[i * nports + j] = vec_get(nb);
            if (!sv[i * nports + j] || sv[i * nports + j]->v_length != npts) {
                fprintf(stderr, "Error: vector %s missing or of wrong length\n", nb);
                tfree(sv);
                return;
            }
        }

    if ((fp = fopen(file, "w")) == NULL) {
        perror(file);
        tfree(sv);
        return;
    }

    fprintf(fp, "!%d-port %c-parameter file\n", nports, param_uc);
    fprintf(fp, "!Title: %s\n", freqv->v_plot ? freqv->v_plot->pl_title : "");
    fprintf(fp, "!Generated by ngspice at %s\n",
            freqv->v_plot ? freqv->v_plot->pl_date : "");
    fprintf(fp, "# %s %c %s R %g\n", funit, param_uc, fmt_str, Rbaseval);
    if (nports == 2)
        fprintf(fp, "!freq  %c11  %c21  %c12  %c22  (%s pairs)\n",
                param_uc, param_uc, param_uc, param_uc, fmt_str);

    for (k = 0; k < npts; k++) {
        double f = isreal(freqv) ? freqv->v_realdata[k]
                                 : realpart(freqv->v_compdata[k]);
        fprintf(fp, "% .*e", prec, f / fscale);
        if (nports == 2) {
            /* Touchstone 2-port column order: 11, 21, 12, 22 */
            static const int order[4][2] = {{0, 0}, {1, 0}, {0, 1}, {1, 1}};
            int n;
            for (n = 0; n < 4; n++) {
                double re, im;
                spar_get(sv[order[n][0] * 2 + order[n][1]], k, &re, &im);
                if (param == 'y') {
                    re *= Rbaseval;
                    im *= Rbaseval;
                } else if (param == 'z') {
                    re /= Rbaseval;
                    im /= Rbaseval;
                }
                spar_emit(fp, prec, re, im, fmt);
            }
            fprintf(fp, "\n");
            continue;
        }
        for (i = 0; i < nports; i++) {
            if (i > 0)
                fprintf(fp, "%*s", prec + 9, "");   /* align continuation rows */
            inrow = 0;
            for (j = 0; j < nports; j++) {
                double re, im;
                spar_get(sv[i * nports + j], k, &re, &im);
                if (param == 'y') {
                    re *= Rbaseval;
                    im *= Rbaseval;
                } else if (param == 'z') {
                    re /= Rbaseval;
                    im /= Rbaseval;
                }
                if (inrow == 4) {           /* max 4 pairs per line */
                    fprintf(fp, "\n%*s", prec + 9, "");
                    inrow = 0;
                }
                spar_emit(fp, prec, re, im, fmt);
                inrow++;
            }
            fprintf(fp, "\n");             /* each matrix row on its own line */
        }
    }

    (void) fclose(fp);
    fprintf(stdout, "%d-port %c-parameters written to %s (%s, %s)\n",
            nports, param_uc, file, fmt_str, funit);
    tfree(sv);
}


/* Write scattering parameters into a file with Touchstone File Format Version 1
   with command wrs2p file (2 ports) or wrsnp file (any port count).
   Format info from http://www.eda.org/ibis/touchstone_ver2.0/touchstone_ver2_0.pdf
   See example 13 on page 15: Two port, ASCII, real-imaginary
   Check if S_1_1, S_2_1, S_1_2, S_2_2 and frequency vectors are available
   Check if vector Rbase is available (the .sp analysis publishes it since
   Enhancement-64, so no manual `let Rbase = ...` is needed anymore)
   Call spar_write() (2-port) or spar_write_np() (N-port)
*/

void
com_write_sparam(wordlist *wl)
{
    char *file;
    char *sbuf[6];
    wordlist *wl_sparam;
    struct pnode *pn;
    struct dvec *d, *vecs = NULL, *lv = NULL, *end, *vv, *Rbasevec = NULL;
    struct pnode *names;
    bool scalefound;
    struct plot *tpl, newplot;
    double Rbaseval;

    int nports = 0;
    /* Enhancement-72: output options -- format (ri|ma|db), parameter
       (s|y|z) and frequency unit (hz|khz|mhz|ghz), any order after the
       file name. Defaults preserve the classic wrs2p output exactly. */
    char fmt = 'r', param = 's';
    double fscale = 1.0;
    const char *funit = "Hz";
    bool have_opts = FALSE;

    if (wl)
        file = wl->wl_word;
    else
        file = "s_param.s2p";

    if (wl) {
        wordlist *w;
        for (w = wl->wl_next; w; w = w->wl_next) {
            char *t = w->wl_word;
            if (cieq(t, "ri") || cieq(t, "ma") || cieq(t, "db")) {
                fmt = (char) tolower_c(t[0]);   /* 'r' | 'm' | 'd' */
                have_opts = TRUE;
            } else if (cieq(t, "s") || cieq(t, "y") || cieq(t, "z")) {
                param = (char) tolower_c(t[0]);
                have_opts = TRUE;
            } else if (cieq(t, "hz")) {
                fscale = 1.0; funit = "Hz"; have_opts = TRUE;
            } else if (cieq(t, "khz")) {
                fscale = 1e3; funit = "kHz"; have_opts = TRUE;
            } else if (cieq(t, "mhz")) {
                fscale = 1e6; funit = "MHz"; have_opts = TRUE;
            } else if (cieq(t, "ghz")) {
                fscale = 1e9; funit = "GHz"; have_opts = TRUE;
            } else {
                fprintf(stderr,
                        "Error: unknown wrsnp option '%s' (expected ri|ma|db, s|y|z, hz|khz|mhz|ghz)\n",
                        t);
                return;
            }
        }
    }

    /* Enhancement-64: how many ports does the current sp plot hold? */
    while (nports < 99) {
        char nb[40];
        (void) sprintf(nb, "S_%d_%d", nports + 1, nports + 1);
        if (!vec_get(nb))
            break;
        nports++;
    }
    if (nports == 0) {
        fprintf(stderr, "Error: no S-parameter vectors found (run a .sp analysis first)\n");
        return;
    }

    /* Enhancement-64: the sp analysis publishes Rbase (the ports'
       reference resistance); a user-defined `let Rbase = ...` still
       overrides. The sp plot is complex, so read either data form. */
    Rbasevec = vec_get("Rbase");
    if (Rbasevec) {
        Rbaseval = isreal(Rbasevec) ? Rbasevec->v_realdata[0]
                                    : realpart(Rbasevec->v_compdata[0]);
    } else {
        fprintf(stderr, "Error: No Rbase vector given\n");
        return;
    }

    if (nports != 2 || have_opts) {
        spar_write_np(file, nports, Rbaseval, fmt, param, fscale, funit);
        return;
    }

    /* generate wordlist with all vectors required*/
    sbuf[0] = "frequency";
    sbuf[1] = "S_1_1";
    sbuf[2] = "S_2_1";
    sbuf[3] = "S_1_2";
    sbuf[4] = "S_2_2";
    sbuf[5] = NULL;
    wl_sparam = wl_build((const char * const *) sbuf);

    names = ft_getpnames(wl_sparam, TRUE);
    if (names == NULL)
        goto done;

    for (pn = names; pn; pn = pn->pn_next) {
        d = ft_evaluate(pn);
        if (!d)
            goto done;

        if (vecs)
            lv->v_link2 = d;
        else
            vecs = d;

        for (lv = d; lv->v_link2; lv = lv->v_link2)
            ;
    }

    /* Now we have to write them out plot by plot. */

    while (vecs) {
        tpl = vecs->v_plot;
        tpl->pl_written = TRUE;
        end = NULL;
        memcpy(&newplot, tpl, sizeof(struct plot));
        scalefound = FALSE;

        /* Figure out how many vectors are in this plot. Also look
         * for the scale, or a copy of it, which may have a different
         * name.
         */
        for (d = vecs; d; d = d->v_link2) {
            if (d->v_plot == tpl) {
                char *basename = vec_basename(d);
                vv = vec_copy(d);
                /* Note that since we are building a new plot
                 * we don't want to vec_new this one...
                 */
                tfree(vv->v_name);
                vv->v_name = basename;

                if (end)
                    end->v_next = vv;
                else
                    end = newplot.pl_dvecs = vv;
                end = vv;

                if (vec_eq(d, tpl->pl_scale)) {
                    newplot.pl_scale = vv;
                    scalefound = TRUE;
                }
            }
        }
        end->v_next = NULL;

        /* Maybe we shouldn't make sure that the default scale is
         * present if nobody uses it.
         */
        if (!scalefound) {
            newplot.pl_scale = vec_copy(tpl->pl_scale);
            newplot.pl_scale->v_next = newplot.pl_dvecs;
            newplot.pl_dvecs = newplot.pl_scale;
        }

        /* Now let's go through and make sure that everything that
         * has its own scale has it in the plot.
         */
        for (;;) {
            scalefound = FALSE;
            for (d = newplot.pl_dvecs; d; d = d->v_next) {
                if (d->v_scale) {
                    for (vv = newplot.pl_dvecs; vv; vv = vv->v_next)
                        if (vec_eq(vv, d->v_scale))
                            break;
                    if (!vv) {
                        /* We have to grab it... */
                        vv = vec_copy(d->v_scale);
                        vv->v_next = newplot.pl_dvecs;
                        newplot.pl_dvecs = vv;
                        scalefound = TRUE;
                    }
                }
            }
            if (!scalefound)
                break;
            /* Otherwise loop through again... */
        }

        spar_write(file, &newplot, Rbaseval);

        for (vv = newplot.pl_dvecs; vv;) {
            struct dvec *next_vv = vv->v_next;
            vv->v_plot = NULL;
            vec_free(vv);
            vv = next_vv;
        }

        /* Now throw out the vectors we have written already... */
        for (d = vecs, lv = NULL;  d; d = d->v_link2)
            if (d->v_plot == tpl) {
                if (lv) {
                    lv->v_link2 = d->v_link2;
                    d = lv;
                } else {
                    vecs = d->v_link2;
                }
            } else {
                lv = d;
            }
    }

done:
    free_pnode(names);
    wl_free(wl_sparam);
}


/* If the named vectors have more than 1 dimension, then consider
 * to be a collection of one or more matrices.  This command transposes
 * each named matrix.
 */
void
com_transpose(wordlist *wl)
{
    struct dvec *d;
    char *s;

    /* For each vector named in the wordlist, perform the transform to
     * it and the vectors associated with it through v_link2 */
    for ( ; wl != (wordlist *) NULL; wl = wl->wl_next) {
        s = cp_unquote(wl->wl_word);
        d = vec_get(s);
        tfree(s); /*DG: Avoid Memory Leak */
        if (d == NULL) {
            /* Print error message, but continue with other vectors */
            fprintf(cp_err, "Error: no such vector as %s.\n", wl->wl_word);
       }
        else {
            /* Transpose the named vector and vectors tied to it
             * through v_link2 */
            while (d) {
                vec_transpose(d);
                d = d->v_link2;
            }
        }
    } /* end of loop over words in wordlist */
} /* end of function com_transpose */



/* Take a set of vectors and form a new vector of the nth elements of each. */
void
com_cross(wordlist *wl)
{
    char *newvec, *s;
    struct dvec *n, *v, *vecs = NULL, *lv = NULL;
    struct pnode *pn, *names;
    int i, ind;
    bool comp = FALSE;

    newvec = wl->wl_word;
    wl = wl->wl_next;
    s = wl->wl_word;

    {
        double val;
        if (ft_numparse(&s, FALSE, &val) <= 0) {
            fprintf(cp_err, "Error: bad index value %s\n", wl->wl_word);
            return;
        }
        if ((ind = (int) val) < 0) {
            fprintf(cp_err, "Error: badstrchr %d\n", ind);
            return;
        }
    }

    wl = wl->wl_next;
    names = ft_getpnames(wl, TRUE);
    for (pn = names; pn; pn = pn->pn_next) {
        if ((n = ft_evaluate(pn)) == NULL)
            goto done;

        if (!vecs)
            vecs = lv = n;
        else
            lv->v_link2 = n;

        for (lv = n; lv->v_link2; lv = lv->v_link2)
            ;
    }

    for (n = vecs, i = 0; n; n = n->v_link2) {
        if (iscomplex(n))
            comp = TRUE;
        i++;
    }

    vec_remove(newvec);
    v = dvec_alloc(copy(newvec),
            (int) (vecs ? vecs->v_type : SV_NOTYPE),
            comp ? (VF_COMPLEX | VF_PERMANENT) : (VF_REAL | VF_PERMANENT),
            i, NULL);

    /* Now copy the ind'ths elements into this one. */
    for (n = vecs, i = 0; n; n = n->v_link2, i++)
        if (n->v_length > ind) {
            if (comp) {
                v->v_compdata[i] = n->v_compdata[ind];
            } else {
                v->v_realdata[i] = n->v_realdata[ind];
            }
        } else {
            if (comp) {
                realpart(v->v_compdata[i]) = 0.0;
                imagpart(v->v_compdata[i]) = 0.0;
            } else {
                v->v_realdata[i] = 0.0;
            }
        }
    vec_new(v);
    cp_addkword(CT_VECTOR, v->v_name);

done:
    free_pnode(names);
}

/* Free resources associated with "plot" datasets. The wordlist contains
 * the names of the plots to delete or the word "all" to delete all but the
 * default "const" plot, which cannot be deleted, even by name. If there are
 * no names given, the current plot is deleted */
void com_destroy(wordlist *wl)
{
    /* If no name given, delete the current output data */
    if (!wl) {
        DelPlotWindows(plot_cur);
        killplot(plot_cur);
    }
    else if (eq(wl->wl_word, "all")) { /* "all" -> all plots deleted */
        struct plot *pl, *npl = NULL;
        for (pl = plot_list; pl; pl = npl) {
            npl = pl->pl_next;
            if (!eq(pl->pl_typename, "const")) {
                DelPlotWindows(pl);
                killplot(pl);
            }
            else {
                plot_num = 1;
            }
        }
    }
    else { /* list of plots by name */
        while (wl) {
            struct plot *pl;
            for (pl = plot_list; pl; pl = pl->pl_next) {
                if (eq(pl->pl_typename, wl->wl_word)) {
                    break;
                }
            }
            if (pl) {
                DelPlotWindows(pl);
                killplot(pl);
            }
            else {
                fprintf(cp_err, "Error: no such plot %s\n", wl->wl_word);
            }
            wl = wl->wl_next;
        }
    }
} /* end of function com_destroy */



static void killplot(struct plot *pl)
{
    if (eq(pl->pl_typename, "const")) {
        fprintf(cp_err, "Error: can't destroy the constant plot\n");
        return;
    }
    /*  pl_dvecs, pl_scale */
    {
        struct dvec *v;
        struct dvec *nv;
        for (v = pl->pl_dvecs; v; v = nv) {
            nv = v->v_next;
            vec_free(v);
        }
    }

    /* Enhancement-345: release the name before unlinking, so a number freed
     * here can be handed out again exactly as it was before the index existed */
    plot_forget(pl);

    /* unlink from plot_list (linked via pl_next) */
    if (pl == plot_list) { /* First in list */
        plot_list = pl->pl_next;
        if (pl == plot_cur) {
            plot_cur = plot_list;
        }
    }
    else { /* inside list */
        struct plot *op;
        for (op = plot_list; op; op = op->pl_next) {
            if (op->pl_next == pl) {
                break;
            }
        }
        if (!op) {
            fprintf(cp_err,
                    "Internal Error: kill plot -- not in list\n");
            return;
        }
        op->pl_next = pl->pl_next;
        if (pl == plot_cur) {
            plot_cur = op;
        }
    }
    /* delete the hash table entry for this plot */
    if (pl->pl_lookup_table) {
        nghash_free(pl->pl_lookup_table, NULL, NULL);
        pl->pl_lookup_table = NULL;
    }
    txfree(pl->pl_title);
    txfree(pl->pl_name);
    txfree(pl->pl_typename);
    txfree(pl->pl_kind);                        /* Enhancement-666 */
    wl_free(pl->pl_commands);
    txfree(pl->pl_date); /* va: also tfree (memory leak) */
    if (pl->pl_ccom)  { /* va: also tfree (memory leak) */
        throwaway(pl->pl_ccom);
    }

    if (pl->pl_env) { /* The 'environment' for this plot. */
        /* va: HOW to do? */
        printf("va: killplot should tfree pl->pl_env=(%p)\n", pl->pl_env);
        fflush(stdout);
    }
    txfree(pl); /* va: also tfree pl itself (memory leak) */
}

/* delete the const plot (called from com_quit) */
void
destroy_const_plot(void)
{
    struct dvec *v, *nv = NULL;
    struct plot *pl = &constantplot;

    /*  pl_dvecs, pl_scale */
    for (v = pl->pl_dvecs; v; v = nv) {
        nv = v->v_next;
        vec_free(v);
    }
    /* delete the hash table entry for the const plot */
    if (pl->pl_lookup_table) {
        nghash_free(pl->pl_lookup_table, NULL, NULL);
        pl->pl_lookup_table = NULL;
    }
    wl_free(pl->pl_commands);
    if (pl->pl_ccom)    /* va: also tfree (memory leak) */
        throwaway(pl->pl_ccom);

    if (pl->pl_env) { /* The 'environment' for this plot. */
        /* va: HOW to do? */
        printf("va: killplot should tfree pl->pl_env=(%p)\n", pl->pl_env);
        fflush(stdout);
    }
}


/* delete all windows with graphs dedrived from a given plot */
static void
DelPlotWindows(struct plot *pl)
{
    /* do this only if windows or X11 is defined */
#if defined(HAS_WINGUI) || !defined(X_DISPLAY_MISSING)
    GRAPH *dgraph;
    int n;
    /* find and remove all graph structures derived from a given plot */
    for (n = 1; n < 100; n++) { /* should be no more than 100 */
        dgraph = FindGraph(n);
        if (dgraph) {
            if (ciprefix(pl->pl_typename, dgraph->plotname))
                RemoveWindow(dgraph);
        }
        /* We have to run through all potential graph ids. If some numbers are
           already missing, 'else break;' might miss the plotwindow to be removed. */
        /* else
           break;
        */
    }
#else
    NG_IGNORE(pl);
#endif
}


/*
 * command 'setplot'
 *   print a list of plots available
 * command 'setplot <plotname>'
 *   make <plotname> the current plot
 * command 'setplot new'
 *   create a new plot
 */

void
com_splot(wordlist *wl)
{
    struct plot *pl;

    if (wl) {
        plot_setcur(wl->wl_word);
        return;
    }

    fprintf(cp_out, "List of plots available:\n\n");
    for (pl = plot_list; pl; pl = pl->pl_next)
        fprintf(cp_out, "%s%s\t%s (%s)\n",
                (pl == plot_cur) ? "Current " : "\t",
                pl->pl_typename, pl->pl_title, pl->pl_name);
}
