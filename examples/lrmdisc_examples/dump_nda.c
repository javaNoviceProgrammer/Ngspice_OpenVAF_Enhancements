#include <stdio.h>
#include <stdint.h>
#include <dlfcn.h>
typedef struct { char *name; uint32_t parent_type, parent, ddt, idt, attr_start, num_attr; } OsdiNature;
typedef union { char* s; int32_t i; double r; } AV;
typedef struct { char *name; uint32_t value_type; AV value; } OsdiAttribute;
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
    return 0;
}
