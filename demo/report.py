"""Writes a self-contained HTML report from one triage run.

No server, no dependencies, no network. One file you open in a browser.
"""

from __future__ import annotations

import html
import json
import pathlib
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
"""


def _cluster(timeline: list[dict], issues: list[dict]) -> dict[str, dict]:
    """Group issues by the cause each investigator recorded."""
    by_cause: dict[str, dict] = defaultdict(lambda: {"root": None, "dups": []})
    for e in timeline:
        if e["action"] not in ("investigated", "skipped") or not e.get("issue"):
            continue
        detail = e.get("detail", "")
        cause = "unclassified"
        for token in ("session-expiry", "pdf-export", "search-performance",
                      "docs-copy", "theme-persistence", "platform-path", "unknown"):
            if token in detail:
                cause = token
                break
        row = {"issue": e["issue"], "agent": e["agent"], "prior_read": e.get("prior_read", 0)}
        if e["action"] == "investigated":
            by_cause[cause]["root"] = row
        else:
            by_cause[cause]["dups"].append(row)
    return by_cause


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

    A("<div class=grid>")
    for val, lab in ((c["claimed"], "issues claimed"),
                     (c["investigated"], "causes investigated"),
                     (c["recognised"], "recognised from memory"),
                     (c["duplicated"], "work duplicated")):
        A(f"<div class=kpi><b>{val}</b><span>{esc(lab)}</span></div>")
    A("</div>")

    A("<h2>Verdicts</h2>")
    for cause, grp in sorted(clusters.items(), key=lambda kv: -(1 + len(kv[1]['dups']))):
        root, dups = grp["root"], grp["dups"]
        n = (1 if root else 0) + len(dups)
        A(f"<div class='card cluster'><h3><span class=cause>{esc(cause)}</span>"
          f" &nbsp;<span class=tag>{n} report{'s' if n != 1 else ''}</span></h3>")
        if root:
            A(f"<div class=iss><span class=num>{esc(root['issue'])}</span>"
              f"<span>{esc(titles.get(root['issue'], ''))}</span>"
              f"<span class='tag root'>investigated by {esc(root['agent'])}</span></div>")
        for d in sorted(dups, key=lambda x: x["issue"]):
            A(f"<div class=iss><span class=num>{esc(d['issue'])}</span>"
              f"<span>{esc(titles.get(d['issue'], ''))}</span>"
              f"<span class='tag dup'>recognised by {esc(d['agent'])} after reading "
              f"{d['prior_read']} prior</span></div>")
        A("</div>")

    A("<h2>What the engine concluded by itself</h2>")
    concluded = [e for e in p["timeline"] if e["action"] in ("derived", "explained", "belief changed")]
    if concluded:
        for e in concluded:
            A(f"<div class=card><b>{esc(e['detail'])}</b>")
            for line in (e.get("extra") or {}).get("evidence", []):
                A(f"<div class=ev>{esc(line)}</div>")
            for line in (e.get("extra") or {}).get("replaced", []):
                A(f"<div class=ev>replaced: {esc(line)}</div>")
            A("</div>")
        A("<p class=note>No language model took part in the line above. The engine "
          "counted events that shared a subject and linked the evidence it counted.</p>")
    else:
        A("<div class=card>No subject reached the threshold in this run.</div>")

    A("<h2>Agent timeline</h2><div class='card scroll'><table>")
    A("<tr><th>agent</th><th>issue</th><th>action</th><th>detail</th><th>prior read</th></tr>")
    for e in p["timeline"]:
        A(f"<tr><td class=who>{esc(e['agent'])}</td><td class=num>{esc(e.get('issue') or '')}</td>"
          f"<td class='act {esc(e['action'].replace(' ', '-'))}'>{esc(e['action'])}</td>"
          f"<td>{esc((e.get('detail') or '')[:150])}</td>"
          f"<td class=num>{e.get('prior_read') or ''}</td></tr>")
    A("</table></div>")

    A("<h2>The memory graph this run built</h2><div class=card><pre>")
    A(esc("""(:Session)──HAS_TURN──▶(:Turn)──NEXT──▶(:Turn)
     │
   PRODUCED
     ▼
(:Memory:Event)      ──┐
(:Memory:Fact)       ──┼──ABOUT──▶(:Subject)◀──RELATED_TO──▶(:Subject)
(:Memory:Procedure)  ──┘              ▲
                                  CONCERNS
(:Memory:Fact)──DERIVED_FROM──▶(:Event)   │
(:Memory:Fact)──SUPERSEDES────▶(:Fact)    │
                                          │
(:Agent)──WORKING_ON──▶(:Task)────────────┘   many agents, additive
(:Agent)──OWNS────────▶(:Task)                one owner, moved by handoff
(:Handoff)──FROM/TO──▶(:Agent),  ──OF──▶(:Task)"""))
    A("</pre></div>")

    A("<h2>Measured, from FalkorDB's own instruments</h2><div class=grid>")
    for val, lab in ((p["graph_count"], "tenant graphs (GRAPH.LIST)"),
                     (f"{p['used_memory_mb']} MB", "instance memory (INFO memory)"),
                     (f"{pct.get('p50', '—')} µs", "GRAPH.QUERY p50 (server)"),
                     (f"{pct.get('p99', '—')} µs", "GRAPH.QUERY p99 (server)")):
        A(f"<div class=kpi><b>{esc(str(val))}</b><span>{esc(lab)}</span></div>")
    A("</div>")
    A("<div class=card><b>Ran against</b><pre>"
      + esc("\n".join(f"{k} = {v}" for k, v in p["config"].items())) + "</pre></div>")

    A("</div>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(out))
