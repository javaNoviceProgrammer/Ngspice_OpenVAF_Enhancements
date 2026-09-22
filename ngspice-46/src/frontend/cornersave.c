/* Enhancement-701: `.option savecorner[=csv|txt|excel|<file>]` -- the corner
 * runs of a circuit whose Verilog-A models declare process corners
 * (Enhancement-654's `(* corner="ss=..., ff=..." *)`), one row per corner
 * run, in a file beside the netlist. Requested by the user as the corner
 * twin of `.option savemc` (Enhancement-610): where savemc keys its rows by
 * trial, this file keys them by CORNER.
 *
 * A row is `corner`, `analysis`, `status` (ok / failed / paused), then the
 * value in force of every cornered parameter -- each parameter carrying a
 * `corner` attribute, read off the devices when the row is made, as
 * `@<model>[<param>]` for a model parameter and `@<instance>[<param>]` for an
 * instance one: the corner's value under a corner, the nominal at `tt` --
 * then what the run computed: the `corners -output` values, `writemc`'s (on
 * an autocorner combined plot, evaluated on every corner's own plot and put
 * on that corner's row, Enhancement-666's rule), and under `corners -mc N`
 * the montecarlo's yield, npass, nsamples and nfailed.
 *
 * Which runs are corner runs: every run-class command (`op`, `tran`, `run`,
 * ... -- what if_run dispatches) that is not a sample of a loop command --
 * a plain run at the deck's `.option corner=<name>` (or at `tt` without
 * one), each corner of an `.option autocorner` pass, each corner of the
 * `corners` command. Inside `montecarlo`, `sweep`, `optimize`, `wcd` and
 * `highsigma` the runs are the loop's samples and make no rows (savemc
 * records those); `corners -mc N` adds one summary row per corner instead.
 *
 * The file is `corners_<date>_<time>.<ext>` in the netlist's directory, or
 * the name the option gives; csv by default, `txt` tab-separated, `excel` a
 * genuine .xlsx sharing savemc's writer and font options (`savecorner_font`,
 * `savecorner_fontsize`, `savecorner_model`, `savecorner_instance`,
 * `savecorner_output`, each falling back to the savemc one). One file per
 * circuit: a `reset` continues it, a different deck starts its own;
 * `nosavecorner` turns it off. A circuit no loaded model of which declares a
 * corner has nothing to record, said once. */

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dstring.h"
#include "ngspice/osdiitf.h"
#include "ngspice/dvec.h"
#include "ngspice/fteext.h"       /* outp_loop_label_now */
#include "ngspice/randnumb.h"     /* mc_wcd_active */
#include "mcsave.h"
#include "cornersave.h"
#include <math.h>
#include <errno.h>
#ifdef HAVE_UNISTD_H
#include <unistd.h>         /* ftruncate */
#endif
#ifdef _MSC_VER
#include <io.h>
#define ftruncate(fd, len) _chsize(fd, (long) (len))
#endif

struct cs_col {
    char *name;
    int model;                      /* a model card's parameter (bold in the workbook) */
    int written;                    /* a value put on the row after the run (blue) */
    double value;                   /* the value in force, for the row being made */
    int set;
};

static struct cs_col *cols;
static int ncols, capcols;

static double **rows;               /* nrows x (columns at the time), NAN = not seen */
static int *rowcols;
static char **rowcn;                /* the corner */
static char **rowan;                /* the analysis */
static char **rowst;                /* ok / failed / paused */
static struct plot **rowplot;       /* the plot the row's run made (identity only) */
static char **rowpl;                /* ... its name, for the messages */
static int nrows, caprows;
static struct plot *plot_before;    /* plot_cur when the run began */
static int hold_depth;              /* CSAVEhold: the runs are a loop's samples */

static char *owner_file, *owner_name;
static int owner;
static char *path;
static int fmt;
static FILE *fp;                    /* csv/txt: kept open, appended */
static int header_cols;
static long lastrow_off = -1;
static int noted_nothing;
static int unwritable;
static int noted_write_fail;

/* ------------------------------------------------------------ the columns */

static struct cs_col *
col_find(const char *name)
{
    int i;
    for (i = 0; i < ncols; i++)
        if (eq(cols[i].name, name))
            return &cols[i];
    return NULL;
}

static struct cs_col *
col_add(const char *name, int model)
{
    if (ncols == capcols) {
        capcols = capcols ? 2 * capcols : 16;
        cols = TREALLOC(struct cs_col, cols, capcols);
    }
    memset(&cols[ncols], 0, sizeof cols[ncols]);
    cols[ncols].name = copy(name);
    cols[ncols].model = model;
    return &cols[ncols++];
}

