/**********
Copyright 1990 Regents of the University of California.  All rights reserved.
Author: 1985 Wayne A. Christopher, U. C. Berkeley CAD Group
**********/

/*
 * Line-printer (ASCII) plots.
 */

#include "ngspice/ngspice.h"
#include <float.h>
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dvec.h"
#include "ngspice/fteparse.h"
#include "agraf.h"


#define FUDGE           7
#define MARGIN_BASE     11
#define LCHAR           '.'
#define MCHAR           'X'
#define PCHARS          "+*=$%!0123456789"

/* We should really deal with the xlog and delta arguments.  This routine is
 * full of magic numbers that make the formatting correct.
 */



/* Enhancement-283: floor() a base-10 exponent into an int, tolerating the
 * non-finite results mylog10() returns for inf / 0 / denormal data. DBL_MAX_10_EXP
 * bounds any decade a double can actually represent. */
static int
agraf_int(double v)
{
    if (v != v)                         /* NaN */
        return 0;
    if (v >=  (double) INT_MAX)
        return INT_MAX;
    if (v <= -(double) INT_MAX)
        return -INT_MAX;
    return (int) v;
}

static int
agraf_decade(double lg)
{
    if (lg != lg)                       /* NaN */
        return 0;
    if (lg >  (double) DBL_MAX_10_EXP)
        return DBL_MAX_10_EXP;
    if (lg < -(double) DBL_MAX_10_EXP)
        return -DBL_MAX_10_EXP;
    return (int) floor(lg);
}

