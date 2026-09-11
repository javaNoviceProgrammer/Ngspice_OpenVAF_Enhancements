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
#include "mcsave.h"
#include <time.h>
#include <ctype.h>
#include <math.h>

enum { FMT_CSV, FMT_TXT, FMT_XLSX };

struct mcs_col {
    char *name;
    int osdi;                       /* an OSDI parameter, read per row */
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
static int noted_nothing;
static int noted_osdimc_off;

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
col_add(const char *name, int osdi)
{
    if (ncols == capcols) {
        capcols = capcols ? 2 * capcols : 16;
        cols = TREALLOC(struct mcs_col, cols, capcols);
    }
    cols[ncols].name = copy(name);
    cols[ncols].osdi = osdi;
    cols[ncols].value = NAN;
    cols[ncols].set = 0;
    cols[ncols].gen = gen;
    return &cols[ncols++];
}

static void
col_set(const char *name, double value, int osdi)
{
    struct mcs_col *c = col_find(name);
    if (!c)
        c = col_add(name, osdi);
    c->value = value;
    c->set = 1;
    c->gen = gen;
}

void
MCSAVEparam(const char *name, double value)
{
    if (!name || !*name)
        return;
    col_set(name, value, 0);
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
        if (cols[i].osdi || (!cols[i].set && cols[i].gen != gen)) {
            tfree(cols[i].name);
        } else {
            cols[k++] = cols[i];
        }
    }
    ncols = k;
}

static void
osdi_cb(const char *owner_name, const char *param, double value, void *ctx)
{
    char *name = tprintf("@%s[%s]", owner_name, param);
    NG_IGNORE(ctx);
    col_set(name, value, 1);
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
    return !osdi_only || cols[i].osdi;
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
    if (!fp)
        return;
    text_header(fp);
    for (r = 0; r < nrows; r++)
        text_row(fp, r);
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

static void
xlsx_str_cell(DSTRING *d, int col0, int row1, const char *s)
{
    ds_cat_str(d, "<c r=\"");
    cell_ref(d, col0, row1);
    ds_cat_str(d, "\" t=\"inlineStr\"><is><t>");
    xml_text(d, s);
    ds_cat_str(d, "</t></is></c>");
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
        "<fonts count=\"1\"><font><sz val=\"11\"/><name val=\"Calibri\"/></font></fonts>"
        "<fills count=\"2\"><fill><patternFill patternType=\"none\"/></fill><fill><patternFill patternType=\"gray125\"/></fill></fills>"
        "<borders count=\"1\"><border><left/><right/><top/><bottom/><diagonal/></border></borders>"
        "<cellStyleXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\"/></cellStyleXfs>"
        "<cellXfs count=\"1\"><xf numFmtId=\"0\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"/></cellXfs>"
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
            xlsx_str_cell(&sheet, c++, 1, cols[i].name);
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
        ds_free(&sheet);
        return;
    }
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
    noted_nothing = 0;
    noted_osdimc_off = 0;
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
    first = !owner;
    if (first)
        cols_prune_for_new_owner();

    /* the OSDI parameters with declared statistics, as the devices hold them */
    if (ft_curckt->ci_ckt && OSDImcEnabled()) {
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
        owner = 1;
        owner_file = copy(ft_curckt->ci_filename ? ft_curckt->ci_filename : "");
        owner_name = copy(ft_curckt->ci_name ? ft_curckt->ci_name : "");
        path = mcs_path(given);
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
        rows[nrows][i] = cols[i].set ? cols[i].value : NAN;
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
    text_row(fp, nrows - 1);
    fflush(fp);
}
