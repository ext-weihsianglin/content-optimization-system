"""Plain-language review of frozen teacher results; no model calls or label edits."""

import argparse
from html import escape
import json
import os
from pathlib import Path

from encoder_scorer.curate import sha256


BRIEFS = {
    "e3c9f84f220d": "A router manual mentions firewalls, but it does not answer the question about Cox.",
    "daa66b7ee3dd": "The page sells washer fluid. It asks you to pick a store, but does not show Montreal shops or their stock.",
    "44d0bfe1983c": "GPT-5 gave a quote the wrong block ID, even after a retry. We discarded its body scores.",
    "e71ac87f0ed1": "The page names relevant autoscaling tools and shows how spot capacity fits their configuration.",
    "f005f9482345": "The checklist wrongly asked a static article to invite a conversation. The body judgment also claimed missing answers despite unseen content.",
    "7b6268a11499": "The page gives useful KPI presentation advice, but only some of it is tailored to executives.",
    "3dbad81cd10c": "The page explains AI dance videos. The swapping part of the question gets little attention.",
    "b329f018a814": "The quoted evidence was not an exact passage in its assigned block, even after a retry. We discarded its body scores.",
    "baf47bd9ff2d": "The page offers interview advice, but not the concrete example answers the checklist expected.",
    "5610d6f67164": "A single vendor's marketing page does not help compare options or choose the best tool for this team.",
    "21e9c4b6310f": "The page describes bot protection, but does not compare CDNs. Some background is useful.",
    "56fd0eae0893": "The saved page is a loading screen. It has no payment-tool advice, even though its title matches the screen.",
}
COMPONENTS = [("body", "intent_fulfillment", "Does it answer the question?"),
              ("body", "section_usefulness", "Are the sections useful?"),
              ("title", "title_body_consistency", "Does the title match the page?")]
WORDS = {0: "No useful answer", 1: "Related, with big gaps", 2: "Answers the main task", 3: "Strong match"}


