"""Writes a self-contained HTML report from one triage run.

No server, no dependencies, no network. One file you open in a browser.
"""

from __future__ import annotations

import html
import json
import pathlib
import re
from collections import defaultdict
from typing import Any

CSS = """
:root{--bg:#fbfaf8;--card:#fff;--ink:#17171a;--mut:#6b6b73;--line:#e6e4e0;
--good:#1a7f4b;--warn:#a85c00;--acc:#5b3fd6;--code:#f4f2ef}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:25px;margin:0 0 4px;letter-spacing:-.02em}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--mut);
margin:30px 0 10px;font-weight:600}
.sub{color:var(--mut);margin:0 0 22px;font-size:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px 18px;margin:0 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 15px}
.kpi b{display:block;font-size:23px;letter-spacing:-.02em}
.kpi span{color:var(--mut);font-size:12px}
.cluster{border-left:3px solid var(--acc)}
.cluster h3{margin:0 0 3px;font-size:16px}
.cause{color:var(--acc);font-weight:600}
.iss{display:flex;gap:9px;padding:5px 0;border-top:1px solid var(--line);font-size:14px}
.iss:first-of-type{border-top:0}
.num{color:var(--mut);min-width:40px;font-variant-numeric:tabular-nums}
.tag{font-size:11px;padding:1px 7px;border-radius:20px;border:1px solid var(--line);
color:var(--mut);white-space:nowrap}
.tag.dup{color:var(--warn);border-color:#f0dfc4;background:#fdf7ee}
.tag.root{color:var(--good);border-color:#c8e6d4;background:#f1f9f4}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;color:var(--mut);font-weight:600;font-size:11px;
text-transform:uppercase;letter-spacing:.07em;padding:0 10px 7px 0;border-bottom:1px solid var(--line)}
td{padding:7px 10px 7px 0;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}
.who{font-weight:600;white-space:nowrap}
.act{white-space:nowrap}
.act.skipped{color:var(--warn)}
.act.investigated{color:var(--good)}
.act.derived,.act.explained{color:var(--acc);font-weight:600}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
pre{background:var(--code);border:1px solid var(--line);border-radius:8px;
padding:11px 13px;overflow-x:auto;margin:8px 0 0}
.ev{color:var(--mut);font-size:12.5px;padding:2px 0 2px 14px;border-left:2px solid var(--line);margin:3px 0}
.scroll{overflow-x:auto}
.note{color:var(--mut);font-size:13px;margin:8px 0 0}
.lead{border-left:3px solid var(--good)}
.lead p{margin:0;font-size:15.5px;line-height:1.6}
h2.plain{margin:0 0 7px;font-size:12px}
.why{color:var(--mut);font-size:12.5px}
.step{padding:7px 0;border-top:1px solid var(--line);font-size:14px}
.step:first-child{border-top:0}
.sub{color:var(--mut);font-size:12.5px;padding:2px 0 0 2px}
.lead p{margin:0 0 9px}
.cause{background:var(--code);border-radius:7px;padding:9px 12px;font-size:14.5px}
.grouped{margin:0 0 10px}
.grouped .iss{padding:4px 0}
.cz{color:var(--acc);font-size:12px;min-width:130px}

/* the picture. two colour roles only: a shared cause, and a singleton. */
svg{display:block;margin:4px 0 2px}
.sg-hd{font:600 10px ui-monospace,Menlo,monospace;letter-spacing:.1em;fill:var(--mut)}
.sg-box{fill:var(--card);stroke:var(--line);stroke-width:1}
.sg-box.sg-on{fill:#f4f1fe;stroke:#d9d0f8}
.sg-ref{font:600 12px ui-monospace,Menlo,monospace;fill:var(--mut)}
.sg-ti{font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;fill:var(--ink)}
.sg-ln{fill:none;stroke:var(--line);stroke-width:1.5}
.sg-ln.sg-on{stroke:var(--acc);stroke-width:2;stroke-opacity:.55}
.sg-cz{fill:var(--card);stroke:var(--line);stroke-width:1}
.sg-cz.sg-on{fill:#efeafd;stroke:var(--acc)}
.sg-cn{font:600 13px ui-monospace,Menlo,monospace;fill:var(--ink)}
.sg-cn.sg-on{fill:var(--acc)}
.sg-ct{font:11.5px -apple-system,BlinkMacSystemFont,sans-serif;fill:var(--mut)}
"""


def _count_and_cause(detail: str) -> tuple[int, str]:
    """Pull the number and the cause out of "5 separate events concern X"."""
    m = re.match(r"(\d+) separate events concern ([\w-]+)", detail or "")
    return (int(m.group(1)), m.group(2)) if m else (0, (detail or "")[:40])


