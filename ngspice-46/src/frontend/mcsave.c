/* Enhancement-610: `.option savemc[=csv|excel|txt|<file>]` and
 * `.option automc_save` (alias `osdimc_save`) -- the value of every parameter
 * with statistics, one row per analysis run, in a file beside the netlist.
 *
 * What has statistics: a `.param` whose expression calls a random function
 * (`.param rv = agauss(1k, 50, 1)`), a subcircuit instance's own such value
 * (`x1.p`), a device line's brace draw (`r1:{agauss(1k,50,1)}`), and an OSDI
 * parameter declared with `(* std= *)` under `.option osdimc`, read as
 * `@<model>[<param>]` / `@<instance>[<param>]`. The numparam side records
 * each draw as it is evaluated (a re-source, a `reset`, a sweep's or
 * montecarlo's in-place re-evaluation); the OSDI side is read off the devices
 * when the row is made, so the baseline trial (nominal) and a pinned or
 * pending draw are reported as the devices actually ran.
 *
 * One row per run-class command (`op`, `tran`, `run`, ... -- what if_run
 * dispatches, `resume` excluded): under `montecarlo`, `sweep` or a `repeat`
 * loop that is one row per sample; a run whose analysis failed is a row too,
 * marked in its status column, since the draw happened. Columns are fixed by
 * the first row's set of names and grow if a later row brings a new one (the
 * file is rewritten then). The file is `mcparams_<date>_<time>.<ext>` in the
 * netlist's directory (Infile_Path; the working directory when a deck was not
 * read from a file), or the name `.option savemc=<name>.<ext>` gives; csv by
 * default, `txt` tab-separated, `excel` a genuine .xlsx (a stored zip, written
 * in full every 25 rows and when the circuit is freed or ngspice exits). One
 * file per circuit: a `reset` continues it, a new `source` starts a new one.
 * `automc_save` restricts the columns to the OSDI parameters. */

#include "ngspice/ngspice.h"
#include "ngspice/cpdefs.h"
#include "ngspice/ftedefs.h"
#include "ngspice/dstring.h"
#include "ngspice/osdiitf.h"
#include "ngspice/stringskip.h"
#include "ngspice/dvec.h"
#include "ngspice/fteparse.h"
#include "mcsave.h"
#include <time.h>
#include <ctype.h>
#include <math.h>
#ifdef HAVE_UNISTD_H
#include <unistd.h>         /* ftruncate */
#endif
#ifdef _MSC_VER
#include <io.h>
#define ftruncate(fd, len) _chsize(fd, (long) (len))
#endif
#include <errno.h>
#include <sys/types.h>
#include <sys/stat.h>
/* Enhancement-613: mkdir() as com_dl.c spells it for the three toolchains
 * (a mode on POSIX; _mkdir() from <direct.h> on Windows) */
#if defined(_WIN32)
#include <direct.h>
#define NG_MKDIR(p) _mkdir(p)
#else
#define NG_MKDIR(p) mkdir((p), 0777)
#endif

enum { FMT_CSV, FMT_TXT, FMT_XLSX };

struct mcs_col {
    char *name;
    int osdi;                       /* an OSDI parameter, read per row */
    int model;                      /* Enhancement-617: a model card's parameter (the xlsx
                                       header sets its name in bold); 0 for an instance's,
                                       a subcircuit call's, a .param, a writemc value */
    int written;                    /* Enhancement-611: a writemc value, put on the row after the run */
    double value;                   /* the value in force */
    int set;
    int gen;                        /* the deck expansion that last set it */
};
static int gen;                     /* counts deck expansions (source, reset) */

static struct mcs_col *cols;
static int ncols, capcols;

static double **rows;               /* nrows x (columns at the time), NAN = not seen */
static int *rowcols;
static char **rowan;                /* the analysis name */
static char **rowst;                /* "ok" / "failed" */
static int nrows, caprows;

/* the circuit whose file this is -- by its file and title, not its struct:
 * a `reset` frees the struct and builds a new one from the same deck (every
 * montecarlo sample does), and that is the same circuit to this file */
static char *owner_file, *owner_name;
static int owner;                   /* a file is open for a circuit */
static char *path;
static int fmt;
static int osdi_only;
static FILE *fp;                    /* csv/txt: kept open, appended */
static int header_cols;             /* columns the csv/txt header was written with */
static long lastrow_off = -1;       /* Enhancement-611: where the last row begins, to rewrite it */
static int noted_nothing;
static int noted_osdimc_off;
static int unwritable;              /* Enhancement-613: no file could be opened for this circuit */
static int noted_write_fail;        /* Enhancement-613: a later open failed (said once) */

/* ------------------------------------------------------------ the draws */

