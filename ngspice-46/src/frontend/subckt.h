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
struct card *inp_deckcopy(struct card *deck);
struct card *inp_deckcopy_oc(struct card *deck);
struct card *inp_deckcopy_ln(struct card *deck);

#endif
