/*************
 * Header file for subckt.c
 * 1999 E. Rouat
 ************/

#ifndef ngspice_SUBCKT_H
#define ngspice_SUBCKT_H

struct card *inp_subcktexpand(struct card *deck);
/* Enhancement-449: `.option autobus` is consumed from the option card lists by
   the caller, because those cards are no longer in the deck by the time
   inp_subcktexpand() runs and the option variable is not published yet. */
void inp_set_autobus(bool onoff, bool kicad);
bool inp_get_autobus(bool *kicad);          /* Enhancement-628 */
/* Enhancement-628 (hunt F11): the port widths of an OSDI instance line's model,
   resolved through the deck's own .model cards and the registered module (E-464's
   lookup, on any deck), and the model name of an instance line. */
struct IFdevice;
int inp_osdi_port_widths(struct card *deck, const char *modelname, int *start, int *cnt,
                         int maxp, struct IFdevice **devout);
char *inp_model_of_line(const char *line);
struct card *inp_deckcopy(struct card *deck);
struct card *inp_deckcopy_oc(struct card *deck);
struct card *inp_deckcopy_ln(struct card *deck);

#endif