int
MCSAVEexpr_is_random(const char *e)
{
    static const char *const rf[] = { "agauss", "gauss", "unif", "aunif",
                                      "limit", "mvnorm", NULL };
    int i;

    if (!e)
        return 0;
    for (i = 0; rf[i]; i++) {
        size_t n = strlen(rf[i]);
        const char *p;
        for (p = e; (p = strstr(p, rf[i])) != NULL; p += n) {
            const char *q = p + n;
            if (p > e && (isalnum_c(p[-1]) || p[-1] == '_'))
                continue;                       /* part of a longer identifier */
            while (*q && isspace_c(*q))
                q++;
            if (*q == '(')
                return 1;
        }
    }
    return 0;
}

static struct mcs_col *
col_find(const char *name)
{
    int i;
    for (i = 0; i < ncols; i++)
        if (eq(cols[i].name, name))
            return &cols[i];
    return NULL;
}

static struct mcs_col *
col_add(const char *name, int osdi, int model)
{
    if (ncols == capcols) {
        capcols = capcols ? 2 * capcols : 16;
        cols = TREALLOC(struct mcs_col, cols, capcols);
    }
    cols[ncols].name = copy(name);
    cols[ncols].osdi = osdi;
    cols[ncols].model = model;
    cols[ncols].written = 0;
    cols[ncols].value = NAN;
    cols[ncols].set = 0;
    cols[ncols].gen = gen;
    return &cols[ncols++];
}

static void
col_set(const char *name, double value, int osdi, int model)
{
    struct mcs_col *c = col_find(name);
    if (!c)
        c = col_add(name, osdi, model);
    c->value = value;
    c->set = 1;
    c->gen = gen;
}

void
MCSAVEparam(const char *name, double value, int model)
{
    if (!name || !*name)
        return;
    col_set(name, value, 0, model);
}

int
MCSAVEis_stochastic(const char *name)
{
    struct mcs_col *c = name ? col_find(name) : NULL;
    return c != NULL && !c->osdi;
}

/* a deck expansion begins (a source, a reset): every numparam draw is about
 * to be re-evaluated, so forget the values -- the columns stay, so a reset
 * keeps the file's column order -- and what is not drawn again is nan */
void
MCSAVEnewDeck(void)
{
    int i;
    gen++;
    for (i = 0; i < ncols; i++)
        if (!cols[i].osdi)
            cols[i].set = 0;
}

/* montecarlo's fast path re-derives the device values without a deck
 * expansion: the values are forgotten, the deck stays the same one -- a
 * value the path does not re-derive (a subcircuit call's own parameter) is
 * nan on its rows */
void
MCSAVEredraw(void)
{
    int i;
    for (i = 0; i < ncols; i++)
        if (!cols[i].osdi)
            cols[i].set = 0;
}

/* a new circuit takes the recorder: the columns a previous deck left --
 * not set since this deck's expansion -- and every OSDI column (read
 * afresh) go */
static void
cols_prune_for_new_owner(void)
{
    int i, k = 0;
    for (i = 0; i < ncols; i++) {
        if (cols[i].osdi || cols[i].written || (!cols[i].set && cols[i].gen != gen)) {
            tfree(cols[i].name);
        } else {
            cols[k++] = cols[i];
        }
    }
    ncols = k;
}

/* Enhancement-618: does the file already carry OSDI columns? */
static int
cols_have_osdi(void)
{
    int i;
    for (i = 0; i < ncols; i++)
        if (cols[i].osdi)
            return 1;
    return 0;
}

static void
osdi_cb(const char *owner_name, const char *param, double value, int is_model,
        void *ctx)
{
    char *name = tprintf("@%s[%s]", owner_name, param);
    NG_IGNORE(ctx);
    col_set(name, value, 1, is_model);
    tfree(name);
}

/* ------------------------------------------------------------ the option */

/* 0: off; else sets fmt, osdi_only and (a private copy of) the file name
 * the option gives, or NULL for the dated default */
