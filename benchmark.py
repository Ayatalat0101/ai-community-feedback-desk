"""
Benchmark: rules + templates vs Gemini, on two sets of messages.

  samples   data/sample_feedback.csv   the 23 messages the rules were written with
  holdout   data/holdout_feedback.csv  14 NEW messages the rules were NOT tuned on

The samples score is flattering for the rules (they were built while looking at
those messages). The holdout score shows how each approach handles wording it
has never seen, which is what real feedback looks like.

Every message goes through the REAL agent (guardrail, lookup tool, policy,
safety check) in a throw-away database, and is compared with the expected
values in data/sample_feedback.csv:

  category        the ticket's category == expected_category
  priority        == expected_priority
  action          refer / ask / draft == expected_action
  distribution    the linked distribution == expected_distribution (drafted rows that have one)
  draft safe      the draft passes check_draft() in strict mode
  LLM draft kept  drafts written by the LLM that passed (not replaced by the template)

Run:  python benchmark.py      (rules only when no key is set)
Writes BENCHMARK.md. Pauses between messages to stay inside free-tier limits.
"""
from __future__ import annotations

import csv
import sys
import tempfile
import time
from pathlib import Path

from feedback import agent
from feedback.config import load_secrets
from feedback.drafter import check_draft
from feedback.llm import build_pipeline
from feedback.models import Submission
from feedback.store import connect, events_for

ROOT = Path(__file__).parent
PAUSE_S = 8          # about 2 LLM calls per message; stays under ~15 requests per minute
ACTION = {"escalate": "refer_confidential"}


SETS = {"samples": "sample_feedback.csv", "holdout": "holdout_feedback.csv"}


def load_rows(name: str = "samples") -> list[dict]:
    rows = csv.DictReader(open(ROOT / "data" / SETS[name], encoding="utf-8"))
    return [r for r in rows if r["expected_action"] != "reject_form"]


def run(name: str, pipe: dict, rows: list[dict], pause: float = 0) -> dict:
    conn = connect(Path(tempfile.mkdtemp()) / "bench.db")
    res = {"name": name, "n": len(rows), "category": 0, "priority": 0, "action": 0, "dist": 0, "dist_n": 0,
           "safe": 0, "drafts": 0, "llm_drafts": 0, "fallbacks": 0, "misses": []}
    for i, r in enumerate(rows):
        if pause and i:
            time.sleep(pause)
        out = agent.submit(conn, Submission(message=r["message"], channel=r["channel"]), **pipe)
        t = out.ticket
        ok = {"category": t["category"] == r["expected_category"], "priority": t["priority"] == r["expected_priority"],
              "action": out.action == ACTION.get(r["expected_action"], r["expected_action"])}
        for k, v in ok.items():
            res[k] += v
        if r["expected_distribution"] and r["expected_action"] == "draft_response":
            res["dist_n"] += 1
            res["dist"] += t["distribution_id"] == r["expected_distribution"]
        if not all(ok.values()):
            res["misses"].append(f"{r['id']}: got {t['category']}/{t['priority']}/{out.action}, expected "
                                 f"{r['expected_category']}/{r['expected_priority']}/{r['expected_action']}")
        res["fallbacks"] += "fallback" in (t["planner"] or "")
        if out.action == "draft_response":
            res["drafts"] += 1
            res["safe"] += not check_draft(t["draft_response"], t["language"], t["distribution_id"])
            author = next(e["detail"] for e in reversed(events_for(conn, t["ref"])) if e["event"] == "draft_response")
            res["llm_drafts"] += "template" not in author
        print(f"  {name:5} {r['id']}  {'✅' if all(ok.values()) else '❌'}  {t['planner']}", flush=True)
    return res


def pct(a, b) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "—"


def table(title: str, results: list[dict], with_llm: bool) -> list[str]:
    cols = [r["name"] for r in results] + ([] if with_llm else ["LLM"])
    by = {r["name"]: r for r in results}
    lines = [f"## {title}", "", "| Metric | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for label, key, denom in [("Category correct", "category", "n"), ("Priority correct", "priority", "n"),
                              ("Action correct (refer / ask / draft)", "action", "n"),
                              ("Distribution linked correctly", "dist", "dist_n"),
                              ("Drafts passing the safety check", "safe", "drafts"),
                              ("Drafts written by the LLM (kept)", "llm_drafts", "drafts"),
                              ("Fell back to rules", "fallbacks", "n")]:
        lines.append(f"| {label} | " + " | ".join(pct(by[c][key], by[c][denom]) if c in by else "—" for c in cols) + " |")
    for r in results:
        lines += ["", f"**Misses ({r['name']}):** " + ("none" if not r["misses"] else ""), *[f"- {m}" for m in r["misses"]]]
    return lines + [""]


def main() -> None:
    llm = build_pipeline(load_secrets())
    if llm:
        print(f"LLM chain: {llm['classifier'].chain.name}. This takes a few minutes (pauses for the free quota).")
    else:
        print("No API key found: rules only. Run  python -m feedback.llm  to see why.", file=sys.stderr)
    lines = ["# Benchmark: rules vs LLM", "",
             "Each message runs through the real agent loop. Sensitive messages never reach the LLM (the guardrail",
             "runs first), the distribution always comes from the lookup tool, and the priority from the written",
             "policy. **samples** are the 23 messages the rules were written with; **holdout** are 14 new messages",
             "the rules were not tuned on.", ""]
    for name in SETS:
        rows = load_rows(name)
        results = [run("rules", {}, rows)]
        if llm:
            results.append(run("LLM", llm, rows, pause=PAUSE_S))
        lines += table(f"{name} ({len(rows)} messages)", results, bool(llm))
    if llm:
        lines += [f"LLM chain: `{llm['classifier'].chain.name}`, run on {time.strftime('%Y-%m-%d')}."]
    (ROOT / "BENCHMARK.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
