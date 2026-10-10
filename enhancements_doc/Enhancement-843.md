# Enhancement-843: `source` nesting stops at 50 levels — a deck that sourced itself recursed until the stack overflowed

**Scope:** F6 of the
[robustness and correctness campaign of 2026-10-10](../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

ngspice:
- `frontend/inp.c`: `com_source` counts its nesting and refuses past 50 levels. The prompt a
  failed `source` drops to gets a control level of its own.
- `frontend/signal_handler.c`: an interrupt resets the count.
- `include/ngspice/fteext.h`: `inp_source_depth_reset`.
- `frontend/parser/lexical.c`: the lexer reports the end of its input.
- `main.c`: without readline, the main loop quits at the end of its input.

`examples/sourcenest_examples/` (new). **ngspice only.**

**Suites:**
- [`sourcenest_examples`](../examples/sourcenest_examples/): 9 of 9. 7 fail on the E-840
  binaries, 5 of them with SIGSEGV; the other 2 are controls.
- The full sweep: 551 of 551.

## What was wrong

```spice
* s.cir
r1 1 0 1k
v1 1 0 1
.control
source s.cir
.endc
.end
```

`ngspice -b s.cir` recursed `com_source → inp_spsource → cp_evloop → doblock → com_source` until
the stack overflowed. That is SIGSEGV after 3 932 levels and 1.3 s on macOS's 8 MB stack, about
2 KB a level. Two decks that source each other did the same. So did a `.spiceinit` that sources
itself, before the deck was read: `inp_source` reads it through `com_source`.

The netlist twin has been refused since Enhancement-212. `.include i.cir` inside `i.cir` stops
with "`.include nesting too deep (> 50 levels), likely a circular include`". `source` had no
such limit.

Alias loops and a `define` that calls itself were already refused. `mc_source` reloads the deck
without running its control block, so it cannot recurse.

## The change

`com_source` counts how deeply it is nested and refuses a 51st level:

```
Command 'source' failed:
Error: source nesting too deep (> 50 levels), likely a deck that sources itself:
    s.cir
    Simulation interrupted due to error!
```

It is handled like every other `source` failure, such as a missing file:
- In batch mode, ngspice exits with status 1.
- Under `set interactive`, which `ngspice -i` and a terminal session set, it drops to a prompt.

A file sourced from a loop at the top level stays at depth 1, so sequential sourcing has no
limit. A Ctrl-C longjmps back to the prompt past the decrements, so `ft_sigintr_cleanup`
resets the count, beside Enhancement-536's other resets. The suite does not exercise that
reset, since it needs a signal mid-source.

At 2 KB a level, 50 levels take about 100 KB of stack. That fits Windows' 1 MB main-thread
stack and a host's worker thread.

## The prompt a failed `source` drops to

Testing the refusal under `ngspice -i` showed that this prompt had two defects of its own. Both
were already reachable from a missing file.

**It ran away at the end of its input.** The prompt reads standard input through `cp_lexer`, and
the lexer had no case for `EOF`. EOF fell to the default branch, was appended to the current
word, and the next read was EOF again. The buffer doubled until a realloc of 2 GB failed:
`Error: realloc: can't allocate -2147483648 bytes`, exit 1. The original ngspice-46 lexer has
no EOF case either; with readline, the main loop never reaches it.

The lexer now ends a partial line at EOF as it would at a newline. With nothing read, it returns
NULL, which `cp_evloop` already takes as the end of the input. The prompt ends, and the block
that ran `source` goes on. A build without readline has a main loop that is a bare
`cp_evloop(NULL)`. Without the change below, that loop would now come straight back at EOF
forever, instead of running away. It now quits, as the readline loop does on its NULL line.
By the code, piped input to such a build used to end in the same runaway; that was not
rebuilt to watch. A scratch build with `--with-readline=no` now quits at EOF with status 0,
after an `echo` piped to it and with `/dev/null` as its input.

**Each command typed there ran twice.** The prompt recorded its commands on the control level
of the block that ran `source`. Once `source` returned, the block's loop walked on into them and
ran each a second time. While the prompt could only be left by `quit`, this never showed. The
prompt now runs on a control level of its own (`cp_pushcontrol`/`cp_popcontrol`, as
`inp_spsource` does for a deck's control block).

## The checks

`sourcenest_examples`:
- **[1]** A deck that sources itself is refused at level 50 with the message, exit 1. Its control
  block ran 51 times: the deck and 50 sources.
- **[2]** Two decks that source each other: the same.
- **[3]** A `.spiceinit` that sources itself: refused, exit 1.
- **[4]** A chain of 50 nested sources runs to the bottom (control).
- **[5]** A chain of 51 is refused at the 51st.
- **[6]** 60 sources one after another in a `repeat` loop all run (control).
- **[7]** `ngspice -i` with its input at end of file: refused, the prompt ends, the levels unwind,
  exit 0.
- **[8]** A command typed at that prompt runs once.
- **[9]** After a missing file, the same prompt: the typed command runs once, and the deck's
  block goes on.

[7] to [9] pipe their input, and run on POSIX systems only. On the E-840 binaries, [1] to [3],
[7] and [8] fail with SIGSEGV. [5] runs past 50 levels, and [9] ends in the realloc failure.
