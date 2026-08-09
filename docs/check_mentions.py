#!/usr/bin/env python3
"""Fail if any Markdown contains an `@token` that GitHub will render as a user mention.

WHY THIS EXISTS. Release notes for Enhancements 419, 427 and 430 contained
`@dev[param]`, `@n1[n]` and `@181 it` written outside a code span. GitHub parses
those as @-mentions: it linked the profiles of real, uninvolved accounts (`@dev`
is a person, so are `@n1` and the four numeric handles in E-419's benchmark
table), listed them under "Contributors" on the release pages, and emailed them.

Every `@token` this project writes is a SPICE accessor (`@r1[i]`, `@x1.rmod[res]`,
`@inst[param]`) or a shorthand for "at N" (`@181 it`, `@1kHz`). None is ever a
person. So the rule is simply: put them in backticks, like the same tokens are
written everywhere else.

WHAT COUNTS AS SAFE. GitHub does not create a mention when the `@` is preceded by
a word character (so `noreply@anthropic.com` is fine) or when it sits inside a
code span. Everything else is treated as a live mention here, whether or not the
handle is registered today -- an unregistered one can be claimed tomorrow.

THE SCANNING TRAP THIS SCRIPT EXISTS TO AVOID. The obvious way to blank inline
code is `re.sub(r"`[^`]*`", "", text)`, and it is wrong: with no newline in the
character class the pairing runs ACROSS lines, so a backtick late on one line
pairs with one early on the next and the correctly-quoted tokens between them are
reported as bare. That over-reported by 2x when this was first investigated.
Inline code cannot span lines, so the pattern must exclude newlines.

Usage:
    python3 docs/check_mentions.py                 # every tracked *.md
    python3 docs/check_mentions.py FILE [FILE...]  # specific files
    python3 docs/check_mentions.py --stdin         # e.g. a release body on a pipe

Exits 0 when clean, 1 when a live mention is found.
"""
import re
import subprocess
import sys

# A token GitHub would linkify: '@' not preceded by a word char or backtick, then
# a handle-shaped run. GitHub handles are alphanumeric plus '-'.
MENTION = re.compile(r"(?<![\w`])@([A-Za-z0-9][A-Za-z0-9-]*)")

# The whole SPICE-ish token, so the report can suggest the exact replacement.
TOKEN = re.compile(r"@[A-Za-z0-9_][A-Za-z0-9_.\-]*(?:\[[^\]\n]*\])?")


def code_spans(text):
    """Ranges covered by fenced blocks, indented blocks, or inline code.

    Inline code is matched WITHOUT newlines -- see the trap in the docstring.
    """
    spans = [m.span() for m in re.finditer(r"```.*?```", text, re.S)]
    spans += [m.span() for m in re.finditer(r"~~~.*?~~~", text, re.S)]
    spans += [m.span() for m in re.finditer(r"`[^`\n]*`", text)]
    spans += [m.span() for m in re.finditer(r"<!--.*?-->", text, re.S)]
    # four-space indented code blocks
    for m in re.finditer(r"(?m)^(?: {4}|\t).*$", text):
        spans.append(m.span())
    return spans


def find(text):
    """Yield (line, column, handle, full_token) for every live mention."""
    spans = code_spans(text)
    for m in MENTION.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        tok = TOKEN.match(text, m.start())
        tok = tok.group().rstrip(".,;:") if tok else m.group()
        line = text.count("\n", 0, m.start()) + 1
        col = m.start() - (text.rfind("\n", 0, m.start()) + 1) + 1
        yield line, col, m.group(1), tok


def tracked_markdown():
    out = subprocess.run(["git", "ls-files", "*.md"],
                         capture_output=True, text=True).stdout
    return out.split()


def main(argv):
    if "--stdin" in argv:
        sources = [("<release notes>", sys.stdin.read())]
    else:
        paths = [a for a in argv if not a.startswith("-")] or tracked_markdown()
        sources = []
        for p in paths:
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    sources.append((p, fh.read()))
            except OSError as exc:
                print(f"cannot read {p}: {exc}", file=sys.stderr)
                return 1

    bad = 0
    for name, text in sources:
        for line, col, handle, tok in find(text):
            bad += 1
            print(f"{name}:{line}:{col}: `@{handle}` would be a GitHub mention "
                  f"-- write it as `{tok}`")

    if bad:
        print(f"\n{bad} live @-mention(s) in {len(sources)} source(s).")
        print("GitHub linkifies these, lists the account under Contributors on a "
              "release, and emails a stranger. Wrap the token in backticks.")
        return 1

    print(f"no live @-mentions in {len(sources)} source(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
