"""Blank optional human-review templates for the AI-assisted development set."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .common import dump_json, utc_now


REVIEW_KIND = "independent-human-gold-annotation"
INDEPENDENCE_STATEMENT = "Complete this file without reading the other reviewer's file, any AI annotation, model output, fixture, or existing gold set."


def _blank_claim() -> dict[str, Any]:
    return {
        "claim": "",
        "option": None,
        "polarity": None,
        "evidence_quote": "",
        "conditions": {"freq": None, "clean": None, "play": None},
        "cost": None,
        "source_type": None,
        "confidence": None,
    }


def _template_payload(candidates: list[dict[str, Any]], scenario: dict[str, Any], slot: str) -> dict[str, Any]:
    cases = []
    for candidate in candidates:
        cases.append({
            "candidate_id": candidate["candidate_id"],
            "status": None,
            "claims": [],
            "source": {
                "title": candidate["title"],
                "url": candidate["url"],
                "author": candidate["author"],
                "badge": candidate["badge"],
                "votes": candidate["votes"],
                "content_type": candidate["content_type"],
            },
            "content_text": candidate["content_text"],
        })
    return {
        "template_version": "1.0",
        "generated_at": utc_now(),
        "scenario_id": scenario["id"],
        "reviewer_slot": slot,
        "reviewer": "",
        "review_kind": REVIEW_KIND,
        "human_review": True,
        "independence_statement": INDEPENDENCE_STATEMENT,
        "instructions": {
            "status": "extracted 表示正文有明确决策主张；irrelevant 表示无关；insufficient_evidence 表示相关但证据不足。后两种状态的 claims 必须为空。",
            "claim": "用4-240字复述原文主张，不补充外部知识。option 为 capsule/semi，polarity 为 pro/con。",
            "evidence_quote": "必须是 content_text 中逐字连续子串，4-500字，不得拼接或改写。",
            "conditions": "freq/clean/play 可填 null 或场景枚举；非 null 值必须在主引文或代价引文内出现对应证据词。",
            "cost": "null 或包含 text 与 evidence_quote 的对象；代价引文也必须是原文逐字连续子串。",
            "source_type": "experience/guide/cleaning/other，按整篇正文性质判断。",
            "confidence": "0-1实数。每条候选最多6条不重复主张。",
            "submission": "填满 reviewer 并确保50条案例全部通过校验后，将文件另存为 reviewer-a.json 或 reviewer-b.json。HTML工作台导出的JSON可直接用于校验。",
        },
        "claim_template": _blank_claim(),
        "cases": cases,
    }


def _human_review_html(template: dict[str, Any], scenario: dict[str, Any]) -> str:
    slot = template["reviewer_slot"]
    bundle = {"template": template, "scenario": scenario}
    data = (
        json.dumps(bundle, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>知乎选哪边 · 黄金集真人复核 __SLOT__</title>
<style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color:#302820;background:#f5f2eb;--paper:#fffdf8;--ground:#f5f2eb;--ink:#302820;--muted:#74685c;--line:#ded7cc;--accent:#2f5d50;--accent-soft:#edf3ef;--danger:#a33b2b;--danger-soft:#fbefec;--focus:#1f4f84}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0}button,input,select,textarea{font:inherit;color:inherit}button,select,input[type="text"],input[type="number"]{border:1px solid #cfc6b8;background:#fff;border-radius:7px;padding:8px 10px}button{cursor:pointer}button:hover{background:#f2eee6}button:active{background:#e9e2d7}button:disabled{cursor:not-allowed;opacity:.5}button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}button.primary:hover{background:#254c41}button.danger{color:var(--danger);border-color:#d8aaa0}button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,a:focus-visible,summary:focus-visible{outline:3px solid rgba(31,79,132,.35);outline-offset:2px}a{color:var(--accent);text-underline-offset:3px}::selection{background:#d9e8df;color:var(--ink)}
.top{position:sticky;top:0;z-index:5;background:rgba(255,253,248,.97);border-bottom:1px solid var(--line);padding:14px 22px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}.top h1{font-size:18px;margin:0;white-space:nowrap}.top .spacer{flex:1}.top .hint{font-size:12px;color:var(--muted)}.name-field{display:flex;align-items:center;gap:7px;font-size:13px}.name-field input{width:150px}.file-input{display:none}
.layout{display:grid;grid-template-columns:230px minmax(0,1fr);gap:22px;max-width:1500px;margin:0 auto;padding:22px}.side{position:sticky;top:78px;align-self:start;max-height:calc(100vh - 96px);overflow:auto;padding-right:6px}.side h2{font-size:13px;margin:0 0 10px}.side select{width:100%;margin-bottom:10px}.candidate-nav{display:grid;gap:4px}.candidate-nav button{text-align:left;border:0;background:transparent;padding:7px 8px;border-radius:6px;font-size:12px;line-height:1.4}.candidate-nav button:hover{background:#ece7dd}.candidate-nav button.complete{color:var(--accent)}.candidate-nav button.current{background:var(--accent-soft);font-weight:700}.candidate-nav .nav-title{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.candidate-nav .nav-state{color:var(--muted);font-size:11px}
main{min-width:0}.intro{max-width:78ch;margin:0 0 18px}.intro h2{font-size:24px;line-height:1.25;margin:0 0 8px}.intro p{color:var(--muted);line-height:1.7;margin:6px 0}.global-status{font-size:13px;color:var(--muted);min-height:20px}.global-status.error{color:var(--danger)}
.case{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(360px,.95fr);gap:0;background:var(--paper);border:1px solid var(--line);border-radius:14px;margin:0 0 18px;scroll-margin-top:86px;overflow:hidden}.case.invalid{border-color:#d8aaa0}.case.complete{border-color:#9fb9aa}.source{padding:20px;border-right:1px solid var(--line);min-width:0}.source h3{font-size:18px;line-height:1.45;margin:0 0 8px;overflow-wrap:anywhere}.meta{font-size:12px;color:var(--muted);line-height:1.6;margin:0 0 12px;overflow-wrap:anywhere}.source-text{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.8;max-height:560px;overflow:auto;padding:12px 14px;background:#f8f5ef;border:1px solid #e7e0d5;border-radius:8px}.annotation{padding:20px;min-width:0}.annotation h4{font-size:14px;margin:0 0 12px}.field{display:grid;gap:6px;margin:0 0 12px}.field>label,.field-label{font-size:12px;font-weight:700;color:var(--muted)}.field textarea{width:100%;min-height:76px;resize:vertical;border:1px solid #d6cdbf;border-radius:7px;padding:9px 10px;background:#fff;line-height:1.55}.field textarea.evidence{min-height:104px}.field select,.field input[type="number"]{width:100%}.field-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.conditions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.conditions .field{margin-bottom:12px}.claim-editor{border-top:1px solid var(--line);padding-top:16px;margin-top:16px}.claim-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.claim-head strong{font-size:13px}.claim-actions,.case-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.case-errors{margin:12px 0 0;padding:10px 12px;background:var(--danger-soft);color:var(--danger);border-radius:7px;font-size:12px;line-height:1.6;white-space:pre-wrap}.case-errors:empty{display:none}.case-summary{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}.badge{display:inline-flex;align-items:center;border:1px solid var(--line);border-radius:999px;padding:3px 8px;font-size:11px;color:var(--muted);background:#fff}.badge.ok{color:var(--accent);border-color:#9fb9aa;background:var(--accent-soft)}.badge.pending{color:#8a5a12;border-color:#d8c08e;background:#fbf5e8}details.cost{margin:4px 0 12px}details.cost summary{cursor:pointer;font-size:12px;font-weight:700;color:var(--muted)}details.cost[open] summary{margin-bottom:10px}.empty{padding:36px;text-align:center;color:var(--muted);background:var(--paper);border:1px solid var(--line);border-radius:12px}
@media(max-width:1050px){.layout{grid-template-columns:190px minmax(0,1fr);gap:16px}.case{grid-template-columns:1fr}.source{border-right:0;border-bottom:1px solid var(--line)}.source-text{max-height:420px}}
@media(max-width:760px){.top{padding:11px 14px}.top h1{font-size:16px}.top .hint{display:none}.name-field{order:3;width:100%}.name-field input{flex:1}.layout{display:block;padding:14px}.side{position:static;max-height:none;margin-bottom:16px}.candidate-nav{display:flex;overflow:auto;gap:6px;padding-bottom:4px}.candidate-nav button{min-width:150px}.intro h2{font-size:21px}.annotation,.source{padding:16px}.conditions{grid-template-columns:1fr}.field-row{grid-template-columns:1fr}.case{scroll-margin-top:120px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
</style>
</head>
<body>
<header class="top">
<h1>黄金集真人复核 · __SLOT__</h1>
<label class="name-field">复核人 <input id="reviewer" type="text" autocomplete="name" placeholder="填写真实姓名或代号"></label>
<span id="progress" class="hint">0 / 50</span>
<span class="spacer"></span>
<button id="import" type="button">导入 JSON</button>
<input id="file" class="file-input" type="file" accept="application/json,.json">
<button id="export" class="primary" type="button" disabled>下载标注 JSON</button>
</header>
<div class="layout">
<aside class="side">
<h2>候选导航</h2>
<select id="filter" aria-label="筛选候选">
<option value="unfinished">只看未完成</option>
<option value="all">显示全部</option>
<option value="complete">只看已完成</option>
<option value="invalid">只看有错误</option>
</select>
<nav id="nav" class="candidate-nav" aria-label="候选列表"></nav>
</aside>
<main>
<section class="intro">
<h2>独立阅读原文，再作判断</h2>
<p>本工作台只包含候选原文，不包含 AI 黄金结论。请不要查看另一位复核人的文件、AI 标注、模型运行结果或既有黄金集。</p>
<p>每条候选选择一种状态；只有 extracted 需要填写 1–6 条主张。引文必须是左侧原文中逐字连续的片段。条件与代价也必须由所附引文直接支持。</p>
<p>草稿自动保存在当前浏览器。完成后填写复核人并下载 JSON；导出前会检查全部 50 条案例。</p>
<div id="global-status" class="global-status" aria-live="polite"></div>
</section>
<div id="list"></div>
</main>
</div>
<script id="review-data" type="application/json">__DATA_JSON__</script>
<script>
'use strict';
const bundle=JSON.parse(document.getElementById('review-data').textContent);
const template=bundle.template,scenario=bundle.scenario,candidates=template.cases;
const slot=template.reviewer_slot;
const storageKey=`zhihu-gold-human-review-${slot}-v1`;
const candidateMap=new Map(candidates.map(x=>[x.candidate_id,x]));
const blankClaim=()=>({claim:'',option:null,polarity:null,evidence_quote:'',conditions:{freq:null,clean:null,play:null},cost:null,source_type:null,confidence:null});
const initialState=()=>({reviewer:'',cases:Object.fromEntries(candidates.map(x=>[x.candidate_id,{status:null,claims:[]}]))});
let state=initialState(),filter='unfinished',errors=new Map(),saveTimer=null,storageAvailable=true;
const list=document.getElementById('list'),nav=document.getElementById('nav'),filterEl=document.getElementById('filter');
const reviewerEl=document.getElementById('reviewer'),exportEl=document.getElementById('export'),globalStatus=document.getElementById('global-status');
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clone=x=>JSON.parse(JSON.stringify(x));
const statusLabel=x=>({extracted:'可抽取',insufficient_evidence:'证据不足',irrelevant:'无关'}[x]||'未填写');
function options(values,current,placeholder){return `<option value="">${esc(placeholder)}</option>`+values.map(v=>`<option value="${esc(v)}" ${current===v?'selected':''}>${esc(v)}</option>`).join('')}
function conditionOptions(key,current){const values=Object.keys(scenario.conditions[key].values);return options(values,current,'不指定')}
function setPath(object,path,value){const parts=path.split('.');let target=object;for(const part of parts.slice(0,-1)){if(target[part]==null||typeof target[part]!=='object')target[part]={};target=target[part]}target[parts.at(-1)]=value}
function getPath(object,path){return path.split('.').reduce((value,key)=>value?.[key],object)}
function validateCase(candidate){
 const item=state.cases[candidate.candidate_id],text=candidate.content_text,issues=[];
 if(!['extracted','insufficient_evidence','irrelevant'].includes(item.status)){issues.push('请选择案例状态');return issues}
 if(item.status!=='extracted'){if(item.claims.length)issues.push('非 extracted 状态的 claims 必须为空');return issues}
 if(!item.claims.length)issues.push('extracted 状态至少需要1条主张');
 if(item.claims.length>scenario.limits.max_claims_per_candidate)issues.push(`每条候选最多${scenario.limits.max_claims_per_candidate}条主张`);
 const quotes=new Set(),signatures=new Set();
 item.claims.forEach((claim,index)=>{
  const prefix=`主张${index+1}`;
  if(typeof claim.claim!=='string'||claim.claim.length<4||claim.claim.length>240)issues.push(`${prefix}：claim 需为4-240字`);
  if(!['capsule','semi'].includes(claim.option))issues.push(`${prefix}：请选择 option`);
  if(!['pro','con'].includes(claim.polarity))issues.push(`${prefix}：请选择 polarity`);
  if(typeof claim.evidence_quote!=='string'||claim.evidence_quote.length<4||claim.evidence_quote.length>500)issues.push(`${prefix}：主引文需为4-500字`);
  else if(!text.includes(claim.evidence_quote))issues.push(`${prefix}：主引文不是原文逐字连续子串`);
  if(quotes.has(claim.evidence_quote))issues.push(`${prefix}：主引文重复`);quotes.add(claim.evidence_quote);
  if(!claim.conditions||Object.keys(claim.conditions).sort().join(',')!=='clean,freq,play')issues.push(`${prefix}：conditions 必须包含 freq/clean/play`);
  const evidenceWindow=(claim.evidence_quote||'')+' '+(claim.cost?.evidence_quote||'');
  for(const key of ['freq','clean','play']){
   const value=claim.conditions?.[key];
   if(value!==null&&value!==undefined&&!Object.keys(scenario.conditions[key].values).includes(value))issues.push(`${prefix}：${key} 值不在场景枚举中`);
   if(value!==null&&value!==undefined){const terms=scenario.conditions[key].evidence_terms[value]||[];if(terms.length&&!terms.some(term=>evidenceWindow.toLowerCase().includes(term.toLowerCase())))issues.push(`${prefix}：${key}=${value} 在附加引文中没有词面支持`)}
  }
  if(claim.cost!==null){
   if(!claim.cost||typeof claim.cost!=='object')issues.push(`${prefix}：cost 必须为 null 或对象`);
   else{
    if(typeof claim.cost.text!=='string'||claim.cost.text.length<2||claim.cost.text.length>240)issues.push(`${prefix}：代价描述需为2-240字`);
    if(typeof claim.cost.evidence_quote!=='string'||claim.cost.evidence_quote.length<4||claim.cost.evidence_quote.length>500)issues.push(`${prefix}：代价引文需为4-500字`);
    else if(!text.includes(claim.cost.evidence_quote))issues.push(`${prefix}：代价引文不是原文逐字连续子串`);
   }
  }
  if(!Object.keys(scenario.source_types).includes(claim.source_type))issues.push(`${prefix}：请选择 source_type`);
  if(typeof claim.confidence!=='number'||!Number.isFinite(claim.confidence)||claim.confidence<0||claim.confidence>1)issues.push(`${prefix}：confidence 需为0-1实数`);
  const signature=JSON.stringify([claim.option,claim.polarity,claim.evidence_quote,claim.conditions]);
  if(signatures.has(signature))issues.push(`${prefix}：主张重复`);signatures.add(signature);
 });
 return issues;
}
function claimHtml(claim,index){
 const cost=claim.cost||{text:'',evidence_quote:''};
 return `<section class="claim-editor" data-claim="${index}">
 <div class="claim-head"><strong>主张 ${index+1}</strong><button type="button" class="danger" data-action="remove-claim" data-index="${index}">删除主张</button></div>
 <div class="field"><label for="claim-${index}">主张描述</label><textarea id="claim-${index}" data-field="claim" data-index="${index}" maxlength="240" placeholder="用4-240字复述原文主张">${esc(claim.claim)}</textarea></div>
 <div class="field-row"><div class="field"><label>选项</label><select data-field="option" data-index="${index}">${options(['capsule','semi'],claim.option,'请选择')}</select></div><div class="field"><label>方向</label><select data-field="polarity" data-index="${index}">${options(['pro','con'],claim.polarity,'请选择')}</select></div></div>
 <div class="field"><label for="evidence-${index}">主引文（原文逐字连续片段）</label><textarea id="evidence-${index}" class="evidence" data-field="evidence_quote" data-index="${index}" maxlength="500" placeholder="从左侧原文复制4-500字">${esc(claim.evidence_quote)}</textarea></div>
 <div class="field-label">使用条件（没有明确支持就留空）</div><div class="conditions">${['freq','clean','play'].map(key=>`<div class="field"><label>${esc(scenario.conditions[key].label)} · ${key}</label><select data-field="${key}" data-index="${index}">${conditionOptions(key,claim.conditions[key])}</select></div>`).join('')}</div>
 <details class="cost" ${claim.cost?'open':''}><summary>代价（可选）</summary><div class="field"><label>代价描述</label><textarea data-field="cost.text" data-index="${index}" maxlength="240" placeholder="例如：需要额外购买磨豆机">${esc(cost.text)}</textarea></div><div class="field"><label>代价引文</label><textarea class="evidence" data-field="cost.evidence_quote" data-index="${index}" maxlength="500" placeholder="填写代价描述对应的原文片段">${esc(cost.evidence_quote)}</textarea></div></details>
 <div class="field-row"><div class="field"><label>来源类型</label><select data-field="source_type" data-index="${index}">${options(Object.keys(scenario.source_types),claim.source_type,'请选择')}</select></div><div class="field"><label>置信度（0-1）</label><input type="number" min="0" max="1" step="0.01" data-field="confidence" data-index="${index}" value="${claim.confidence??''}" placeholder="例如 0.9"></div></div>
 <div class="case-actions"><button type="button" data-action="check" data-index="${index}">检查本条主张</button></div>
 </section>`;
}
function caseHtml(candidate,index){
 const item=state.cases[candidate.candidate_id],source=candidate.source,issues=errors.get(candidate.candidate_id)||[];
 return `<article class="case ${issues.length?'invalid':''}" id="case-${esc(candidate.candidate_id)}" data-id="${esc(candidate.candidate_id)}">
 <section class="source"><h3>${esc(source.title)}</h3><p class="meta">${esc(source.author||'匿名')}${source.badge?' · '+esc(source.badge):''} · ${source.votes} 赞 · ${esc(source.content_type)}<br><a href="${esc(source.url)}" target="_blank" rel="noreferrer">打开知乎原链接</a></p><div class="source-text" tabindex="0" aria-label="候选完整正文">${esc(candidate.content_text)}</div></section>
 <section class="annotation"><div class="case-summary"><span class="badge">候选 ${index+1} / ${candidates.length}</span><span class="badge ${issues.length?'pending':'ok'}" data-role="state-badge">${issues.length?'待修正':'已完成'}</span></div>
 <div class="field"><label for="status-${esc(candidate.candidate_id)}">案例状态</label><select id="status-${esc(candidate.candidate_id)}" data-field="status">${options(['extracted','insufficient_evidence','irrelevant'],item.status,'请选择')}</select></div>
 ${item.status==='extracted'?item.claims.map(claimHtml).join('')+`<div class="case-actions"><button type="button" data-action="add-claim" ${item.claims.length>=scenario.limits.max_claims_per_candidate?'disabled':''}>添加主张</button></div>`:'<p class="hint">选择 extracted 后开始填写主张；其他状态不填写 claims。</p>'}
 <div class="case-errors" data-role="errors">${esc(issues.join('\n'))}</div></section></article>`;
}
function visibleCandidates(){return candidates.filter(c=>{const issues=errors.get(c.candidate_id)||[];return filter==='all'||(filter==='unfinished'?issues.length>0:filter==='complete'?issues.length===0:filter==='invalid'?issues.length>0:true)})}
function renderList(){const visible=visibleCandidates();list.innerHTML=visible.length?visible.map(c=>caseHtml(c,candidates.indexOf(c))).join(''):'<div class="empty">当前筛选下没有候选</div>';renderNav();updateSummary()}
function renderNav(){nav.innerHTML=candidates.map((c,index)=>{const issues=errors.get(c.candidate_id)||[];return `<button type="button" data-target="${esc(c.candidate_id)}" class="${issues.length?'':'complete'}"><span class="nav-title">${index+1}. ${esc(c.source.title)}</span><span class="nav-state">${issues.length?'待完成':statusLabel(state.cases[c.candidate_id].status)}</span></button>`}).join('')}
function updateSummary(){let complete=0,invalid=0;for(const c of candidates){const issues=validateCase(c);errors.set(c.candidate_id,issues);if(!issues.length)complete++;else invalid++}document.getElementById('progress').textContent=`${complete} / ${candidates.length} 已完成`;exportEl.disabled=complete!==candidates.length||!state.reviewer.trim();exportEl.title=exportEl.disabled?'请填写复核人并修正全部案例':'下载可直接校验的JSON';globalStatus.classList.toggle('error',invalid>0);globalStatus.textContent=state.reviewer.trim()?(invalid?`还有 ${invalid} 条案例需要修正；错误会显示在对应案例下方。`:'全部案例通过本地校验，可以下载 JSON。'):'请先在顶部填写复核人姓名或代号。';for(const c of candidates){const card=document.getElementById(`case-${c.candidate_id}`);if(!card)continue;const issues=errors.get(c.candidate_id)||[];card.classList.toggle('invalid',issues.length>0);card.classList.toggle('complete',issues.length===0);card.querySelector('[data-role="errors"]').textContent=issues.join('\n');const badge=card.querySelector('[data-role="state-badge"]');badge.textContent=issues.length?'待修正':'已完成';badge.className=`badge ${issues.length?'pending':'ok'}`}renderNav()}
function scheduleSave(){globalStatus.dataset.saving='true';clearTimeout(saveTimer);saveTimer=setTimeout(saveDraft,300)}
function saveDraft(){try{localStorage.setItem(storageKey,JSON.stringify(state));storageAvailable=true;globalStatus.dataset.saving='false'}catch(error){storageAvailable=false;globalStatus.textContent='浏览器禁止本地草稿保存；请及时下载 JSON。'}}
function loadDraft(){try{const raw=localStorage.getItem(storageKey);if(!raw)return;const saved=JSON.parse(raw);if(!saved||!saved.cases)return;const ids=Object.keys(saved.cases);if(ids.length!==candidates.length||!ids.every(id=>candidateMap.has(id)))return;state={reviewer:String(saved.reviewer||''),cases:Object.fromEntries(candidates.map(c=>[c.candidate_id,{status:saved.cases[c.candidate_id]?.status??null,claims:Array.isArray(saved.cases[c.candidate_id]?.claims)?clone(saved.cases[c.candidate_id].claims):[]}]))}}catch(error){storageAvailable=false}}
function exportPayload(){const signedAt=new Date().toISOString();return {reviewer:state.reviewer.trim(),reviewer_slot:slot,review_kind:template.review_kind,human_review:true,independence_statement:template.independence_statement,attestation:{independent_completion:true,source_only:true,signed_at:signedAt},scenario_id:template.scenario_id,exported_at:signedAt,cases:candidates.map(c=>({candidate_id:c.candidate_id,status:state.cases[c.candidate_id].status,claims:clone(state.cases[c.candidate_id].claims)}))}}
list.addEventListener('input',event=>{const el=event.target,field=el.dataset.field;if(!field)return;const card=el.closest('.case');if(!card)return;const item=state.cases[card.dataset.id];let value=el.value;if(field==='confidence')value=value===''?null:Number(value);if(el.dataset.index!==undefined){const claim=item.claims[Number(el.dataset.index)];if(field.startsWith('cost.')){const key=field.slice(5);if(!claim.cost)claim.cost={text:'',evidence_quote:''};claim.cost[key]=value;if(!claim.cost.text&&!claim.cost.evidence_quote)claim.cost=null}else if(['freq','clean','play'].includes(field)){claim.conditions[field]=value||null}else{claim[field]=value}}else{item[field]=field==='status'?(value||null):value}scheduleSave();updateSummary()});
list.addEventListener('change',event=>{const el=event.target;if(el.dataset.field&&el.dataset.field!=='status'){el.dispatchEvent(new Event('input',{bubbles:true}));return}if(el.dataset.field!=='status')return;const card=el.closest('.case'),item=state.cases[card.dataset.id];if(item.status==='extracted'&&!item.claims.length)item.claims=[blankClaim()];if(item.status!=='extracted')item.claims=[];renderList();scheduleSave()});
list.addEventListener('click',event=>{const button=event.target.closest('button[data-action]');if(!button)return;const card=button.closest('.case'),item=state.cases[card.dataset.id],action=button.dataset.action;if(action==='add-claim'&&item.claims.length<scenario.limits.max_claims_per_candidate)item.claims.push(blankClaim());if(action==='remove-claim')item.claims.splice(Number(button.dataset.index),1);if(action==='check'){updateSummary();const target=card.querySelector(`[data-claim="${button.dataset.index}"]`);target?.scrollIntoView({behavior:'smooth',block:'center'});return}renderList();scheduleSave()});
nav.addEventListener('click',event=>{const button=event.target.closest('button[data-target]');if(!button)return;const target=document.getElementById(`case-${button.dataset.target}`);if(target){target.scrollIntoView({behavior:'smooth',block:'start'});nav.querySelectorAll('button').forEach(x=>x.classList.toggle('current',x===button))}});
filterEl.onchange=()=>{filter=filterEl.value;renderList()};
reviewerEl.oninput=()=>{state.reviewer=reviewerEl.value;scheduleSave();updateSummary()};
document.getElementById('import').onclick=()=>document.getElementById('file').click();
document.getElementById('file').onchange=async event=>{const file=event.target.files[0];if(!file)return;try{const payload=JSON.parse(await file.text());if(payload.review_kind!==template.review_kind||payload.reviewer_slot!==slot)throw new Error('文件类型或复核人槽位不匹配');if(!Array.isArray(payload.cases))throw new Error('缺少 cases 数组');const incoming=new Map(payload.cases.map(x=>[x.candidate_id,x]));if(incoming.size!==candidates.length||!candidates.every(c=>incoming.has(c.candidate_id)))throw new Error('候选覆盖必须恰好为50条');state={reviewer:String(payload.reviewer||''),cases:Object.fromEntries(candidates.map(c=>[c.candidate_id,{status:incoming.get(c.candidate_id).status??null,claims:Array.isArray(incoming.get(c.candidate_id).claims)?clone(incoming.get(c.candidate_id).claims):[]}]))};reviewerEl.value=state.reviewer;renderList();saveDraft();globalStatus.textContent='JSON 已导入，请检查本地校验结果。'}catch(error){globalStatus.classList.add('error');globalStatus.textContent=`导入失败：${error.message}`}finally{event.target.value=''}};
exportEl.onclick=()=>{updateSummary();if(exportEl.disabled){globalStatus.classList.add('error');globalStatus.textContent='导出被阻止：请填写复核人并修正全部案例。';return}const blob=new Blob([JSON.stringify(exportPayload(),null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`reviewer-${slot.toLowerCase()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);globalStatus.classList.remove('error');globalStatus.textContent='标注 JSON 已生成；文件只保存在本地。'};
window.addEventListener('beforeunload',saveDraft);
loadDraft();reviewerEl.value=state.reviewer;updateSummary();renderList();
</script>
</body>
</html>'''.replace("__SLOT__", slot).replace("__DATA_JSON__", data)


def build_human_gold_templates(
    candidates: list[dict[str, Any]],
    scenario: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Generate two blank, source-only human annotation workbenches."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    for slot in ("A", "B"):
        template = _template_payload(candidates, scenario, slot)
        slot_output = output / f"reviewer-{slot.lower()}"
        slot_output.mkdir(parents=True, exist_ok=True)
        json_path = slot_output / f"reviewer-{slot.lower()}.template.json"
        html_path = slot_output / f"reviewer-{slot.lower()}.html"
        dump_json(json_path, template)
        html_path.write_text(_human_review_html(deepcopy(template), scenario), encoding="utf-8")
        files.append({"slot": slot, "json": str(json_path), "html": str(html_path)})
    return {
        "generated_at": utc_now(),
        "candidate_count": len(candidates),
        "review_kind": REVIEW_KIND,
        "ai_annotations_included": False,
        "files": files,
    }