def _readable(line: str) -> str:
    """Turn an internal note into something a reader understands."""
    line = re.sub(r"^#(\d+) reported, same cause as known ([\w-]+)$",
                  r"issue #\1, matched to \2", line or "")
    line = re.sub(r"^#(\d+) reported and reproduced$",
                  r"issue #\1, reproduced by an agent", line)
    line = re.sub(r"^root cause ([\w-]+): ", r"\1 — ", line)
    return line.rstrip(";")


# One sentence per kind of thing an agent did.
_SAYS = {
    "opened": "split the inbox into items any agent could pick up.",
    "investigated": "picked up {issue}, found nothing about it in memory, and recorded a new cause: {cause}.",
    "deferred": "picked up {issue} and reached the same cause as another agent at the same moment, so it logged the issue instead of writing the cause twice.",
    "skipped": "picked up {issue}, read the cause another agent had already written, and did no further work.",
    "derived": "counted issues that shared a cause and wrote the conclusion itself.",
    "read": "read every cause the investigators had recorded.",
    "corrected": "changed its mind about one cause, and kept the old answer marked out of date.",
    "applied rule": "read an escalation rule out of memory and followed it.",
    "escalated": "escalated a cause, because it crossed the stored threshold.",
    "below rule": "left a cause alone, because it was under the stored threshold.",
    "no rule": "found no escalation rule in memory, so it escalated nothing.",
    "handoff": "handed the batch to the next agent.",
    "picked up": "took over the batch with nothing but a user id and a job id, and could state every note the others had written.",
    "recognised": "saw a brand new issue and recognised it from memory, in a fresh process.",
    "unknown": "saw a brand new issue and had no memory of it.",
    "explained": "answered \u201cwhy do you believe that?\u201d by following the arrows to the evidence.",
    "belief changed": "showed what the crew used to believe and what replaced it.",
}


def _sentence(e: dict, titles: dict[str, str]) -> str:
    says = _SAYS.get(e["action"])
    if not says:
        return ""
    issue = e.get("issue") or ""
    cause = ""
    m = re.search(r"Cause: ([\w-]+)", e.get("detail") or "")
    if m:
        cause = m.group(1)
    text = says.format(issue=issue or "an issue", cause=cause or "a cause")
    out = html.escape(text)
    if issue and titles.get(issue):
        out += f"<div class=sub>{html.escape(issue)} {html.escape(titles[issue])}</div>"
    return out


def _cluster(timeline: list[dict], issues: list[dict]) -> dict[str, dict]:
    """Group issues by cause.

    All three outcomes count. A deferred issue was dropped from an earlier
    version of this report, so a cause showed four reports when it had five.
    """
    by_cause: dict[str, dict] = defaultdict(lambda: {"root": None, "dups": []})
    for e in timeline:
        if e["action"] not in ("investigated", "skipped", "deferred") or not e.get("issue"):
            continue
        detail = e.get("detail", "")
        cause = "unclassified"
        for token in ("session-expiry", "pdf-export", "search-performance",
                      "docs-copy", "theme-persistence", "platform-path", "unknown"):
            if token in detail:
                cause = token
                break
        row = {"issue": e["issue"], "agent": e["agent"],
               "prior_read": e.get("prior_read", 0), "how": e["action"]}
        if e["action"] == "investigated":
            by_cause[cause]["root"] = row
        else:
            by_cause[cause]["dups"].append(row)
    return by_cause



# ----------------------------------------------------------------- the picture

ROW = 34          # vertical space per issue
PAD = 26
L_W, GAP, R_W = 330, 230, 300
BOX_H = 26


