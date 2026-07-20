# Crash-hardening round 2 (Enhancement-244)

Two user-triggerable crashes found by argument-fuzzing the newer devices/commands
— both reproduce on the shipped binary, both fixed:

- **`nport` device** (`spicelib/devices/nport/nportsetup.c`) — the native n-port
  device (E-242) never checked that the instance line connected all `N+1` nodes the
  `.model`'s port count claims. A `.nport` with more ports than the instance wires
  (or `nports` past the device maximum) made `setup` stamp an **unbound (−1)** node
  into the sparse builder → `Row>=0 && Col>=0` assertion (SIGABRT) / out-of-bounds.
  Fixed by validating node binding and capping the port count → a clean error.

- **`pyplot`** (`frontend/com_pyplot.c`) — `pyplot -hist …` / `pyplot -contour …`
  (E-217/E-218) stripped the render-mode marker by unlinking and **freeing a node of
  the command's own argument wordlist**. When the marker was the *first* word it
  freed the list **head**, which the command loop then freed again →
  use-after-free (SIGSEGV). Fixed by detecting the marker without mutating the
  caller's list and handing `plotit` a filtered copy. (As a bonus, `-hist` as the
  first arg now renders the histogram it silently degraded to a line plot before.)

`verify_crashfix2.py` drives each repro and asserts it now exits gracefully (no
signal), that the diagnostics fire, and that valid forms still work — under both
linear solvers.

```
python3 verify_crashfix2.py
```
