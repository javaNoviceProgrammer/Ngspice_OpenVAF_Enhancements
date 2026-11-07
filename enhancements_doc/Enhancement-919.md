# Enhancement-919: the prompt ends at the end of its input with an X display open — `ngspice -i` with piped input spun there for good

**Scope:** found by the local regression sweep of E-918, where
[`sourcenest_examples`](../examples/sourcenest_examples/) [7] timed out on a machine running XQuartz.

ngspice:
- `main.c` (`app_event_func`, a new `app_rl_input_at_end`).

**ngspice only.**

**Suites:**
- [`x11eof_examples`](../examples/x11eof_examples/) (new): 14 checks with an X display, 6 of which
  fail on E-918. 7 checks without one, none of which fail on E-918.
- [`sourcenest_examples`](../examples/sourcenest_examples/): 9 of 9 with a display, where it hung
  at [7] on E-918.
- The full sweep, `--jobs 8`: 606 of 606 with `DISPLAY` set and 606 of 606 with it unset.

## What was wrong

With a display, ngspice sets `rl_event_hook` so plot windows keep working while it waits at the
prompt. Readline then waits in this loop instead of calling `read()` (`rl_read_key`, the same in
readline 8.1 and 8.3):

```c
while (rl_event_hook) {
    if (rl_get_char(&c) != 0)
        break;
    if ((r = rl_gather_tyi()) < 0)      /* an error such as EIO */
        ...
    else if (r > 0)                     /* read something */
        continue;
    ...
    (*rl_event_hook)();
}
```

At the end of a pipe or a file, `select` says the input is readable and `FIONREAD` says 0 bytes.
`rl_gather_tyi` returns 0, and the hook's `X11_Input` returns at once, because its own `select` says
the same. Nothing in the loop ever reads, so the end of the input is never seen.

| input | E-918, with a display |
|---|---|
| a pipe closed with nothing written | spins, about 40% of a core, until killed |
| a pipe closed after commands | they run, then it spins |
| a file | its lines run, then it spins |
| `/dev/null` | exits: readline's own end-of-input path handles it |

No display, no hang: `DevInit` falls back to the error device, no hook is set and readline reaches
its `read()`. That is why CI, whose runners have no `DISPLAY`, never showed this, and why the sweep
passes or fails `sourcenest` according to whether XQuartz is running.

## What changed

`app_event_func` checks for that state after `X11_Input` returns, and calls `rl_stuff_char(EOF)`:

```c
if (app_rl_input_at_end())
    rl_stuff_char(EOF);
```

That is what `rl_gather_tyi` itself does at the end of the input on its other path. It stuffs a
newline, so a last line with no newline is still accepted, and leaves `EOF` pending, so the next
`readline()` returns NULL and `app_rl_readlines` quits as it always does there.

`app_rl_input_at_end` asks `select` again, with no wait, before it believes `FIONREAD`. `X11_Input`
also returns when a signal interrupts its `select`, with nothing to read. Without the second
`select`, resizing a terminal ended the session; `x11eof` [7] fails on that build.

Taking the hook away at the end of the input from inside the hook is not an option: the loop above
would fall out with `c` unset.

## Results

| suite | E-918 | E-919 |
|---|---|---|
| `x11eof`, with a display | 8 of 14: [1] to [6] of the display half hang | 14 of 14 |
| `x11eof`, no display | 7 of 7 | 7 of 7 |
| `sourcenest`, with a display | hangs at [7] | 9 of 9 |
| full sweep, `DISPLAY` set | 604 of 605 | 606 of 606 |
| full sweep, `DISPLAY` unset | 605 of 605 | 606 of 606 |

One small difference remains in the output with a display: when input ends after a complete line,
one more empty prompt prints before `ngspice-46 done`. The exit status and the commands that run are
the same as without a display.

All of this ran on macOS arm64 with readline 8.3.6, XQuartz and Python 3.15.2.

## Not done

- **Linux with a display, and other readline versions, were not run.** `rl_read_key` and
  `rl_stuff_char` read the same in the 8.1 source, which is what Ubuntu 22.04 ships.
- **BSD editline builds are unchanged.** The fix is under `HAVE_GNUREADLINE`, and nothing here shows
  whether an editline build has this hang.
- **CI cannot guard this.** Its runners have no display, so the display half of `x11eof` reports
  `SKIP` there. Running that half on CI would need an X server on the runners, such as Xvfb.