void
ft_agraf(double *xlims, double *ylims, struct dvec *xscale, struct plot *plot, struct dvec *vecs, double xdel, double ydel, bool xlog, bool ylog, bool nointerp)
{
    int height;
    bool nobreakp, novalue;
    int maxx, maxy, omaxy;  /* The size of the plotting area. */
    bool /* xlogscale = FALSE, */ ylogscale = FALSE;
    char *field, buf[BSIZE_SP];
    char *line1, *line2, c, cb;
    double xrange[2], yrange[2], x1, x2, yy1, y2, x, y;
    int mag, hmt, lmt, dst, spacing, nsp, ypt, upper, lower, curline;
    double tenpowmag, diff;
    double *values = NULL;
    struct dvec *v;
    int margin = MARGIN_BASE;
    int omargin;
    int i, j, k;
    int shift;
    int line_end;   /* Enhancement-282: index of the '\0' in line1/line2 */

    NG_IGNORE(xdel);
    NG_IGNORE(ydel);
    NG_IGNORE(ylog);

    /* ANSI C does not specify how many digits are in an exponent for %c
     * We assumed it was 2.  If it's more, shift starting position over.
     */
    sprintf(buf, "%1.1e", 0.0);         /* expect 0.0e+00 */
    shift = (int) strlen(buf) - 7;
    margin += shift;

    /* Make sure the margin is correct */
    omargin = margin;
    novalue = cp_getvar("noasciiplotvalue", CP_BOOL, NULL, 0);
    if (!novalue && !vec_eq(xscale, vecs))
        margin *= 2;
    else
        novalue = TRUE;

    if ((xscale->v_gridtype == GRID_YLOG) || (xscale->v_gridtype == GRID_LOGLOG))
        ylogscale = TRUE;

    if (!cp_getvar("width", CP_NUM, &maxy, 0))
        maxy = DEF_WIDTH;

    if (!cp_getvar("height", CP_NUM, &height, 0))
        height = DEF_HEIGHT;

    if (ft_nopage)
        nobreakp = TRUE;
    else
        nobreakp = cp_getvar("nobreak", CP_BOOL, NULL, 0);

    maxy -= (margin + FUDGE);
    maxx = xscale->v_length;

    xrange[0] = xlims[0];
    xrange[1] = xlims[1];
    yrange[0] = ylims[0];
    yrange[1] = ylims[1];

    if (maxx <= 0) {
        fprintf(cp_err, "Note: no points to plot\n");
        return;
    }

    for (v = vecs, i = 0; v; v = v->v_link2)
        v->v_linestyle = (PCHARS[i] ? PCHARS[i++] : '#');

    /* Now allocate the field and stuff. */
    field = TMALLOC(char, (maxy + 1) * (maxx + 1));
    /* Enhancement-282: remember the buffer bound now -- `maxy` is reassigned
     * below, so this cannot be recomputed at the label loop. */
    line_end = maxy + margin + FUDGE;
    line1 = TMALLOC(char, line_end + 1);
    line2 = TMALLOC(char, line_end + 1);
    if (!novalue)
        values = TMALLOC(double, maxx);

    /* Clear the field, put the lines in the right places, and create
     * the headers.
     */
    for (i = 0, j = (maxx + 1) * (maxy + 1); i < j; i++)
        field[i] = ' ';
    for (i = 0, j = line_end; i < j; i++) {
        line1[i] = '-';
        line2[i] = ' ';
    }
    line1[j] = line2[j] = '\0';

    /* The following is similar to the stuff in grid.c */
    if ((xrange[0] > xrange[1]) || (yrange[0] > yrange[1])) {
        fprintf(cp_err,
                "ft_agraf: Internal Error: bad limits %g, %g, %g, %g\n",
                xrange[0], xrange[1], yrange[0], yrange[1]);
        return;
    }

    /* gcc doesn't like !double */
    /* Enhancement-283: mylog10() here can be +/-inf or NaN -- the data may overflow
     * to inf (e.g. -1e308 * 6), or be zero/denormal -- and (int) of a non-finite
     * double is undefined behaviour. Sanitize the exponent to a representable
     * decade before the cast. */
    if (ylims[1] == 0.0) {
        mag = agraf_decade(mylog10(- ylims[0]));
        tenpowmag = pow(10.0, (double) mag);
    } else if (ylims[0] == 0.0) {
        mag = agraf_decade(mylog10(ylims[1]));
        tenpowmag = pow(10.0, (double) mag);
    } else {
        diff = ylims[1] - ylims[0];
        mag = agraf_decade(mylog10(diff));
        tenpowmag = pow(10.0, (double) mag);
    }

    /* Enhancement-283: tenpowmag can be 0 or inf for extreme data, making these
     * ratios non-finite; (int) of that is undefined behaviour. */
    lmt = agraf_int(floor(ylims[0] / tenpowmag));
    yrange[0] = ylims[0] = lmt * tenpowmag;
    hmt = agraf_int(ceil(ylims[1] / tenpowmag));
    yrange[1] = ylims[1] = hmt * tenpowmag;

    dst = hmt - lmt;

    /* This is a strange case; I don't know why it's here. */
    if (dst == 11) {
        dst = 12;
    } else if (dst == 1) {
        dst = 10;
        mag++;
        hmt *= 10;
        lmt *= 10;
    } else if (dst == 0) {
        dst = 2;
        lmt -= 1;
        hmt += 1;
    }

    for (nsp = 4; nsp < 8; nsp++)
        if (!(dst % nsp))
            break;
    if (nsp == 8)
        for (nsp = 2; nsp < 4; nsp++)
            if (!(dst % nsp))
                break;
    spacing = maxy / nsp;

    /* Reset the max X coordinate to deal with round-off error. */
    omaxy = maxy + 1;
    maxy = spacing * nsp;

    for (i = 0, j = lmt; j <= hmt; i += spacing, j += dst / nsp) {
        for (k = 0; k < maxx; k++)
            field[k * omaxy + i] = LCHAR;
        line1[i + margin + 2 * shift] = '|';
        (void) sprintf(buf, "%.2e", j * pow(10.0, (double) mag));
        /* Enhancement-282: `shift` above is measured by formatting 0.0, which
         * always has a 2-digit exponent, so a label with a 3-DIGIT exponent
         * ("1.00e-320", from denormal data) is one char longer than the FUDGE pad
         * allows. The last label then overwrote line2's terminating '\0' and the
         * printf of line2 read past the buffer. Clamp the copy to the buffer. */
        {
            int off = i + margin - ((j < 0) ? 2 : 1) - shift;
            int n = (int) strlen(buf);
            if (off < 0) {
                n += off;
                off = 0;
            }
            if (off + n > line_end)
                n = line_end - off;
            if (n > 0)
                memcpy(&line2[off], buf, (size_t) n);
        }
    }
    line1[i - spacing + margin + 1] = '\0';
    line2[line_end] = '\0';   /* Enhancement-282: keep line2 terminated */

    for (i = 1; i < omargin - 1 && xscale->v_name[i - 1]; i++)
        line2[i] = xscale->v_name[i - 1];
    if (!novalue)
        for (i = omargin + 1;
             i < margin - 2 && (vecs->v_name[i - omargin - 1]);
             i++)
            line2[i] = vecs->v_name[i - omargin - 1];

    /* Now the buffers are all set up properly. Plot points for each
     * vector using interpolation. For each point on the x-axis, find the
     * two bracketing points in xscale, and then interpolate their
     * y values for each vector.
     */

    upper = lower = 0;
    for (i = 0; i < maxx; i++) {
        if (nointerp)
            x = isreal(xscale) ? xscale->v_realdata[i] :
                realpart(xscale->v_compdata[i]);
        else if (xlog && xrange[0] > 0.0 && xrange[1] > 0.0)
            x = xrange[0] * pow(10.0, mylog10(xrange[1]/xrange[0])
                                 * i / (maxx - 1));
        else
            x = xrange[0] + (xrange[1] - xrange[0]) * i /
                (maxx - 1);
        while ((isreal(xscale) ? (xscale->v_realdata[upper] < x) :
                (realpart(xscale->v_compdata[upper]) < x)) &&
               (upper < xscale->v_length - 1))
            upper++;
        while ((isreal(xscale) ? (xscale->v_realdata[lower] < x) :
                (realpart(xscale->v_compdata[lower]) < x)) &&
               (lower < xscale->v_length - 1))
            lower++;
        if ((isreal(xscale) ? (xscale->v_realdata[lower] > x) :
             (realpart(xscale->v_compdata[lower]) > x)) &&
            (lower > 0))
            lower--;
        x1 = (isreal(xscale) ? xscale->v_realdata[lower] :
              realpart(xscale->v_compdata[lower]));
        x2 = (isreal(xscale) ? xscale->v_realdata[upper] :
              realpart(xscale->v_compdata[upper]));
        if (x1 > x2) {
            fprintf(cp_err, "Error: X scale (%s) not monotonic\n",
                    xscale->v_name);
            return;
        }
        for (v = vecs; v; v = v->v_link2) {
            /* Enhancement-285: `lower`/`upper` are bracketing indices into the
             * X SCALE and are bounded by xscale->v_length, but they index the
             * VECTOR here. A vector shorter than its scale -- a synthetic vector
             * (`let y = vector(8)`) carries the plot's much longer scale -- was
             * therefore read past its end. Clamp to this vector's own length. */
            int lo = lower, up = upper;
            if (lo >= v->v_length) lo = v->v_length - 1;
            if (up >= v->v_length) up = v->v_length - 1;
            if (lo < 0) lo = 0;
            if (up < 0) up = 0;
            yy1 = (isreal(v) ? v->v_realdata[lo] :
                   realpart(v->v_compdata[lo]));
            y2 = (isreal(v) ? v->v_realdata[up] :
                  realpart(v->v_compdata[up]));
            if (x1 == x2)
                y = yy1;
            else
                y = yy1 + (y2 - yy1) * (x - x1) / (x2 - x1);
            if (!novalue && (v == vecs))
                values[i] = y;
            ypt = ft_findpoint(y, yrange, maxy, 0, ylogscale);
            c = field[omaxy * i + ypt];
            if ((c == ' ') || (c == LCHAR))
                field[omaxy * i + ypt] = (char) v->v_linestyle;
            else
                field[omaxy * i + ypt] = MCHAR;
        }
    }

    out_init();
    for (i = 0; i < omaxy + margin; i++)
        out_send("-");
    out_send("\n");
    i = (omaxy + margin - (int) strlen(plot->pl_title)) / 2;
    while (i-- > 0)
        out_send(" ");
    (void) strcpy(buf, plot->pl_title);
    buf[maxy + margin] = '\0';  /* Cut off if too wide */
    out_send(buf);
    out_send("\n");
    (void) sprintf(buf, "%s %s", plot->pl_name, plot->pl_date);
    buf[maxy + margin] = '\0';
    i = (omaxy + margin - (int) strlen(buf)) / 2;
    while (i-- > 0)
        out_send(" ");
    out_send(buf);
    out_send("\n\n");
    curline = 7;
    out_send("Legend:  ");
    i = 0;
    j = (maxx + margin - 8) / 20;

    if (j == 0)
        j = 1;

    for (v = vecs; v; v = v->v_link2) {
        out_printf("%c = %-17s", (char) v->v_linestyle, v->v_name);
        if (!(++i % j) && v->v_link2) {
            out_send("\n         ");
            curline++;
        }
    }
    out_send("\n");

    for (i = 0; i < omaxy + margin; i++)
        out_send("-");
    out_send("\n");
    i = 0;
    out_printf("%s\n%s\n", line2, line1);
    curline += 2;

    for (i = 0; i < maxx; i++) {
        if (nointerp)
            x = isreal(xscale) ? xscale->v_realdata[i] :
            realpart(xscale->v_compdata[i]);
        else if (xlog && xrange[0] > 0.0 && xrange[1] > 0.0)
            if (maxx == 1)
                x = (xrange[0] + xrange[1]) / 2.;
            else
                x = xrange[0] * pow(10.0, mylog10(xrange[1] / xrange[0])
                    * i / (maxx - 1));
        else
            if (maxx == 1)
                x = (xrange[0] + xrange[1]) / 2.;
            else
                x = xrange[0] + (xrange[1] - xrange[0]) * i / (maxx - 1);

        if (x < 0.0)
            out_printf("%.3e ", x);
        else
            out_printf(" %.3e ", x);

        if (!novalue) {
            if (values[i] < 0.0)
                out_printf("%.3e ", values[i]);
            else
                out_printf(" %.3e ", values[i]);
        }

        cb = field[(i + 1) * omaxy];
        field[(i + 1) * omaxy] = '\0';
        out_send(&field[i * omaxy]);
        field[(i + 1) * omaxy] = cb;
        out_send("\n");

        if (((curline++ % height) == 0) && (i < maxx - 1) && !nobreakp) {
            out_printf("%s\n%s\n\014\n%s\n%s\n",
                       line1, line2, line2, line1);
            curline += 5;
        }
    }

    out_printf("%s\n%s\n", line1, line2);

    txfree(field);
    txfree(line1);
    txfree(line2);
    if (!novalue)
        txfree(values);
}