static int
mcs_option(char **given)
{
    char val[BSIZE_SP];
    int on = 0;

    *given = NULL;
    osdi_only = 0;
    fmt = FMT_CSV;
    if (cp_getvar("savemc", CP_STRING, val, sizeof val)) {
        on = 1;
    } else if (cp_getvar("savemc", CP_BOOL, NULL, 0)) {
        on = 1;
        val[0] = '\0';
    }
    if (!on) {
        if (cp_getvar("automc_save", CP_STRING, val, sizeof val) ||
                cp_getvar("osdimc_save", CP_STRING, val, sizeof val)) {
            on = 1;
        } else if (cp_getvar("automc_save", CP_BOOL, NULL, 0) ||
                   cp_getvar("osdimc_save", CP_BOOL, NULL, 0)) {
            on = 1;
            val[0] = '\0';
        }
        if (on)
            osdi_only = 1;
    }
    if (!on || cp_getvar("nosavemc", CP_BOOL, NULL, 0))
        return 0;

    if (!val[0] || cieq(val, "csv") || cieq(val, "true")) {
        fmt = FMT_CSV;
    } else if (cieq(val, "txt") || cieq(val, "text")) {
        fmt = FMT_TXT;
    } else if (cieq(val, "excel") || cieq(val, "xlsx") || cieq(val, "xls")) {
        fmt = FMT_XLSX;
    } else {
        /* a file name: its extension picks the format */
        const char *dot = strrchr(val, '.');
        if (dot && cieq(dot, ".csv"))
            fmt = FMT_CSV;
        else if (dot && (cieq(dot, ".txt") || cieq(dot, ".tsv")))
            fmt = FMT_TXT;
        else if (dot && (cieq(dot, ".xlsx") || cieq(dot, ".xls")))
            fmt = FMT_XLSX;
        else {
            fprintf(cp_err, "Warning: .option savemc=%s: not a format (csv, txt, excel) "
                            "and not a file name ending in .csv, .txt or .xlsx; "
                            "csv is used\n", val);
            fmt = FMT_CSV;
            return 1;
        }
        *given = copy(val);
    }
    return 1;
}

static const char *
mcs_ext(void)
{
    return fmt == FMT_CSV ? "csv" : fmt == FMT_TXT ? "txt" : "xlsx";
}

static char *
mcs_path(const char *given)
{
    const char *dir = Infile_Path && *Infile_Path ? Infile_Path : ".";
    if (given && (given[0] == '/' || given[0] == '\\' ||
                  (isalpha_c(given[0]) && given[1] == ':')))
        return copy(given);
    if (given)
        return tprintf("%s/%s", dir, given);
    {
        time_t now = time(NULL);
        struct tm *lt = localtime(&now);
        char stamp[40];
        char *name;
        FILE *probe;
        int k;
        if (lt)
            strftime(stamp, sizeof stamp, "%Y%m%d_%H%M%S", lt);
        else
            strcpy(stamp, "00000000_000000");
        name = tprintf("%s/mcparams_%s.%s", dir, stamp, mcs_ext());
        /* two runs within the same second (a script) must not share a file */
        for (k = 2; (probe = fopen(name, "r")) != NULL && k < 1000; k++) {
            fclose(probe);
            tfree(name);
            name = tprintf("%s/mcparams_%s_%d.%s", dir, stamp, k, mcs_ext());
        }
        if (probe)
            fclose(probe);
        return name;
    }
}

/* Enhancement-613: create the missing directories of a file name, each
 * component in turn like `mkdir -p`. 0, or -1 with `*why` the reason the
 * first directory that is still missing afterwards could not be made. */
static int
mcs_mkdirs(const char *file, char **why)
{
    char *p, *s;
    int rc = 0;

    *why = NULL;
    p = copy(file);
    for (s = p + 1; *s; s++) {
        char sep = *s;
        if (sep != '/'
#if defined(_WIN32)
            && sep != '\\'
#endif
            )
            continue;
        *s = '\0';                 /* p is now the directory up to here */
        if (s[-1] != ':' && NG_MKDIR(p) != 0 && errno != EEXIST) {
            int e = errno;
            struct stat st;
            if (stat(p, &st) != 0 || !S_ISDIR(st.st_mode)) {
                *why = tprintf("cannot create directory %s: %s", p, strerror(e));
                rc = -1;
                *s = sep;
                break;
            }
        }
        *s = sep;
    }
    tfree(p);
    return rc;
}

/* can the file be written? A try at the first row, so that a name that
 * cannot be opened is found then and not never; the file is created empty
 * and the row that follows writes it. */
static int
mcs_can_open(const char *file, char **why)
{
    FILE *f = fopen(file, fmt == FMT_XLSX ? "wb" : "w");
    if (f) {
        fclose(f);
        *why = NULL;
        return 1;
    }
    *why = tprintf("%s", strerror(errno));
    return 0;
}

/* a later open of the file failed (a directory removed, a disk full):
 * said once per file, and the rows stay in memory for the next try */
static void
mcs_note_write_fail(void)
{
    if (noted_write_fail)
        return;
    fprintf(cp_err, "Error: savemc: cannot write %s (%s); the rows so far are kept and "
                    "written when the file can be opened again\n",
            path, strerror(errno));
    noted_write_fail = 1;
}

/* Enhancement-615 (hunt F17): the names this session has written, each with
 * the title of the deck that wrote it. A later deck that names the same file
 * used to replace it without a word -- E-610's "a different deck starts its
 * own file" was an overwrite when the name is fixed. Such a deck now gets
 * `<stem>_2.<ext>` (the first not written by this session) and says so. A
 * name from an earlier ngspice run is not protected: a fixed name means the
 * same file on every run, as for any output file. */