static void
col_set(const char *name, double value, int model)
{
    struct cs_col *c = col_find(name);
    if (!c)
        c = col_add(name, model);
    c->value = value;
    c->set = 1;
}

static void
cols_clear_values(void)
{
    int i;
    for (i = 0; i < ncols; i++)
        cols[i].set = 0;
}

static void
cols_free(void)
{
    int i;
    for (i = 0; i < ncols; i++)
        tfree(cols[i].name);
    tfree(cols);
    ncols = capcols = 0;
}

/* ctx: non-NULL for a `corners -mc` summary row, whose montecarlo drew every
 * parameter with statistics the corner does not hold -- the row stands for
 * the whole sample, so that cell is left empty rather than showing the last
 * draw (as savemc's Enhancement-626 leaves a swept cell empty) */
static void
snapshot_cb(const OSDImcSnapshotItem *it, void *ctx)
{
    char *name = tprintf("@%s[%s]", it->owner, it->param);
    double v = it->value;
    if (ctx && it->has_stats && !it->held && OSDImcEnabled())
        v = NAN;
    /* Enhancement-626's rule, as savemc applies it: a run that swept the
     * parameter itself (`dc @rm[rsh] 90 110 10`, a `sweep` fast path) wrote
     * it once per level and once to restore -- the device ran at each level,
     * not at a corner's value, so that cell is empty too */
    if (it->writes > 1)
        v = NAN;
    col_set(name, v, it->is_model);
    tfree(name);
}

/* ------------------------------------------------------------ the option */

static int
cs_option(char **given)
{
    char val[BSIZE_SP];
    int on = 0;

    *given = NULL;
    fmt = MCS_FMT_CSV;
    if (cp_getvar("savecorner", CP_STRING, val, sizeof val)) {
        on = 1;
    } else if (cp_getvar("savecorner", CP_BOOL, NULL, 0)) {
        on = 1;
        val[0] = '\0';
    }
    if (!on || cp_getvar("nosavecorner", CP_BOOL, NULL, 0))
        return 0;
    fmt = MCSAVEparseFormat("savecorner", val, given);
    return 1;
}

int
CSAVEactive(void)
{
    char *given = NULL;
    int on = cs_option(&given);
    tfree(given);
    return on;
}

static void
cs_note_write_fail(void)
{
    if (noted_write_fail)
        return;
    fprintf(cp_err, "Error: savecorner: cannot write %s (%s); the rows so far are kept and "
                    "written when the file can be opened again\n",
            path, strerror(errno));
    noted_write_fail = 1;
}

/* ------------------------------------------------------------ csv / txt */

static void
text_header(FILE *f)
{
    const char sep = fmt == MCS_FMT_CSV ? ',' : '\t';
    int i;
    fprintf(f, "corner%canalysis%cstatus", sep, sep);
    for (i = 0; i < ncols; i++) {
        putc(sep, f);
        MCSAVEputName(f, cols[i].name, fmt == MCS_FMT_CSV);
    }
    putc('\n', f);
    header_cols = ncols;
}

static void
text_row(FILE *f, int r)
{
    const char sep = fmt == MCS_FMT_CSV ? ',' : '\t';
    int i;
    MCSAVEputName(f, rowcn[r], fmt == MCS_FMT_CSV);
    putc(sep, f);
    MCSAVEputName(f, rowan[r], fmt == MCS_FMT_CSV);   /* a montecarlo command line may hold commas */
    putc(sep, f);
    MCSAVEputName(f, rowst[r], fmt == MCS_FMT_CSV);
    for (i = 0; i < ncols; i++) {
        putc(sep, f);
        MCSAVEputValue(f, i < rowcols[r] ? rows[r][i] : NAN);
    }
    putc('\n', f);
}

static void
text_rewrite(void)
{
    int r;
    if (fp)
        fclose(fp);
    fp = fopen(path, "w");
    if (!fp) {
        cs_note_write_fail();
        return;
    }
    noted_write_fail = 0;
    text_header(fp);
    for (r = 0; r < nrows; r++) {
        if (r == nrows - 1)
            lastrow_off = ftell(fp);
        text_row(fp, r);
    }
    fflush(fp);
}

static void
text_rewrite_last(void)
{
    if (fp && lastrow_off >= 0 && header_cols == ncols &&
        fseek(fp, lastrow_off, SEEK_SET) == 0) {
        int fd = fileno(fp);
        if (ftruncate(fd, lastrow_off) == 0) {
            text_row(fp, nrows - 1);
            fflush(fp);
            return;
        }
    }
    text_rewrite();
}