def _diagram(clusters: dict[str, dict], titles: dict[str, str],
             timeline: list[dict]) -> str:
    """Issues on the left, causes on the right, lines between them.

    The data has a known shape, so no layout engine is needed. Issues stack in
    their cause groups, and each cause sits beside its own group. Five lines
    meeting one box is the whole story of the run.
    """
    groups = []
    for cause, grp in clusters.items():
        rows = ([grp["root"]] if grp["root"] else []) + grp["dups"]
        rows = sorted(rows, key=lambda r: int(r["issue"].lstrip("#")))
        groups.append((len(rows), cause, rows))
    groups.sort(key=lambda g: (-g[0], g[1]))
    if not groups:
        return ""

    corrected = _corrected_causes(timeline)
    total_rows = sum(n for n, _, _ in groups)
    height = PAD * 2 + total_rows * ROW
    width = L_W + GAP + R_W

    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'style="max-width:{width}px" role="img" '
           f'aria-label="Issues on the left, their causes on the right">']
    out.append(f'<text x="0" y="14" class="sg-hd">{total_rows} ISSUES</text>')
    out.append(f'<text x="{L_W + GAP}" y="14" class="sg-hd">CAUSE THE CREW FOUND</text>')

    y = PAD
    for n, cause, rows in groups:
        shared = n > 1
        cls = "sg-on" if shared else "sg-off"
        cy = y + (n * ROW) / 2 - ROW / 2 + BOX_H / 2

        for i, r in enumerate(rows):
            ry = y + i * ROW
            ref = r["issue"]
            out.append(
                f'<rect x="0" y="{ry}" width="{L_W}" height="{BOX_H}" rx="5" '
                f'class="sg-box {cls}"/>'
                f'<text x="9" y="{ry + 17}" class="sg-ref">{html.escape(ref)}</text>'
                f'<text x="44" y="{ry + 17}" class="sg-ti">'
                f'{html.escape(_short(titles.get(ref, ""), 36))}</text>'
            )
            x1, y1 = L_W, ry + BOX_H / 2
            x2 = L_W + GAP
            mid = x1 + GAP / 2
            out.append(
                f'<path d="M{x1} {y1} C{mid} {y1} {mid} {cy} {x2} {cy}" '
                f'class="sg-ln {cls}"/>'
            )

        tag = "  corrected later" if cause in corrected else ""
        label = "reports" if n != 1 else "report"
        out.append(
            f'<rect x="{L_W + GAP}" y="{cy - BOX_H / 2}" width="{R_W}" '
            f'height="{BOX_H}" rx="5" class="sg-cz {cls}"/>'
            f'<text x="{L_W + GAP + 11}" y="{cy + 5}" class="sg-cn {cls}">'
            f'{html.escape(cause)}</text>'
            f'<text x="{L_W + GAP + R_W - 11}" y="{cy + 5}" class="sg-ct" '
            f'text-anchor="end">{n} {label}{html.escape(tag)}</text>'
        )
        y += n * ROW

    out.append("</svg>")
    return "".join(out)


def _cause_text(timeline: list[dict], cause: str) -> str:
    """The plain explanation an agent wrote for this cause."""
    for e in timeline:
        if e["action"] != "investigated":
            continue
        d = e.get("detail") or ""
        if f"Cause: {cause}" in d and "\u2014" in d:
            return d.split("\u2014", 1)[1].strip().rstrip(".")
    return ""


def _short(title: str, n: int = 64) -> str:
    if len(title) <= n:
        return title
    cut = title[:n].rsplit(" ", 1)[0]
    return cut + "\u2026"


def _summary(clusters: dict[str, dict], issues: list[dict],
             timeline: list[dict], titles: dict[str, str]) -> str:
    """Name the bug, name the issues, name the other causes.

    Counts on their own say nothing. A reader wants to know which issues were
    the same bug and what that bug was.
    """
    sized = []
    for cause, grp in clusters.items():
        rows = ([grp["root"]] if grp["root"] else []) + grp["dups"]
        sized.append((len(rows), cause, rows))
    sized.sort(reverse=True)
    if not sized:
        return "<p>No issues were triaged in this run.</p>"

    out: list[str] = []
    n, cause, rows = sized[0]

    if n > 1:
        explain = _cause_text(timeline, cause)
        out.append(f"<p><b>{n} of these {len(issues)} issues are the same bug.</b></p>")
        if explain:
            out.append(f"<p class=cause>The cause: {html.escape(explain)}.</p>")
        out.append("<div class=grouped>")
        for r in sorted(rows, key=lambda x: int(x["issue"].lstrip('#'))):
            ref = r["issue"]
            out.append(f"<div class=iss><span class=num>{html.escape(ref)}</span>"
                       f"<span>{html.escape(_short(titles.get(ref, '')))}</span></div>")
        out.append("</div>")
        out.append("<p class=note>They share almost no wording. One agent worked out "
                   f"the cause. The other {n - 1} read it from memory, or reached it at "
                   "the same moment, and none of them repeated the work.</p>")

    corrected = _corrected_causes(timeline)
    rest = [(ref, c) for _, c, rows in sized[1:] for ref in
            (r["issue"] for r in rows)]
    if rest:
        out.append(f"<p><b>The other {len(rest)} are separate problems.</b></p>"
                   f"<div class=grouped>")
        for ref, c in sorted(rest, key=lambda x: int(x[0].lstrip("#"))):
            flag = ""
            if c in corrected:
                flag = ("<span class='tag dup'>the triager corrected this one "
                        "later</span>")
            out.append(f"<div class=iss><span class=num>{html.escape(ref)}</span>"
                       f"<span class=cz>{html.escape(c)}</span>"
                       f"<span>{html.escape(_short(titles.get(ref, ''), 48))}"
                       f"{flag}</span></div>")
        out.append("</div>")
    return "".join(out)