static struct mcs_used {
    char *path;
    char *title;
} *used;
static int nused, capused;

static const char *
mcs_used_by(const char *p)
{
    int i;
    for (i = 0; i < nused; i++)
        if (eq(used[i].path, p))
            return used[i].title;
    return NULL;
}

static void
mcs_note_used(const char *p, const char *title)
{
    if (nused == capused) {
        capused = capused ? 2 * capused : 8;
        used = TREALLOC(struct mcs_used, used, capused);
    }
    used[nused].path = copy(p);
    used[nused].title = copy(title && *title ? title : "(untitled)");
    nused++;
}

static void
mcs_free_used(void)
{
    int i;
    for (i = 0; i < nused; i++) {
        tfree(used[i].path);
        tfree(used[i].title);
    }
    tfree(used);
    nused = capused = 0;
}

/* `<stem>_<k>.<ext>` for the smallest k >= 2 this session has not written */
static char *
mcs_unused_variant(const char *p)
{
    const char *base = strrchr(p, '/');
#if defined(_WIN32)
    const char *bs = strrchr(p, '\\');
    if (bs && (!base || bs > base))
        base = bs;
#endif
    const char *dot = strrchr(base ? base : p, '.');
    int k;
    for (k = 2; ; k++) {
        char *cand = dot ? tprintf("%.*s_%d%s", (int) (dot - p), p, k, dot)
                         : tprintf("%s_%d", p, k);
        if (!mcs_used_by(cand))
            return cand;
        tfree(cand);
    }
}

/* ------------------------------------------------------------ csv / txt */

static void
put_name(FILE *f, const char *name)
{
    if (fmt == FMT_CSV && (strchr(name, ',') || strchr(name, '"'))) {
        const char *p;
        putc('"', f);
        for (p = name; *p; p++) {
            if (*p == '"')
                putc('"', f);
            putc(*p, f);
        }
        putc('"', f);
    } else {
        fputs(name, f);
    }
}

static void
put_value(FILE *f, double v)
{
    if (isnan(v))
        fputs(fmt == FMT_TXT ? "nan" : "", f);
    else
        fprintf(f, "%.12g", v);
}

static int
col_wanted(int i)
{
    return !osdi_only || cols[i].osdi || cols[i].written;
}

static void
text_header(FILE *f)
{
    const char sep = fmt == FMT_CSV ? ',' : '\t';
    int i;
    fprintf(f, "trial%canalysis%cstatus", sep, sep);
    for (i = 0; i < ncols; i++)
        if (col_wanted(i)) {
            putc(sep, f);
            put_name(f, cols[i].name);
        }
    putc('\n', f);
    header_cols = ncols;
}