/* ------------------------------------------------------------ xlsx */

static void
xlsx_write(void)
{
    const char **hdr;
    int *hstyle;
    struct mcs_xcell **cells, *pool;
    int nc = 3 + ncols, i, r, c;

    hdr = TMALLOC(const char *, nc);
    hstyle = TMALLOC(int, nc);
    c = 0;
    hdr[c] = "corner"; hstyle[c++] = 0;
    hdr[c] = "analysis"; hstyle[c++] = 0;
    hdr[c] = "status"; hstyle[c++] = 0;
    for (i = 0; i < ncols; i++) {
        hdr[c] = cols[i].name;
        hstyle[c++] = cols[i].written ? 3 : cols[i].model ? 1 : 2;
    }
    pool = TMALLOC(struct mcs_xcell, (size_t) nrows * (size_t) nc);
    cells = TMALLOC(struct mcs_xcell *, nrows ? nrows : 1);
    for (r = 0; r < nrows; r++) {
        struct mcs_xcell *row = pool + (size_t) r * (size_t) nc;
        cells[r] = row;
        c = 0;
        row[c].s = rowcn[r]; row[c++].v = NAN;
        row[c].s = rowan[r]; row[c++].v = NAN;
        row[c].s = rowst[r]; row[c++].v = NAN;
        for (i = 0; i < ncols; i++) {
            row[c].s = NULL;
            row[c++].v = i < rowcols[r] ? rows[r][i] : NAN;
        }
    }
    if (MCSAVExlsxWrite(path, "corners", "savecorner", nc, hdr, hstyle, nrows,
                        (const struct mcs_xcell *const *) cells) != 0)
        cs_note_write_fail();
    else
        noted_write_fail = 0;
    tfree(hdr);
    tfree(hstyle);
    tfree(pool);
    tfree(cells);
}

/* ------------------------------------------------------------ the file */

static void
cs_reset_file(void)
{
    int r;
    if (fp)
        fclose(fp);
    fp = NULL;
    for (r = 0; r < nrows; r++) {
        tfree(rows[r]);
        tfree(rowcn[r]);
        tfree(rowan[r]);
        tfree(rowst[r]);
        tfree(rowpl[r]);
    }
    tfree(rows); tfree(rowcols); tfree(rowcn); tfree(rowan); tfree(rowst);
    tfree(rowplot); tfree(rowpl);
    nrows = caprows = 0;
    cols_free();
    tfree(path);
    tfree(owner_file);
    tfree(owner_name);
    owner = 0;
    header_cols = 0;
    lastrow_off = -1;
    noted_nothing = 0;
    unwritable = 0;
    noted_write_fail = 0;
}

static void
cs_complete(void)
{
    if (!owner)
        return;
    if (fmt == MCS_FMT_XLSX && nrows > 0)
        xlsx_write();
    if (fp) {
        fclose(fp);
        fp = NULL;
    }
}

static int
same_circuit(struct circ *ci)
{
    const char *f = ci->ci_filename ? ci->ci_filename : "";
    const char *n = ci->ci_name ? ci->ci_name : "";
    if (!owner || !eq(owner_name ? owner_name : "", n))
        return 0;
    return !*f || !owner_file || !*owner_file || eq(owner_file, f);
}

void
CSAVEcircuitFreed(struct circ *ci)
{
    if (owner && ci && same_circuit(ci))
        if (fmt == MCS_FMT_XLSX && nrows > 0)
            xlsx_write();
}

void
CSAVEfinish(void)
{
    cs_complete();
    cs_reset_file();
}

/* the file for this circuit is opened at its first row; 1 when a row can be
 * written, 0 when nothing is recorded for this circuit (said) */
static int
cs_open_for(const char *given)
{
    char *why = NULL;
    int ok = 0;

    owner = 1;
    owner_file = copy(ft_curckt->ci_filename ? ft_curckt->ci_filename : "");
    owner_name = copy(ft_curckt->ci_name ? ft_curckt->ci_name : "");
    path = MCSAVEmakePath(given, "corners", fmt);
    if (given) {
        const char *by = MCSAVEusedBy(path);
        if (by) {
            char *alt = MCSAVEunusedVariant(path);
            fprintf(cp_out, "Note: savecorner: %s holds the rows of '%s' from earlier in "
                            "this session and is kept; this deck's rows go to %s\n",
                    path, by, alt);
            tfree(path);
            path = alt;
        }
    }
    if (given) {
        char *mkwhy = NULL;
        (void) MCSAVEmkdirs(path, &mkwhy);
        ok = MCSAVEcanOpen(path, fmt, &why);
        if (!ok) {
            char *fallback = MCSAVEmakePath(NULL, "corners", fmt);
            fprintf(cp_err, "Warning: savecorner: cannot open %s (%s); recording to %s "
                            "instead\n", path, mkwhy ? mkwhy : why, fallback);
            tfree(why);
            tfree(path);
            path = fallback;
        }
        tfree(mkwhy);
    }
    if (!ok && !MCSAVEcanOpen(path, fmt, &why)) {
        fprintf(cp_err, "Error: savecorner: cannot open %s (%s); nothing is recorded for "
                        "this circuit\n", path, why);
        tfree(why);
        unwritable = 1;
        return 0;
    }
    MCSAVEnoteUsed(path, owner_name);
    return 1;
}