def _corrected_causes(timeline: list[dict]) -> set[str]:
    """Causes a later agent superseded, so the summary can flag them."""
    out: set[str] = set()
    for e in timeline:
        if e["action"] != "belief changed":
            continue
        for line in (e.get("extra") or {}).get("replaced", []):
            m = re.match(r"root cause ([\w-]+)", line or "")
            if m:
                out.add(m.group(1))
    return out


def write_report(p: dict[str, Any], path: pathlib.Path) -> None:
    esc = html.escape
    titles = {f"#{i['number']}": i["title"] for i in p["issues"]}
    clusters = _cluster(p["timeline"], p["issues"])
    c = p["counts"]
    pct = p.get("percentiles") or {}

    out: list[str] = []
    A = out.append
    A(f"<!doctype html><meta charset=utf-8><title>Auryn Triage Desk — {esc(p['repo'])}</title>")
    A(f"<style>{CSS}</style><div class=wrap>")
    A(f"<h1>Auryn Triage Desk</h1>")
    A(f"<p class=sub><code>{esc(p['repo'])}</code> &nbsp;·&nbsp; tenant <code>{esc(p['tenant'])}</code>"
      f" &nbsp;·&nbsp; {len(p['issues'])} open issues &nbsp;·&nbsp; run took {p['elapsed_s']}s</p>")

    A(f"<div class='card lead'><h2 class=plain>What happened</h2>"
      f"{_summary(clusters, p['issues'], p['timeline'], titles)}</div>")

    A("<div class=grid>")
    for val, lab in ((len(p["issues"]), "issues in the inbox"),
                     (c["investigated"], "different causes found"),
                     (c.get("recognised", 0) + c.get("deferred", 0),
                      "issues matched to a cause another agent found"),
                     (c["duplicated"], "issues investigated twice")):
        A(f"<div class=kpi><b>{val}</b><span>{esc(lab)}</span></div>")
    A("</div>")

    A("<h2>How the issues group</h2><div class=card>")
    A(_diagram(clusters, titles, p["timeline"]))
    A("<p class=note>Each line is one issue pointing at the cause an agent "
      "recorded for it. Five lines meeting one box is the run in one picture.</p>")
    A("</div>")

    A("<h2>What the crew worked out on its own</h2>")

    # One entry per conclusion. The same derived fact arrives twice in the
    # timeline, once when written and once when the auditor reads it back.
    seen_detail: set[str] = set()
    shown = 0
    for e in p["timeline"]:
        if e["action"] not in ("derived", "explained"):
            continue
        _, cause = _count_and_cause(e["detail"])
        if cause in seen_detail:
            continue
        seen_detail.add(cause)
        shown += 1
        # Count the evidence, not the number baked into the note. The note is
        # written when the threshold is crossed, and more issues arrive after.
        evidence = (e.get("extra") or {}).get("evidence", [])
        n = len(evidence)
        A(f"<div class=card><b>Nobody told it this.</b> {n} separate issues "
          f"reported the same cause, <b>{esc(cause)}</b>, so it wrote that down "
          f"itself. Here are the {n} it counted:")
        for line in evidence:
            A(f"<div class=ev>{esc(_readable(line))}</div>")
        A("</div>")

    for e in p["timeline"]:
        if e["action"] != "belief changed":
            continue
        for line in (e.get("extra") or {}).get("replaced", []):
            A(f"<div class=card><b>It changed its mind.</b>"
              f"<div class=ev>first thought: {esc(_readable(line))}</div>"
              f"<div class=ev>now: {esc(_readable(e['detail']))}</div>"
              f"<p class=note>The first answer is kept and marked out of date, so "
              f"the change is traceable.</p></div>")
        shown += 1

    for e in p["timeline"]:
        if e["action"] == "applied rule":
            A(f"<div class=card><b>It followed a rule stored in memory.</b>"
              f"<div class=ev>{esc(e['detail'])}</div>"
              f"<p class=note>That threshold is not written in the code. Change "
              f"the memory and the crew escalates differently, with no code "
              f"change.</p></div>")
            shown += 1

    if not shown:
        A("<div class=card>Nothing crossed the threshold in this run.</div>")
    A("<p class=note>No language model took part in any of the above. The crew "
      "counted issues that shared a cause.</p>")

    A("</div>")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(out))