def build(report_path, packets_dir, run_dir, output):
    if output.exists():
        raise FileExistsError("Use a fresh report path")
    report = json.loads(report_path.read_text())
    packets = {x["record_id"]: x for x in map(json.loads, (packets_dir / "packets.jsonl").open())}
    labels = report["teacher_annotations"]
    if len({x["record_id"] for x in labels}) != len(labels):
        raise ValueError("This view supports a single teacher per case")
    summary = report["summary"]
    selection_contract = report.get("config", {}).get("provider_contract") == "teacher-selection-v1"
    valid = sum(x["stages"].get("body") is not None for x in labels)
    traces = [(p, json.loads(p.read_text())) for p in sorted((run_dir / "traces").glob("*.json"))]

    def link(path, title):
        return f'<a href="{escape(os.path.relpath(path, output.parent), quote=True)}">{escape(title)}</a>'

    def display(value):
        if value is None:
            return "Failed check"
        if value["score"] is not None:
            return f"{value['score']}/3"
        return "No title metadata" if value["applicability"] == "not_applicable" else "Cannot judge"

    rows, cards = [], []
    for index, label in enumerate(labels, 1):
        rid = label["record_id"]
        packet = packets[rid]
        query = packet["packet"]["query"].strip()
        failed = label["stages"].get("body") is None
        coverage = label["coverage"]
        partial = bool(coverage["omitted_block_ids"])
        status = "failed" if failed else "accepted"
        source = {b["block_id"]: b["text"] for b in packet["packet"]["blocks"]}
        cells, ratings, evidence = [], [], []
        for stage, name, title in COMPONENTS:
            result = label["stages"].get(stage)
            value = result["components"][name] if result else None
            shown = display(value)
            cells.append(f"<td>{escape(shown)}</td>")
            word = WORDS[value["score"]] if value and value["score"] is not None else shown
            ratings.append(f"<div class='rating'><span>{escape(title)}</span><b>{escape(shown)}</b><small>{escape(word)}</small></div>")
            if value:
                quotes = []
                for e in value["evidence"]:
                    quotes.append(f"<blockquote><small>Block {escape(e['block_id'])}</small><pre>{escape(e['quote'])}</pre>"
                                  f"<details><summary>See the full source block</summary><pre>{escape(source[e['block_id']])}</pre></details></blockquote>")
                evidence.append(f"<h4>{escape(title)}</h4><p>{escape(value['reason'])}</p>" + "".join(quotes))
        rows.append(f"<tr data-status='{status}'><td><a href='#case-{index}'>{escape(query)}</a></td>" + "".join(cells) + "</tr>")
        requirements = label["stages"].get("requirements")
        checklist = "<ol>" + "".join(f"<li>{escape(r['text'])} <small>({escape(r['importance'])}; "
                    + ("stated in the query" if r["origin"] == "explicit" else "added by GPT-5") + ")</small></li>" for r in requirements["requirements"]) + "</ol>" if requirements else "<p>No accepted checklist.</p>"
        case_traces = [(p, t) for p, t in traces if t["record_id"] == rid]
        links = "<ul>" + "".join("<li>" + link(p, f"{t['stage']} · attempt {t['attempt']} · {t['validation_status']}") + "</li>" for p, t in case_traces) + "</ul>"
        errors = "".join(f"<p><strong>{escape(t['stage'])}, attempt {t['attempt']}:</strong> {escape(t.get('validation_error', t.get('transport_error', '')))}</p>"
                         for _, t in case_traces if t["validation_status"] != "valid")
        view = "Some page content was left out" if partial else "All retained page blocks were included"
        note = "These accepted outputs passed format and quote checks. A person still needs to judge whether the ratings are fair." if not failed else "No body grade is accepted. This is a grading failure, not proof that the page is bad. The title check is separate."
        brief = BRIEFS.get(rid[:12], "Review the teacher explanation below.")
        if selection_contract:
            body = label["stages"].get("body")
            brief = (body["components"]["intent_fulfillment"]["reason"] if body
                     else "No body judgment was accepted. Inspect the validation details below.")
            note = ("The selected source IDs passed validation, and our code copied their exact full text. "
                    "A person still needs to judge whether those passages support the scores.") if not failed else note
        cards.append(f"<article id='case-{index}' data-status='{status}'><div class='case-top'><span>CASE {index:02}</span>"
                     f"<span class='badge {status}'>{'Body judgment rejected' if failed else 'Body judgment accepted'}</span></div>"
                     f"<h3>{escape(query)}</h3><p class='brief'>{escape(brief)}</p>"
                     f"<p class='meta'>{escape(view)} · {len(coverage['included_block_ids'])}/{coverage['original_block_count']} blocks</p>"
                     f"<div class='ratings'>{''.join(ratings)}</div><p class='note'>{escape(note)}</p>"
                     f"<details><summary>What did GPT-5 expect this page to answer?</summary>{checklist}</details>"
                     f"<details><summary>Read GPT-5’s explanation and exact quotes</summary>{''.join(evidence) or '<p>No valid body explanation was accepted.</p>'}"
                     "<p class='note'>Formatting marks in quotes are part of the exact input. Matching a quote does not prove a fact is true.</p></details>"
                     f"<details><summary>Inspect retries, errors, and original files</summary>{errors}{links}"
                     f"<pre>{escape(json.dumps(label, ensure_ascii=False, indent=2))}</pre></details></article>")
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>GPT-5 page check · explained simply</title><style>
:root{color-scheme:light;--ink:#172f38;--muted:#576d76;--line:#d7e3e5;--green:#08645a;--amber:#92530b}*{box-sizing:border-box}
body{margin:0;background:#f4f7f5;color:var(--ink);font:16px/1.6 system-ui,-apple-system,sans-serif}main{max-width:1140px;margin:auto;padding:48px 24px 70px}
.eyebrow{font-size:12px;font-weight:750;letter-spacing:.13em;color:var(--green)}h1{font-size:clamp(32px,5vw,54px);line-height:1.12;letter-spacing:-.035em;margin:14px 0}h2{font-size:28px;line-height:1.2;margin:38px 0 16px}h3{font-size:22px;line-height:1.3;margin:14px 0}h4{margin:22px 0 8px}.lede{font-size:20px;max-width:780px;color:var(--muted)}
.box,article,.stat{background:white;border:1px solid var(--line);border-radius:16px;padding:24px}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:26px 0}.stat b{font-size:32px;display:block}.stat span{color:var(--muted);font-size:14px}.decision{background:#fff3dc;border-color:#ead4a8}.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.steps strong{display:block;margin-bottom:6px}.steps p{margin:0;color:var(--muted)}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:14px;margin:14px 0}.legend span{padding:7px 12px;background:#eaf0ed;border-radius:8px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:white}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:14px;text-align:left;border-bottom:1px solid var(--line)}th{background:#e9f0ed;white-space:nowrap}td:first-child{min-width:290px}td:not(:first-child){white-space:nowrap}a{color:#08645a;text-underline-offset:3px}article{margin:20px 0;scroll-margin-top:20px}.case-top{display:flex;gap:12px;justify-content:space-between;align-items:center;font-size:12px;font-weight:700;color:var(--muted)}.badge{border-radius:30px;padding:6px 11px}.accepted{color:var(--green);background:#e6f4ed}.failed{color:var(--amber);background:#fff0d6}.brief{font-size:18px;margin:12px 0}.meta,small{color:var(--muted);font-size:13px}.ratings{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:20px 0}.rating{background:#f1f5f3;border-radius:12px;padding:14px}.rating span,.rating b,.rating small{display:block}.rating span{font-size:13px}.rating b{font-size:24px;margin:5px 0}.note{font-size:14px;color:var(--muted)}details{border-top:1px solid var(--line);padding-top:13px;margin-top:13px}summary{cursor:pointer;font-weight:650}blockquote{margin:12px 0;padding:14px;background:#f1f5f3;border-left:3px solid #61968a}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace;color:var(--ink);max-height:500px;overflow:auto}li{margin:7px 0}button{font:inherit;border:1px solid #9ab5ad;padding:9px 16px;border-radius:30px;background:white;color:var(--green);cursor:pointer}button[aria-pressed=true]{background:var(--green);color:white}.filters{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}[hidden]{display:none!important}footer{border-top:1px solid var(--line);margin-top:34px;padding-top:20px;font-size:14px;color:var(--muted)}
@media(max-width:650px){main{padding:28px 16px}.stats{grid-template-columns:repeat(2,1fr)}.steps,.ratings{grid-template-columns:1fr}.box,article{padding:18px}.case-top{align-items:flex-start}h3{font-size:20px}}@media print{details{display:block}.filters{display:none}article{break-inside:avoid}}
</style></head><body><main><div class="eyebrow">P1 SCORING · SMALL TEST · GPT-5</div>
<h1>Can GPT-5 grade these pages?</h1><p class="lede">We gave GPT-5 a question and a saved page. We asked whether the page answers the question, whether its sections help, and whether its title is honest about the content.</p>
<div class="box decision"><strong>The next step: fix the grading instructions before testing all pages.</strong><p>Some ratings look useful. But GPT-5 still mixes up quotes and asks static articles to act like chatbots. We keep those failed judgments out of the labels.</p></div>
'''
    html += f"<div class='stats'><div class='stat'><b>{len(labels)}</b><span>pages tried</span></div><div class='stat'><b>{valid}</b><span>body judgments accepted</span></div><div class='stat'><b>{len(labels)-valid}</b><span>body judgments rejected</span></div><div class='stat'><b>${summary['estimated_cost_usd']:.2f}</b><span>estimated API cost</span></div></div>"
    html += '''<p class="note">“Accepted” means the output passed our format and exact-quote checks. It does not mean a human has confirmed the grade. Nobody has reviewed these as gold labels yet.</p>
<h2>Three different questions</h2><div class="box steps"><div><strong>1. Does it answer the question?</strong><p>A product page can mention washer fluid without telling you which Montreal shops have it in stock.</p></div><div><strong>2. Are the sections useful?</strong><p>Headings and lists help only when they make useful information easier to find.</p></div><div><strong>3. Does the title match the page?</strong><p>A loading screen can match “Just a moment…” perfectly and still give you no useful answer.</p></div></div>
<h2>How to read the grades</h2><div class="legend"><span><b>0</b> — no useful answer</span><span><b>1</b> — related, with big gaps</span><span><b>2</b> — answers the main task</span><span><b>3</b> — strong match</span></div><p class="note">These are GPT-5’s judgments, not citation probabilities. For the title check, the number measures how well the title matches the body. <b>Failed check ≠ 0.</b> A failed output gets no body grade. <b>No title metadata</b> means no separate title was available for this check. The document may still have a title in its body.</p>
<h2>All 12 results</h2><p>Click a question to inspect its explanation. Use the filters to focus on failed body judgments.</p><div class="filters" aria-label="Filter cases"><button data-filter="all" aria-pressed="true">All 12</button><button data-filter="failed" aria-pressed="false">Rejected body judgments</button><button data-filter="accepted" aria-pressed="false">Accepted body judgments</button></div>
<div class="table-wrap"><table><thead><tr><th>Question</th><th>Answers it?</th><th>Useful sections?</th><th>Title matches?</th></tr></thead><tbody>'''
    html += "".join(rows) + "</tbody></table></div>" + "".join(cards)
    html += '''<h2>What this test still cannot tell us</h2><div class="box"><ul><li><b>Are the facts true?</b> We supplied no separate evidence pack, so the factual-support check was not run by GPT-5. Its “cannot judge” result was filled by our code.</li><li><b>What was in the whole page?</b> Six inputs left out some saved blocks to fit the size limit. A missing answer might be in that unseen content.</li><li><b>Will edits get more citations?</b> This test does not measure that. These are proposed content-quality signals.</li></ul><p>We used saved markdownify documents. We did not fetch live pages. The previous smoke used older inputs; its labels were not reused.</p></div>
<h2>What we should fix next</h2><div class="box"><ol><li>Ask for information a static page should contain, rather than instructions to start a conversation.</li><li>When a quote fails, tell GPT-5 which quote and block failed. Keep exact checks instead of accepting guessed evidence.</li><li>Have a person review the grades, then test good and misleading edits before expanding annotation.</li></ol></div>'''
    html += f"<footer>GPT-5, medium reasoning · {summary['generation_calls']} attempts · {summary['valid_calls']} valid / {summary['invalid_calls']} rejected attempts · no human review or student training.<p>"
    html += link(report_path.with_suffix('.html'), 'Original detailed report') + " · " + link(report_path, 'Complete results JSON') + "</p><p>Cost is an estimate, not an invoice. Source-bearing trace links work on this computer.</p>"
    html += f"<small>Results checksum: {sha256(report_path.read_bytes())}</small></footer></main>"
    html += '''<script>document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{const filter=button.dataset.filter;document.querySelectorAll('[data-status]').forEach(row=>row.hidden=filter!=='all'&&row.dataset.status!==filter);document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));}));</script></body></html>'''
    if selection_contract:
        html = html.replace(
            '<div class="box decision"><strong>The next step: fix the grading instructions before testing all pages.</strong><p>Some ratings look useful. But GPT-5 still mixes up quotes and asks static articles to act like chatbots. We keep those failed judgments out of the labels.</p></div>',
            '<div class="box decision"><strong>Review the new grading harness.</strong>'
            f'<p>{valid}/{len(labels)} pages have accepted body judgments. GPT-5 chooses source blocks; '
            'our code copies their exact text. It also fills fixed requirement slots. '
            'The next step is human review of whether the chosen evidence and grades make sense.</p>'
            '<p>Original run: 9/12 accepted body judgments, 48 calls, about $2.46. '
            f'New run: {valid}/{len(labels)}, {summary["generation_calls"]} calls, about ${summary["estimated_cost_usd"]:.2f}. '
            'Instructions and evidence granularity changed; '
            'this comparison does not prove better grading accuracy.</p></div>')
        html = html.replace(
            '“Accepted” means the output passed our format and exact-quote checks.',
            '“Accepted” means the selected IDs and assembled labels passed validation. '
            'Our code copied exact whole source blocks; GPT-5 did not transcribe quotes.')
        html = html.replace(
            'Formatting marks in quotes are part of the exact input. Matching a quote does not prove a fact is true.',
            'These are complete source blocks copied by our code. GPT-5 selected their IDs. '
            'A valid source passage does not prove that it supports the judgment or that its facts are true.')
        html = html.replace(
            '<li>Ask for information a static page should contain, rather than instructions to start a conversation.</li><li>When a quote fails, tell GPT-5 which quote and block failed. Keep exact checks instead of accepting guessed evidence.</li>',
            '<li>Review whether the selected blocks actually support each judgment. Mechanical checks cannot decide this.</li>'
            '<li>Check partial-page abstentions and whether the query-only checklist is appropriate. '
            'Static-page framing and coverage constraints were tightened, but still need review.</li>')
        html = html.replace('Original detailed report', 'Detailed report for this rerun')
        html = html.replace('What we should fix next', 'What we should review next')
        html = html.replace(
            'The previous smoke used older inputs; its labels were not reused.',
            'This rerun uses the same 12 Markdownify packets as the original run. '
            'No old labels were reused; the historical LR v2-source run remains separate.')
        html = html.replace('P1 SCORING · SMALL TEST · GPT-5', 'P1 SCORING · NEW HARNESS RERUN · GPT-5')
    output.write_text(html + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('report', 'packets', 'run', 'output'):
        parser.add_argument('--' + arg, type=Path, required=True)
    args = parser.parse_args()
    build(args.report, args.packets, args.run, args.output)


if __name__ == '__main__':
    main()