/* ------------------------------------------------------------ the rows */

void
CSAVErunBegin(void)
{
    plot_before = plot_cur;
}

/* the common row maker: 0 when nothing was recorded */
static int
cs_row(const char *corner, const char *analysis, int ok, struct plot *made,
       const char *const wnames[], const double wvalues[], int nw)
{
    char *given = NULL;
    int i, n;

    if (!ft_curckt)
        return 0;
    if (!cs_option(&given)) {
        tfree(given);
        return 0;
    }
    if (owner && !same_circuit(ft_curckt)) {    /* a different deck: a new file */
        cs_complete();
        cs_reset_file();
    }
    if (owner && unwritable) {
        tfree(given);
        return 0;
    }
    if (!ft_curckt->ci_ckt || !OSDImcHasCorners(ft_curckt->ci_ckt)) {
        if (!noted_nothing)
            fprintf(cp_err, "Note: savecorner: nothing to record -- no loaded Verilog-A model "
                            "declares a corner (a parameter declares them with "
                            "(* corner=\"ss=..., ff=...\" *), Enhancement-654)\n");
        noted_nothing = 1;
        tfree(given);
        return 0;
    }

    /* the cornered parameters, as the devices hold them now */
    cols_clear_values();
    {
        int summary = nw > 0;
        OSDImcCornerSnapshot(ft_curckt->ci_ckt, snapshot_cb, summary ? &summary : NULL);
    }
    for (i = n = 0; i < ncols; i++)
        if (!cols[i].written)
            n++;

    if (!owner) {
        if (!cs_open_for(given)) {
            tfree(given);
            return 0;
        }
        fprintf(cp_out, "Note: savecorner: recording the %d cornered parameter%s, one row per "
                        "corner run, to %s\n", n, n == 1 ? "" : "s", path);
    }
    tfree(given);

    if (nrows == caprows) {
        caprows = caprows ? 2 * caprows : 64;
        rows = TREALLOC(double *, rows, caprows);
        rowcols = TREALLOC(int, rowcols, caprows);
        rowcn = TREALLOC(char *, rowcn, caprows);
        rowan = TREALLOC(char *, rowan, caprows);
        rowst = TREALLOC(char *, rowst, caprows);
        rowplot = TREALLOC(struct plot *, rowplot, caprows);
        rowpl = TREALLOC(char *, rowpl, caprows);
    }
    /* the written columns first: a summary row brings its own */
    for (i = 0; i < nw; i++) {
        struct cs_col *c = col_find(wnames[i]);
        if (!c) {
            c = col_add(wnames[i], 0);
            c->written = 1;
        }
        c->value = wvalues[i];
        c->set = 1;
    }
    rows[nrows] = TMALLOC(double, ncols);
    for (i = 0; i < ncols; i++)
        rows[nrows][i] = cols[i].set ? cols[i].value : NAN;
    rowcols[nrows] = ncols;
    rowcn[nrows] = copy(corner && *corner ? corner : "tt");
    rowan[nrows] = copy(analysis ? analysis : "?");
    rowst[nrows] = copy(ok == MCS_PAUSED ? "paused" : ok ? "ok" : "failed");
    rowplot[nrows] = made;
    rowpl[nrows] = copy(made && made->pl_typename ? made->pl_typename : "");
    nrows++;

    if (fmt == MCS_FMT_XLSX) {
        if (nrows == 1 || nrows % 25 == 0)
            xlsx_write();
        return 1;
    }
    if (!fp || header_cols != ncols) {
        text_rewrite();                 /* the first row, or a new column */
        return 1;
    }
    lastrow_off = ftell(fp);
    text_row(fp, nrows - 1);
    fflush(fp);
    return 1;
}

void
CSAVEhold(int on)
{
    hold_depth += on ? 1 : -1;
    if (hold_depth < 0)
        hold_depth = 0;
}