static void
text_row(FILE *f, int r)
{
    const char sep = fmt == FMT_CSV ? ',' : '\t';
    int i;
    fprintf(f, "%d%c%s%c%s", r + 1, sep, rowan[r], sep, rowst[r]);
    for (i = 0; i < ncols; i++)
        if (col_wanted(i)) {
            putc(sep, f);
            put_value(f, i < rowcols[r] ? rows[r][i] : NAN);
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
        mcs_note_write_fail();
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

/* ------------------------------------------------------------ xlsx */

static unsigned long crc_table[256];
static int crc_ready;

static unsigned long
crc32_of(const char *buf, size_t n)
{
    unsigned long c;
    size_t i;
    if (!crc_ready) {
        unsigned long k;
        for (k = 0; k < 256; k++) {
            unsigned long v = k;
            int j;
            for (j = 0; j < 8; j++)
                v = (v & 1) ? 0xEDB88320UL ^ (v >> 1) : v >> 1;
            crc_table[k] = v;
        }
        crc_ready = 1;
    }
    c = 0xFFFFFFFFUL;
    for (i = 0; i < n; i++)
        c = crc_table[(c ^ (unsigned char) buf[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFUL;
}

static void
le16(FILE *f, unsigned v) { putc(v & 0xFF, f); putc((v >> 8) & 0xFF, f); }
static void
le32(FILE *f, unsigned long v) { le16(f, (unsigned) (v & 0xFFFF)); le16(f, (unsigned) ((v >> 16) & 0xFFFF)); }

struct zent { const char *name; long offset; unsigned long crc, size; };

/* one stored (uncompressed) entry; returns its local-header offset */
static void
zip_entry(FILE *f, struct zent *z, const char *name, const char *data, size_t n)
{
    z->name = name;
    z->offset = ftell(f);
    z->crc = crc32_of(data, n);
    z->size = (unsigned long) n;
    le32(f, 0x04034b50UL); le16(f, 20); le16(f, 0); le16(f, 0);
    le16(f, 0); le16(f, 0x21);                  /* time 00:00, date 1980-01-01 */
    le32(f, z->crc); le32(f, z->size); le32(f, z->size);
    le16(f, (unsigned) strlen(name)); le16(f, 0);
    fputs(name, f);
    fwrite(data, 1, n, f);
}

static void
zip_finish(FILE *f, struct zent *z, int nz)
{
    long cd = ftell(f), cdsize;
    int i;
    for (i = 0; i < nz; i++) {
        le32(f, 0x02014b50UL); le16(f, 20); le16(f, 20); le16(f, 0); le16(f, 0);
        le16(f, 0); le16(f, 0x21);
        le32(f, z[i].crc); le32(f, z[i].size); le32(f, z[i].size);
        le16(f, (unsigned) strlen(z[i].name)); le16(f, 0); le16(f, 0);
        le16(f, 0); le16(f, 0); le32(f, 0);
        le32(f, (unsigned long) z[i].offset);
        fputs(z[i].name, f);
    }
    cdsize = ftell(f) - cd;
    le32(f, 0x06054b50UL); le16(f, 0); le16(f, 0); le16(f, (unsigned) nz); le16(f, (unsigned) nz);
    le32(f, (unsigned long) cdsize); le32(f, (unsigned long) cd); le16(f, 0);
}

static void
xml_text(DSTRING *d, const char *s)
{
    for (; *s; s++) {
        if (*s == '&') ds_cat_str(d, "&amp;");
        else if (*s == '<') ds_cat_str(d, "&lt;");
        else if (*s == '>') ds_cat_str(d, "&gt;");
        else if (*s == '"') ds_cat_str(d, "&quot;");
        else ds_cat_char(d, *s);
    }
}

static void
cell_ref(DSTRING *d, int col0, int row1)
{
    char letters[8];
    int n = 0, c = col0;
    do {
        letters[n++] = (char) ('A' + c % 26);
        c = c / 26 - 1;
    } while (c >= 0 && n < 7);
    while (n > 0)
        ds_cat_char(d, letters[--n]);
    ds_cat_printf(d, "%d", row1);
}

/* Enhancement-617: style 1 is the bold font, for a model parameter's name
 * in the header row (an instance parameter's stays regular) */
static void
xlsx_str_cell_style(DSTRING *d, int col0, int row1, const char *s, int style)
{
    ds_cat_str(d, "<c r=\"");
    cell_ref(d, col0, row1);
    if (style)
        ds_cat_printf(d, "\" s=\"%d", style);
    ds_cat_str(d, "\" t=\"inlineStr\"><is><t>");
    xml_text(d, s);
    ds_cat_str(d, "</t></is></c>");
}

static void
xlsx_str_cell(DSTRING *d, int col0, int row1, const char *s)
{
    xlsx_str_cell_style(d, col0, row1, s, 0);
}

static void
xlsx_num_cell(DSTRING *d, int col0, int row1, double v)
{
    if (isnan(v))
        return;                                 /* an empty cell */
    ds_cat_str(d, "<c r=\"");
    cell_ref(d, col0, row1);
    ds_cat_printf(d, "\"><v>%.12g</v></c>", v);
}

static void
xlsx_write(void)
{
    static const char *ctypes =
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/>"
        "<Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
        "<Override PartName=\"/xl/styles.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml\"/>"
        "</Types>";
    static const char *rels =
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/>"
        "</Relationships>";
    static const char *workbook =
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" "
        "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\">"
        "<sheets><sheet name=\"mcparams\" sheetId=\"1\" r:id=\"rId1\"/></sheets></workbook>";
    static const char *wbrels =
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/>"
        "<Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
        "</Relationships>";
    static const char *styles =
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<styleSheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        "<fonts count=\"2\"><font><sz val=\"11\"/><name val=\"Calibri\"/></font>"
        "<font><b/><sz val=\"11\"/><name val=\"Calibri\"/></font></fonts>"
        "<fills count=\"2\"><fill><patternFill patternType=\"none\"/></fill><fill><patternFill patternType=\"gray125\"/></fill></fills>"
        "<borders count=\"1\"><border><left/><right/><top/><bottom/><diagonal/></border></borders>"
        "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>"
        "<cellXfs count=\"2\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/>"
        "<xf numFmtId=\"0\" fontId=\"1\" fillId=\"0\" borderId=\"0\" xfId=\"0\" applyFont=\"1\"/></cellXfs>"
        "<cellStyles count=\"1\"><cellStyle name=\"Normal\" xfId=\"0\" builtinId=\"0\"/></cellStyles>"
        "</styleSheet>";
    DS_CREATE(sheet, 4096);
    struct zent z[6];
    FILE *f;
    int r, i, c;

    ds_cat_str(&sheet,
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        "<sheetData><row r=\"1\">");
    xlsx_str_cell(&sheet, 0, 1, "trial");
    xlsx_str_cell(&sheet, 1, 1, "analysis");
    xlsx_str_cell(&sheet, 2, 1, "status");
    for (i = 0, c = 3; i < ncols; i++)
        if (col_wanted(i))
            xlsx_str_cell_style(&sheet, c++, 1, cols[i].name, cols[i].model ? 1 : 0);
    ds_cat_str(&sheet, "</row>");
    for (r = 0; r < nrows; r++) {
        ds_cat_printf(&sheet, "<row r=\"%d\">", r + 2);
        xlsx_num_cell(&sheet, 0, r + 2, (double) (r + 1));
        xlsx_str_cell(&sheet, 1, r + 2, rowan[r]);
        xlsx_str_cell(&sheet, 2, r + 2, rowst[r]);
        for (i = 0, c = 3; i < ncols; i++)
            if (col_wanted(i))
                xlsx_num_cell(&sheet, c++, r + 2, i < rowcols[r] ? rows[r][i] : NAN);
        ds_cat_str(&sheet, "</row>");
    }
    ds_cat_str(&sheet, "</sheetData></worksheet>");

    f = fopen(path, "wb");
    if (!f) {
        mcs_note_write_fail();
        ds_free(&sheet);
        return;
    }
    noted_write_fail = 0;
    zip_entry(f, &z[0], "[Content_Types].xml", ctypes, strlen(ctypes));
    zip_entry(f, &z[1], "_rels/.rels", rels, strlen(rels));
    zip_entry(f, &z[2], "xl/workbook.xml", workbook, strlen(workbook));
    zip_entry(f, &z[3], "xl/_rels/workbook.xml.rels", wbrels, strlen(wbrels));
    zip_entry(f, &z[4], "xl/styles.xml", styles, strlen(styles));
    zip_entry(f, &z[5], "xl/worksheets/sheet1.xml", ds_get_buf(&sheet), ds_get_length(&sheet));
    zip_finish(f, z, 6);
    fclose(f);
    ds_free(&sheet);
}

/* ------------------------------------------------------------ the rows */

static void
mcs_reset_file(void)
{
    int r;
    if (fp)
        fclose(fp);
    fp = NULL;
    for (r = 0; r < nrows; r++) {
        tfree(rows[r]);
        tfree(rowan[r]);
        tfree(rowst[r]);
    }
    tfree(rows); tfree(rowcols); tfree(rowan); tfree(rowst);
    nrows = caprows = 0;
    tfree(path);
    tfree(owner_file);
    tfree(owner_name);
    owner = 0;
    header_cols = 0;
    lastrow_off = -1;
    noted_nothing = 0;
    noted_osdimc_off = 0;
    unwritable = 0;
    noted_write_fail = 0;
}

static void
mcs_complete(void)
{
    if (!owner)
        return;
    if (fmt == FMT_XLSX && nrows > 0)
        xlsx_write();
    if (fp) {
        fclose(fp);
        fp = NULL;
    }
}

/* the same deck: the same title, and the same file when the circuit knows
 * its file -- a `reset` rebuilds the circuit from the deck in memory, with
 * no file name */
static int
same_circuit(struct circ *ci)
{
    const char *f = ci->ci_filename ? ci->ci_filename : "";
    const char *n = ci->ci_name ? ci->ci_name : "";
    if (!owner || !eq(owner_name ? owner_name : "", n))
        return 0;
    return !*f || !owner_file || !*owner_file || eq(owner_file, f);
}

/* a circuit struct goes: a `reset` builds a new one from the same deck and
 * its rows continue this file, so the file is completed (the xlsx written)
 * but stays open to the deck; a different deck's first row, or the exit,
 * closes it */
void
MCSAVEcircuitFreed(struct circ *ci)
{
    if (owner && ci && same_circuit(ci))
        if (fmt == FMT_XLSX && nrows > 0)
            xlsx_write();
}

void
MCSAVEfinish(void)
{
    mcs_complete();
    mcs_reset_file();
    mcs_free_used();                            /* Enhancement-615 */
}

void
MCSAVErun(const char *analysis, int ok)
{
    char *given = NULL;
    int i, n, first;

    if (!ft_curckt)
        return;
    if (!mcs_option(&given)) {
        tfree(given);
        return;
    }
    if (owner && !same_circuit(ft_curckt)) {    /* a different deck: a new file */
        mcs_complete();
        mcs_reset_file();
    }
    if (owner && unwritable) {                  /* said at the first row; nothing more */
        tfree(given);
        return;
    }
    first = !owner;
    if (first)
        cols_prune_for_new_owner();

    /* the OSDI parameters with declared statistics, as the devices hold them.
     * Enhancement-618 (hunt F19): once the file has OSDI columns they are
     * read on every row, option on or off -- after `unset osdimc` the rows
     * used to repeat the last trial's draws while the devices had been put
     * back to their nominals (or swept). */
    if (ft_curckt->ci_ckt && (OSDImcEnabled() || cols_have_osdi())) {
        OSDImcSnapshot(ft_curckt->ci_ckt, osdi_cb, NULL);
    } else if (ft_curckt->ci_ckt && !noted_osdimc_off && OSDImcHasStats(ft_curckt->ci_ckt)) {
        fprintf(cp_err, "Note: savemc: the deck's OSDI models declare statistics, but "
                        "`.option osdimc` is off, so they are not drawn and not recorded\n");
        noted_osdimc_off = 1;
    }

    for (i = n = 0; i < ncols; i++)
        if (col_wanted(i))
            n++;
    if (n == 0) {
        if (!noted_nothing) {
            fprintf(cp_err, "Note: savemc: nothing to record -- no %sparameter with "
                            "statistics in this circuit%s\n",
                    osdi_only ? "OSDI " : "",
                    osdi_only ? " (automc_save records OSDI parameters only)" : "");
            noted_nothing = 1;
        }
        tfree(given);
        return;
    }

    if (first) {
        char *why = NULL;
        int ok = 0;
        owner = 1;
        owner_file = copy(ft_curckt->ci_filename ? ft_curckt->ci_filename : "");
        owner_name = copy(ft_curckt->ci_name ? ft_curckt->ci_name : "");
        path = mcs_path(given);
        /* Enhancement-615 (hunt F17): a name another deck wrote in this
         * session is kept; this deck gets the next free variant */
        if (given) {
            const char *by = mcs_used_by(path);
            if (by) {
                char *alt = mcs_unused_variant(path);
                fprintf(cp_out, "Note: savemc: %s holds the rows of '%s' from earlier in "
                                "this session and is kept; this deck's rows go to %s\n",
                        path, by, alt);
                tfree(path);
                path = alt;
            }
        }
        /* Enhancement-613: a given name's directories are made; a name that
         * still cannot be opened is reported with the reason and the rows go
         * to the dated default beside the netlist; when that fails too the
         * recorder says so and records nothing for this circuit */
        if (given) {
            char *mkwhy = NULL;
            (void) mcs_mkdirs(path, &mkwhy);
            ok = mcs_can_open(path, &why);
            if (!ok) {
                char *fallback = mcs_path(NULL);
                fprintf(cp_err, "Warning: savemc: cannot open %s (%s); recording to %s "
                                "instead\n",
                        path, mkwhy ? mkwhy : why, fallback);
                tfree(why);
                tfree(path);
                path = fallback;
            }
            tfree(mkwhy);
        }
        if (!ok && !mcs_can_open(path, &why)) {
            fprintf(cp_err, "Error: savemc: cannot open %s (%s); nothing is recorded for "
                            "this circuit\n", path, why);
            tfree(why);
            unwritable = 1;
            tfree(given);
            return;
        }
        mcs_note_used(path, owner_name);        /* Enhancement-615 */
        fprintf(cp_out, "Note: savemc: recording the %d parameter%s with statistics, "
                        "one row per analysis run, to %s\n",
                n, n == 1 ? "" : "s", path);
    }
    tfree(given);

    /* the row */
    if (nrows == caprows) {
        caprows = caprows ? 2 * caprows : 64;
        rows = TREALLOC(double *, rows, caprows);
        rowcols = TREALLOC(int, rowcols, caprows);
        rowan = TREALLOC(char *, rowan, caprows);
        rowst = TREALLOC(char *, rowst, caprows);
    }
    rows[nrows] = TMALLOC(double, ncols);
    for (i = 0; i < ncols; i++)
        rows[nrows][i] = cols[i].set && !cols[i].written ? cols[i].value : NAN;
    rowcols[nrows] = ncols;
    rowan[nrows] = copy(analysis ? analysis : "?");
    rowst[nrows] = copy(ok ? "ok" : "failed");
    nrows++;

    if (fmt == FMT_XLSX) {
        if (nrows == 1 || nrows % 25 == 0)
            xlsx_write();
        return;
    }
    if (!fp || header_cols != ncols) {
        text_rewrite();                 /* the first row, or a new column */
        return;
    }
    lastrow_off = ftell(fp);
    text_row(fp, nrows - 1);
    fflush(fp);
}

/* ------------------------------------------------------------ Enhancement-611 */

int
MCSAVEactive(void)
{
    char *given = NULL;
    int on = mcs_option(&given);
    tfree(given);
    return on;
}

/* a value computed after the run goes onto the run's row: `writemc` in a
 * loop, montecarlo's -writemc per sample. The column is added on first use
 * (a row that never gets it is empty there); for csv/txt the last line is
 * rewritten in place -- the file stays complete row by row -- and a new
 * column rewrites the file once, for its header. */
int
MCSAVEappend(const char *name, double value)
{
    struct mcs_col *c;
    int i, newcol = 0;

    if (!MCSAVEactive())
        return -2;
    if (owner && unwritable)
        return -3;
    if (!owner || nrows == 0)
        return -1;
    c = col_find(name);
    if (!c) {
        c = col_add(name, 0, 0);
        c->written = 1;
        newcol = 1;
    } else if (!c->written) {
        /* the name of a draw: keep the draw's column, the value goes on
         * as `<name>*` beside it */
        char *alt = tprintf("%s*", name);
        int r = MCSAVEappend(alt, value);
        tfree(alt);
        return r;
    }
    i = (int) (c - cols);
    if (rowcols[nrows - 1] < ncols) {
        int k;
        rows[nrows - 1] = TREALLOC(double, rows[nrows - 1], ncols);
        for (k = rowcols[nrows - 1]; k < ncols; k++)
            rows[nrows - 1][k] = NAN;
        rowcols[nrows - 1] = ncols;
    }
    rows[nrows - 1][i] = value;

    if (fmt == FMT_XLSX) {
        if (nrows % 25 == 0)
            xlsx_write();
        return 0;
    }
    if (newcol || !fp || lastrow_off < 0 || header_cols != ncols) {
        text_rewrite();
        return 0;
    }
    if (fseek(fp, lastrow_off, SEEK_SET) == 0) {
        int fd = fileno(fp);
        if (ftruncate(fd, lastrow_off) == 0) {
            text_row(fp, nrows - 1);
            fflush(fp);
            return 0;
        }
    }
    text_rewrite();
    return 0;
}

/* evaluate one writemc item on the current plot: a scalar, or the message */
static int
mcs_eval_scalar(const char *expr, double *out, char **why)
{
    struct pnode *pn = ft_getpnames_from_string_quotes(expr, TRUE);
    struct dvec *v;
    int ok = 0;

    *why = NULL;
    if (!pn) {
        *why = copy("it does not evaluate");
        return 0;
    }
    v = ft_evaluate(pn);
    if (!v || v->v_length < 1) {
        *why = copy("it names no vector of the current plot");
    } else if (v->v_length != 1) {
        *why = tprintf("it has %d points and a row holds one number -- reduce it "
                       "(maximum, mean, ...) or index it ([0])", v->v_length);
    } else {
        *out = isreal(v) ? v->v_realdata[0]
                         : hypot(v->v_compdata[0].cx_real, v->v_compdata[0].cx_imag);
        ok = 1;
    }
    if (!pn->pn_value && v)
        vec_free(v);
    free_pnode(pn);
    return ok;
}

/* split `name=expr`: a leading identifier and one '=' (not '==') name the
 * column; otherwise the whole word is both the expression and the name */
static void
mcs_split_item(const char *word, char **name, char **expr)
{
    const char *q = word;
    if (isalpha_c(*q) || *q == '_') {
        while (isalnum_c(*q) || *q == '_')
            q++;
        if (*q == '=' && q[1] != '=' && q > word) {
            *name = copy_substring(word, q);
            *expr = copy(q + 1);
            return;
        }
    }
    *name = copy(word);
    *expr = copy(word);
}

void
com_writemc(wordlist *wl)
{
    static int said_off, said_nofile;
    wordlist *w;

    if (!wl) {
        fprintf(cp_err, "Usage: writemc [name=]<expression> ... -- each value onto the "
                        "savemc row of the last analysis run\n");
        return;
    }
    if (!MCSAVEactive()) {
        if (!said_off)
            fprintf(cp_err, "writemc: nothing is recorded -- `.option savemc` is not set "
                            "(said once)\n");
        said_off = 1;
        return;
    }
    for (w = wl; w; w = w->wl_next) {
        char *name, *expr, *why = NULL, *tok = cp_unquote(w->wl_word);
        double v;
        int r;
        mcs_split_item(tok, &name, &expr);
        tfree(tok);
        if (!mcs_eval_scalar(expr, &v, &why)) {
            fprintf(cp_err, "writemc: %s: %s\n", expr, why ? why : "?");
            tfree(why);
        } else {
            r = MCSAVEappend(name, v);
            if (r == -1)
                fprintf(cp_err, "writemc: no analysis has run yet, so there is no row to "
                                "put %s on\n", name);
            else if (r == -3 && !said_nofile)
                fprintf(cp_err, "writemc: savemc could not open a file for this circuit "
                                "(said above), so %s is not recorded (said once)\n", name);
            if (r == -3)
                said_nofile = 1;
        }
        tfree(name);
        tfree(expr);
    }
}
