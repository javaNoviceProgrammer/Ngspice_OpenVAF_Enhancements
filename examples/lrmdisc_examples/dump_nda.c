#include <stdio.h>
#include <stdint.h>
#include <dlfcn.h>
typedef struct { char *name; uint32_t parent_type, parent, ddt, idt, attr_start, num_attr; } OsdiNature;
typedef union { char* s; int32_t i; double r; } AV;
typedef struct { char *name; uint32_t value_type; AV value; } OsdiAttribute;
/* Round-4 audit: the discipline table too. A discipline's attributes lie in
 * the same array as the natures', laid out [flow][potential][user] from
 * attr_start -- which is where LRM 3.6.2.5's overrides live. */
typedef struct { char *name; uint32_t flow, potential, domain, attr_start,
                 num_flow_attr, num_potential_attr, num_user_attr; } OsdiDiscipline;
int main(int argc, char **argv) {
    void *h = dlopen(argv[1], RTLD_NOW);
    if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
    OsdiNature *nat = dlsym(h, "OSDI_NATURES");
    uint32_t *nlen = dlsym(h, "OSDI_NATURES_LEN");
    OsdiAttribute *attrs = dlsym(h, "OSDI_ATTRIBUTES");
    uint32_t *alen = dlsym(h, "OSDI_ATTRIBUTES_LEN");
    if (!nat || !nlen || !attrs || !alen) { fprintf(stderr, "missing syms\n"); return 1; }
    printf("natures=%u total_attrs=%u\n", *nlen, *alen);
    for (uint32_t i = 0; i < *nlen; i++) {
        printf("nature %-24s attr_start=%u num_attr=%u\n", nat[i].name, nat[i].attr_start, nat[i].num_attr);
        for (uint32_t j = nat[i].attr_start; j < nat[i].attr_start + nat[i].num_attr && j < *alen; j++)
            printf("    attr[%u] name=%s type=%u\n", j, attrs[j].name, attrs[j].value_type);
    }
    OsdiDiscipline *disc = dlsym(h, "OSDI_DISCIPLINES");
    uint32_t *dlen = dlsym(h, "OSDI_DISCIPLINES_LEN");
    if (disc && dlen) {
        printf("disciplines=%u\n", *dlen);
        for (uint32_t i = 0; i < *dlen; i++) {
            printf("discipline %-20s flow_attr=%u potential_attr=%u user_attr=%u\n",
                   disc[i].name, disc[i].num_flow_attr, disc[i].num_potential_attr,
                   disc[i].num_user_attr);
            uint32_t n = disc[i].num_flow_attr + disc[i].num_potential_attr +
                         disc[i].num_user_attr;
            for (uint32_t j = 0; j < n && disc[i].attr_start + j < *alen; j++) {
                OsdiAttribute *a = &attrs[disc[i].attr_start + j];
                const char *side = j < disc[i].num_flow_attr ? "flow"
                    : j < disc[i].num_flow_attr + disc[i].num_potential_attr
                        ? "potential" : "user";
                if (a->value_type == 2)
                    printf("    %s.%s = %g\n", side, a->name, a->value.r);
                else if (a->value_type == 1)
                    printf("    %s.%s = %d\n", side, a->name, a->value.i);
                else
                    printf("    %s.%s = \"%s\"\n", side, a->name, a->value.s);
            }
        }
    }
    return 0;
}