void
CSAVErun(const char *analysis, int ok)
{
    const char *loop = outp_loop_label_now();
    struct plot *made;

    /* a loop command's samples are not corner runs: `montecarlo`, `sweep`,
     * `optimize`, `wcd`, `highsigma` (and wcd's own probing); the `corners`
     * loop's runs are, one per corner, and an autocorner pass is no loop
     * command at all. `corners -mc N` holds the recorder around its
     * montecarlo per corner (the nested loop keeps the outer label). */
    if (hold_depth > 0 || (loop && !eq(loop, "corners")) || mc_wcd_active())
        return;
    made = (ok == MCS_OK || plot_cur != plot_before) ? plot_cur : NULL;
    (void) cs_row(OSDImcCornerName(), analysis, ok, made, NULL, NULL, 0);
}

void
CSAVEsummaryRow(const char *corner, const char *analysis, int ok,
                const char *const names[], const double values[], int n)
{
    (void) cs_row(corner, analysis, ok, NULL, names, values, n);
}

void
CSAVEresumed(int ok)
{
    int r;

    if (!owner || nrows == 0 || unwritable)
        return;
    for (r = nrows - 1; r >= 0; r--)
        if (eq(rowst[r], "paused"))
            break;
    if (r < 0 || (rowplot[r] && rowplot[r] != plot_cur))
        return;
    tfree(rowst[r]);
    rowst[r] = copy(ok ? "ok" : "failed");
    if (fmt == MCS_FMT_XLSX)
        return;
    if (r == nrows - 1)
        text_rewrite_last();
    else
        text_rewrite();
}

/* ------------------------------------------------------------ values after the run */

static int
cs_append_row(int r, const char *name, double value)
{
    struct cs_col *c;
    int i, newcol = 0;
    if (eq(name, "corner") || eq(name, "analysis") || eq(name, "status"))
        return -4;
    c = col_find(name);
    if (!c) {
        c = col_add(name, 0);
        c->written = 1;
        newcol = 1;
    } else if (!c->written) {
        /* the name of a cornered parameter: its column stays, the value
         * goes on as `<name>*` beside it */
        char *alt = tprintf("%s*", name);
        int rr = cs_append_row(r, alt, value);
        tfree(alt);
        return rr;
    }
    i = (int) (c - cols);
    if (rowcols[r] < ncols) {
        int k;
        rows[r] = TREALLOC(double, rows[r], ncols);
        for (k = rowcols[r]; k < ncols; k++)
            rows[r][k] = NAN;
        rowcols[r] = ncols;
    }
    rows[r][i] = value;
    if (fmt == MCS_FMT_XLSX) {
        if (nrows % 25 == 0)
            xlsx_write();
        return 0;
    }
    if (newcol || r != nrows - 1)
        text_rewrite();
    else
        text_rewrite_last();
    return 0;
}

int
CSAVEappend(const char *name, double value)
{
    if (!CSAVEactive())
        return -2;
    if (owner && unwritable)
        return -3;
    if (!owner || nrows == 0)
        return -1;
    return cs_append_row(nrows - 1, name, value);
}

int
CSAVEappendPlot(struct plot *pl, const char *name, double value)
{
    int r;
    if (!CSAVEactive())
        return -2;
    if (owner && unwritable)
        return -3;
    if (!owner || nrows == 0)
        return -1;
    for (r = nrows - 1; r >= 0; r--)
        if (rowplot[r] == pl)
            break;
    if (r < 0)
        return -5;
    return cs_append_row(r, name, value);
}

int
CSAVEplotIsRow(char **why)
{
    struct plot *rp, *pl;
    const char *cur = plot_cur && plot_cur->pl_typename ? plot_cur->pl_typename : "?";

    *why = NULL;
    if (!owner || nrows == 0)
        return 1;
    rp = rowplot[nrows - 1];
    if (!rp) {
        *why = tprintf("the last corner row (%s, %s) has no plot of its own, so the current "
                       "plot %s is another run's", rowcn[nrows - 1], rowan[nrows - 1], cur);
        return 0;
    }
    if (rp == plot_cur)
        return 1;
    for (pl = plot_list; pl; pl = pl->pl_next) {   /* newest first */
        if (pl == rp)
            return 1;
        if (pl == plot_cur) {
            *why = tprintf("the current plot %s was made after the last corner row (%s, %s, "
                           "plot %s) by a run that has no row", cur, rowcn[nrows - 1],
                           rowan[nrows - 1], rowpl[nrows - 1]);
            return 0;
        }
    }
    return 1;
}
