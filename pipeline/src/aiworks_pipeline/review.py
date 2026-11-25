"""Review queue, standalone reviewer, and review-action application."""
from __future__ import annotations

import html
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .common import dump_json, load_json, utc_now
from .validation import validate_batch


def build_review_queue(run: dict[str, Any], candidates: list[dict[str, Any]], output_dir: str | Path) -> dict[str, Any]:
    output_dir = Path(output_dir)
    candidate_map = {x["candidate_id"]: x for x in candidates}
    records = []
    for claim in run["accepted"]:
        candidate = candidate_map[claim["candidate_id"]]
        records.append({**deepcopy(claim), "full_content_text": candidate["content_text"]})
    queue = {
        "queue_version": "1.0",
        "generated_at": utc_now(),
        "run": run["run"],
        "summary": {
            "pending_claims": len(records),
            "candidate_outcomes": run["status_counts"],
            "quarantined_candidates": [x for x in run["item_results"] if x["status"] in {"quarantined", "provider_failed", "invalid_batch"}],
        },
        "records": records,
    }
    dump_json(output_dir / "review-queue.json", queue)
    (output_dir / "review.html").write_text(_review_html(queue), encoding="utf-8")
    return queue


def _review_html(queue: dict[str, Any]) -> str:
    data = json.dumps(queue, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>知乎选哪边 · 抽取人工审核</title>
<style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#302820;background:#f5f2eb}*{box-sizing:border-box}body{margin:0}.top{position:sticky;top:0;background:#fffdf8;border-bottom:1px solid #ded7cc;padding:16px 24px;z-index:2;display:flex;gap:12px;align-items:center;flex-wrap:wrap}.top strong{margin-right:auto}button,select{font:inherit;border:1px solid #cfc6b8;background:#fff;border-radius:7px;padding:7px 11px;cursor:pointer}button.primary{background:#2f5d50;color:white;border-color:#2f5d50}main{max-width:1100px;margin:20px auto;padding:0 18px 70px}.card{background:#fffdf8;border:1px solid #ded7cc;border-radius:12px;padding:18px;margin:14px 0}.card{min-width:0}.card h3{overflow-wrap:anywhere;word-break:break-word}.card.done{opacity:.62}.meta{font-size:13px;color:#74685c;margin:5px 0 12px}.quote{border-left:3px solid #2f5d50;padding:8px 12px;background:#f2f5f1;white-space:pre-wrap}.fields{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px;margin:12px 0}.fields label{font-size:12px;color:#74685c}.fields div{min-width:0;overflow-wrap:anywhere;background:#f7f4ee;padding:8px;border-radius:6px}textarea{width:100%;min-height:240px;font:12px/1.55 ui-monospace,Consolas,monospace;border:1px solid #d6cdbf;border-radius:7px;padding:10px;background:#fff}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.error{color:#a33b2b}.hint{font-size:12px;color:#74685c}.empty{padding:40px;text-align:center;color:#74685c}@media(max-width:700px){.fields{grid-template-columns:minmax(0,1fr)}}
</style></head><body>
<div class="top"><strong id="progress">人工审核队列</strong><select id="filter"><option value="pending">只看未审核</option><option value="all">显示全部</option><option value="done">只看已审核</option></select><button id="download" class="primary">下载审核动作 JSON</button><span class="hint">文件只在本地生成，不会上传</span></div>
<main><div id="list"></div></main>
<script id="q" type="application/json">__QUEUE_JSON__</script>
<script>
const queue=JSON.parse(document.getElementById('q').textContent);
const actions=new Map();let filter='pending';
const list=document.getElementById('list'),filterEl=document.getElementById('filter');
function editable(claim){const {source,run,review,evidence_start,evidence_end,candidate_id,scenario_id,claim_id,...fields}=claim;return fields}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function render(){
 const records=queue.records.filter(r=>filter==='all'||(filter==='pending'?!actions.has(r.claim_id):actions.has(r.claim_id)));
 document.getElementById('progress').textContent=`已审核 ${actions.size} / ${queue.records.length} 条`;
 list.innerHTML=records.length?records.map(r=>{
  const a=actions.get(r.claim_id),done=!!a,fields=editable(r);
  return `<article class="card ${done?'done':''}" data-id="${esc(r.claim_id)}"><h3>${esc(r.claim_id)}</h3><div class="meta">${esc(r.source.author||'匿名')} · ${r.source.votes} 赞 · ${esc(r.source.content_type)} · <a href="${esc(r.source.url)}" target="_blank" rel="noreferrer">知乎原链接</a></div><div class="meta">${esc(r.source.title)}</div><div class="quote">${esc(r.evidence_quote)}</div><div class="fields"><div>选项 / 方向<br><b>${esc(r.option)} / ${esc(r.polarity)}</b></div><div>条件<br><b>${esc(JSON.stringify(r.conditions))}</b></div><div>来源类型<br><b>${esc(r.source_type)}</b></div><div>置信度<br><b>${r.confidence}</b></div></div><details><summary>查看完整正文与代价</summary><p>代价：${esc(r.cost?r.cost.text:'无')}</p><div class="quote">${esc(r.full_content_text)}</div></details><label class="hint">修改模式：编辑以下 JSON（保留全部字段）</label><textarea spellcheck="false">${esc(JSON.stringify(fields,null,2))}</textarea><div class="actions"><button data-act="accept">接受</button><button data-act="modify">保存修改</button><button data-act="reject">拒绝</button><button data-act="undo">撤销</button><span class="hint">${done?esc(a.note||'已记录'):'尚未审核'}</span></div><div class="error"></div></article>`
 }).join(''):'<div class="empty">当前筛选下没有记录</div>';
 list.querySelectorAll('.card').forEach(card=>card.querySelectorAll('button[data-act]').forEach(btn=>btn.onclick=()=>{
  const id=card.dataset.id,record=queue.records.find(x=>x.claim_id===id),act=btn.dataset.act,error=card.querySelector('.error');error.textContent='';
  if(act==='undo'){actions.delete(id)}
  else if(act==='reject'){actions.set(id,{claim_id:id,candidate_id:record.candidate_id,decision:'reject',note:''})}
  else if(act==='accept'){actions.set(id,{claim_id:id,candidate_id:record.candidate_id,decision:'accept',note:''})}
  else {try{const claim=JSON.parse(card.querySelector('textarea').value);actions.set(id,{claim_id:id,candidate_id:record.candidate_id,decision:'modify',claim,note:''})}catch(e){error.textContent='JSON 格式错误，未保存';return}}
  render();
 }));
}
filterEl.onchange=()=>{filter=filterEl.value;render()};
document.getElementById('download').onclick=()=>{const payload={reviewer:'',actions:[...actions.values()]};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='review-actions.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
render();
</script></body></html>""".replace("__QUEUE_JSON__", data)


def apply_review_actions(
    run: dict[str, Any],
    candidates: list[dict[str, Any]],
    scenario: dict[str, Any],
    schema: dict[str, Any],
    action_file: str | Path,
    output_dir: str | Path,
    *,
    reviewer: str,
) -> dict[str, Any]:
    if not reviewer.strip():
        raise ValueError("reviewer must not be empty")
    payload = load_json(action_file)
    if not isinstance(payload, dict):
        raise ValueError("review actions file must contain an object")
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise ValueError("review actions must be an array")
    candidate_map = {x["candidate_id"]: x for x in candidates}
    originals = {x["claim_id"]: x for x in run["accepted"]}
    seen: set[str] = set()
    approved: list[dict[str, Any]] = []
    reviewed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("each review action must be an object")
        if not isinstance(action.get("note", ""), str):
            raise ValueError("review note must be a string")
        claim_id = action.get("claim_id")
        if not isinstance(claim_id, str):
            raise ValueError("claim_id must be a string")
        if claim_id in seen or claim_id not in originals:
            raise ValueError(f"duplicate or unknown claim_id: {claim_id}")
        seen.add(claim_id)
        original = originals[claim_id]
        candidate_id = original["candidate_id"]
        if action.get("candidate_id") != candidate_id:
            raise ValueError(f"candidate_id mismatch for {claim_id}")
        decision = action.get("decision")
        if decision == "reject":
            rejected.append({"claim_id": claim_id, "candidate_id": candidate_id, "reviewer": reviewer, "reviewed_at": utc_now(), "note": action.get("note", "")})
            continue
        if decision not in {"accept", "modify"}:
            raise ValueError(f"invalid decision for {claim_id}")
        if decision == "accept":
            record = deepcopy(original)
        else:
            fields = action.get("claim")
            item = {"candidate_id": candidate_id, "status": "extracted", "claims": [fields]}
            batch = {"items": [item]}
            checked = validate_batch(batch, candidate_map, scenario, schema, run_metadata=original["run"])
            if not checked["accepted"]:
                raise ValueError(f"modified claim failed validation for {claim_id}: {checked['item_results'][0]['errors']}")
            record = deepcopy(checked["accepted"][0])
            record["claim_id"] = claim_id
        record["review"] = {"status": "approved", "reviewed": True, "reviewer": reviewer, "reviewed_at": utc_now(), "note": action.get("note", ""), "decision": decision}
        approved.append(record)
        reviewed.append(record)
    output_dir = Path(output_dir)
    result = {
        "reviewer": reviewer,
        "applied_at": utc_now(),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "pending_count": len(originals) - len(seen),
        "approved": approved,
        "rejected": rejected,
    }
    dump_json(output_dir / "approved-extractions.json", {"scenario_id": scenario["id"], "records": approved})
    dump_json(output_dir / "review-result.json", result)
    return result
