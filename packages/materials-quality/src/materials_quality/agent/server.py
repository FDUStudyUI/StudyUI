"""StudyUI's local research-agent application and embedded Langflow workspace."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .file_workflow_client import FileWorkflowClient
from .harness import StudyUIAgent

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyUI</title><style>
:root{font-family:Inter,"Microsoft YaHei",system-ui,sans-serif;color:#252a31;background:#f6f3eb;--paper:#f6f3eb;--surface:#fffefa;--line:#e8e2d7;--ink:#252a31;--muted:#777b82;--blue:#29476f;--blue-dark:#203958;--blue-soft:#e9eef5;--nav-muted:#747b85}*{box-sizing:border-box}
body{margin:0;height:100vh;overflow:hidden;background:var(--paper)}button,textarea,input{font:inherit}.layout{height:100vh;display:grid;grid-template-columns:286px minmax(0,1fr)}
.side{background:#f1eee6;border-right:1px solid var(--line);padding:17px 13px 12px;display:flex;flex-direction:column;gap:15px;min-height:0}.brand-row{height:39px;display:flex;align-items:center;gap:10px;padding:0 9px}.brand-mark{width:27px;height:27px;border-radius:9px;background:var(--blue);color:#fff;display:grid;place-items:center;font:700 14px Georgia,serif}.brand{font:650 19px Georgia,"Microsoft YaHei",serif;letter-spacing:.15px;color:#242a32}.brand-note{margin-left:auto;color:#98958e;font-size:10px;letter-spacing:.5px}.nav{display:grid;gap:3px}.nav button,.new{border:0;color:#454b55;background:transparent;border-radius:9px;padding:10px 11px;cursor:pointer;text-align:left;display:flex;align-items:center;gap:10px;font-size:13px}.nav button:hover,.nav button.active{background:#e7e3da;color:var(--blue-dark)}.nav .ico{width:18px;text-align:center;font-size:15px;color:var(--nav-muted)}.new{border:1px solid #d9d4c9;background:#fffdf8;color:var(--blue);font-weight:600;justify-content:center;margin:1px 1px 0;padding:10px}.new:hover{background:#fff;color:var(--blue-dark);border-color:#b8c4d4}
.side-scroll{overflow:auto;min-height:0;display:flex;flex-direction:column;gap:15px}.section-head{display:flex;align-items:center;justify-content:space-between;padding:0 8px 5px;color:#777971;font-size:11px;font-weight:650;letter-spacing:.5px;text-transform:uppercase}.icon-btn{width:25px;height:25px;border:0;border-radius:7px;background:transparent;color:#69717c;cursor:pointer;font-size:17px;line-height:1}.icon-btn:hover{background:#e5e1d8;color:var(--blue)}.project-list,#sessions{display:flex;flex-direction:column;gap:2px}.group-label{width:100%;border:0;background:transparent;border-radius:8px;padding:8px 9px;color:#535a64;text-align:left;display:flex;align-items:center;gap:9px;cursor:pointer;font-size:12.5px}.group-label:hover,.group-label.active{background:#e5e2d9;color:var(--blue-dark)}.group-label .project-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.count{font-size:10px;color:#96938b;min-width:14px;text-align:right}.project-action{opacity:0;width:23px;height:23px;border:0;border-radius:6px;background:transparent;color:#747b84;cursor:pointer}.project-row:hover .project-action,.project-row:focus-within .project-action{opacity:1}.project-action:hover{background:#d9d7d0;color:var(--blue)}.project-row{display:flex;align-items:center;position:relative}.project-row .group-label{flex:1;min-width:0}.session-section{display:flex;flex-direction:column;min-height:0}.session{width:100%;border:0;background:transparent;color:#555c65;text-align:left;border-radius:8px;padding:8px 9px;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.session.active,.session:hover{background:#e5e2d9;color:var(--blue-dark)}.session-wrap{display:flex;align-items:center;gap:2px}.session-wrap .session{flex:1;min-width:0}.session-wrap .session-action{opacity:0;width:24px;height:24px;border:0;border-radius:6px;background:transparent;color:#777;cursor:pointer}.session-wrap:hover .session-action,.session-wrap:focus-within .session-action{opacity:1}.session-action:hover{background:#d9d7d0}.empty-side{padding:6px 10px;color:#9b9992;font-size:11px;line-height:1.6}.side-foot{margin-top:auto;border-top:1px solid #ded9ce;padding:12px 8px 0;color:#89877f;font-size:10px;line-height:1.55}
main{min-width:0;min-height:0;height:100vh;background:var(--paper)}.view{height:100%;min-height:0;display:flex;flex-direction:column}.view[hidden]{display:none}.top{min-height:71px;padding:13px 28px;border-bottom:1px solid var(--line);background:rgba(255,254,250,.82);display:flex;align-items:center;justify-content:space-between;gap:16px}.top h1{font-size:16px;font-weight:650;margin:0 0 4px;color:#282d34}.top p{margin:0;color:var(--muted);font-size:12px}.top-actions{display:flex;align-items:center;gap:11px}.model-status{border:1px solid #e2ddd3;border-radius:999px;padding:6px 10px;color:#737780;font-size:10px;background:#fffdf9}.model-status::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:#c49a56;margin-right:7px;vertical-align:1px}.external{color:var(--blue);text-decoration:none;font-size:12px;white-space:nowrap}.external:hover{text-decoration:underline}
#feed{flex:1;min-height:0;overflow:auto;padding:28px max(24px,calc((100% - 820px)/2));display:flex;flex-direction:column;gap:14px}.msg{max-width:820px;padding:13px 16px;border-radius:14px;white-space:pre-wrap;line-height:1.65;overflow-wrap:anywhere;font-size:13px}.user{align-self:flex-end;background:#e5ebf3;color:#29374a;border:1px solid #dce3ed}.assistant{align-self:flex-start;background:var(--surface);border:1px solid var(--line);color:#343941}.artifact-card{align-self:flex-start;width:min(820px,100%);background:#fffefa;border:1px solid #ded8cc;border-radius:12px;padding:13px 15px}.artifact-card h3{margin:0 0 9px;font-size:12px;color:#4d5662}.artifact-row{padding:8px 0;border-top:1px solid #eee9e0;font-size:11px;overflow-wrap:anywhere}.artifact-row a{color:var(--blue);font-weight:650;text-decoration:none}.artifact-row a:hover{text-decoration:underline}.artifact-hash{display:block;margin-top:4px;color:#85878b;font:10px ui-monospace,monospace}.proposal{max-width:820px;background:#fffdf7;border:1px solid #d9d0bd;border-radius:12px;padding:15px}.proposal h3{margin:0 0 8px;font-size:14px}.proposal ul{margin:8px 0;padding-left:20px}.proposal p{margin:6px 0;color:#62646a;font-size:12px}.actions{display:flex;gap:8px;margin-top:12px}.actions button{border:0;border-radius:7px;padding:9px 13px;cursor:pointer;font-size:12px}.approve{background:var(--blue);color:white}.reject{background:#ece9e1;color:#333b46}
.welcome{margin:auto;max-width:590px;text-align:center;padding:36px 20px 48px}.welcome-mark{width:43px;height:43px;margin:0 auto 17px;border-radius:14px;background:var(--blue);color:white;display:grid;place-items:center;font:700 23px Georgia,serif;box-shadow:0 6px 20px #29476f26}.welcome h2{font:500 25px Georgia,"Microsoft YaHei",serif;color:#283342;margin:0 0 10px}.welcome p{font-size:13px;line-height:1.75;color:#777a80;margin:0 auto 23px;max-width:500px}.prompts{display:flex;flex-wrap:wrap;justify-content:center;gap:8px}.prompt-chip{border:1px solid #e0dbd0;background:#fffdf8;border-radius:999px;padding:8px 12px;color:#4c5868;font-size:11px;cursor:pointer}.prompt-chip:hover{border-color:#b9c5d3;color:var(--blue);background:#fff}
.composer{padding:13px 22px 15px;background:rgba(255,254,250,.84);border-top:1px solid var(--line)}.compose-inner{max-width:820px;margin:auto;display:flex;gap:9px;align-items:end;background:var(--surface);border:1px solid #dcd6ca;border-radius:14px;padding:7px;box-shadow:0 2px 10px #37311a0b}.compose-inner:focus-within{border-color:#a8b7ca;box-shadow:0 0 0 3px #29476f12}textarea{resize:vertical;min-height:45px;max-height:180px;flex:1;border:0;outline:0;background:transparent;border-radius:9px;padding:10px;font:inherit;font-size:13px;color:var(--ink)}textarea::placeholder{color:#9b9b9a}#send{height:39px;padding:0 17px;border:0;border-radius:9px;background:var(--blue);color:#fff;font-weight:600;font-size:12px;cursor:pointer}#send:hover{background:var(--blue-dark)}#send:disabled{opacity:.5;cursor:wait}.hint{max-width:820px;margin:7px auto 0;color:#8a8984;font-size:10px}.flow-top{min-height:71px}#flow-frame{flex:1;width:100%;min-height:0;border:0;background:#fff}
dialog{border:1px solid var(--line);border-radius:16px;background:var(--surface);color:var(--ink);padding:22px;width:min(420px,calc(100vw - 32px));box-shadow:0 18px 70px #22251f30}dialog::backdrop{background:#24283155;backdrop-filter:blur(2px)}dialog h2{font-size:17px;margin:0 0 7px}dialog p{font-size:12px;color:var(--muted);margin:0 0 17px}dialog label{display:block;font-size:12px;color:#656a72;margin-bottom:7px}dialog input{width:100%;border:1px solid #d9d5cc;border-radius:9px;padding:11px 12px;outline:0;background:#fffefa;color:var(--ink)}dialog input:focus{border-color:#94a7bf;box-shadow:0 0 0 3px #29476f12}.dialog-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.dialog-actions button{border:0;border-radius:8px;padding:9px 14px;cursor:pointer;font-size:12px}.cancel{background:#eeece6;color:#555a61}.primary{background:var(--blue);color:#fff}.toast{position:fixed;bottom:25px;left:50%;transform:translateX(-50%);background:#293d5b;color:#fff;border-radius:9px;padding:10px 15px;font-size:12px;box-shadow:0 6px 24px #1c2d4933;z-index:10}
@media(max-width:760px){.layout{grid-template-columns:230px minmax(0,1fr)}.side{padding:13px 9px}.top{padding:12px 16px}.model-status{display:none}#feed{padding:18px 14px}.composer{padding:10px}.brand-note{display:none}}
@media(max-width:560px){.layout{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr)}.side{height:auto;max-height:45vh;padding:8px 10px;gap:6px;border-right:0;border-bottom:1px solid var(--line)}.brand-row{height:30px}.brand{font-size:16px}.brand-mark{width:23px;height:23px}.nav{display:flex}.nav button{padding:7px 9px}.new{position:absolute;right:10px;top:8px;width:38px;height:34px;font-size:0}.new::after{content:"＋";font-size:18px}.side-scroll,.side-foot{display:none}.top{min-height:58px;padding:10px 13px}.top p{display:none}.external{font-size:10px}#feed{padding:14px}.msg{font-size:12px}.hint{line-height:1.5}}
</style></head><body>
<div class="layout">
<aside class="side">
  <div class="brand-row"><div class="brand-mark">S</div><div class="brand">StudyUI</div><span class="brand-note">RESEARCH</span></div>
  <nav class="nav"><button id="nav-chat" class="active"><span class="ico">◌</span>研究对话</button><button id="nav-flow"><span class="ico">▦</span>工作流画布</button></nav>
  <button class="new" id="new">＋　新建研究会话</button>
  <div class="side-scroll">
    <section><div class="section-head"><span>项目与工作区</span><button class="icon-btn" id="add-project" title="新建项目" aria-label="新建项目">＋</button></div><div id="projects" class="project-list"></div></section>
    <section class="session-section"><div class="section-head"><span id="session-heading">最近会话</span></div><div id="sessions"></div></section>
  </div>
  <div class="side-foot">工作区与会话保存在本机。删除项目时，研究会话保留在「未归类」，工作流移入恢复目录。</div>
</aside>
<main>
  <section id="chat-view" class="view">
    <header class="top"><div><h1 id="view-title">研究对话</h1><p id="view-subtitle">围绕当前研究项目讨论目标、证据、数据与工作流。</p></div><div class="top-actions"><span id="model-status" class="model-status">AI 模型未配置</span><button id="settings-open" class="prompt-chip">设置</button></div></header>
    <section id="feed"></section>
    <footer class="composer"><div class="compose-inner"><textarea id="input" placeholder="描述研究目标，或告诉 StudyUI 你希望检查、搭建或运行什么……"></textarea><button id="send">发送</button></div><div class="hint">文献检索当前返回 Crossref 元数据，不代表已获取论文全文。请勿粘贴密钥或未授权的敏感数据。</div></footer>
  </section>
  <section id="flow-view" class="view" hidden>
    <header class="top flow-top"><div><h1>工作流画布</h1><p>在 StudyUI 工作区中查看、编辑和运行材料科学流程。</p></div><a id="open-langflow" href="__LANGFLOW_BASE_URL__" class="external" target="_blank" rel="noopener">单独打开画布 ↗</a></header>
    <iframe id="flow-frame" data-src="__LANGFLOW_BASE_URL__/" title="Langflow 工作流画布" loading="lazy" referrerpolicy="no-referrer"></iframe>
  </section>
</main>
</div>
<dialog id="project-dialog"><form id="project-form"><h2>新建研究项目</h2><p>按课题整理研究会话，后续新建的会话会归入当前项目。</p><label for="project-title">项目名称</label><input id="project-title" name="title" maxlength="120" placeholder="例如：DNA Origami 纳米间隙单染料" required><div class="dialog-actions"><button type="button" class="cancel" id="cancel-project">取消</button><button class="primary" type="submit">创建项目</button></div></form></dialog>
<style>#settings-dialog{width:min(700px,calc(100vw - 32px));max-height:88vh;overflow:auto}#settings-dialog input,#settings-dialog select{margin-bottom:12px}#settings-dialog .skill-row{padding:12px;border:1px solid var(--line);border-radius:10px;margin:8px 0;background:#fffdf8}#settings-dialog .skill-row p{margin:5px 0 8px;line-height:1.5}#settings-dialog .skill-actions{display:flex;gap:7px;flex-wrap:wrap}#settings-dialog .skill-actions button{border:1px solid #ded9cf;background:#fff;border-radius:7px;padding:6px 9px;color:#3d4d64;cursor:pointer}#settings-dialog .settings-section{border-top:1px solid var(--line);padding-top:13px;margin-top:14px}#settings-dialog .settings-note{font-size:11px;line-height:1.5;color:var(--muted)}</style>
<dialog id="settings-dialog"><h2>StudyUI 设置</h2><p>模型密钥写入本机系统凭据库；项目权限、Skills 和模型设置保存在本机。</p>
<form id="model-form"><div class="settings-section"><h3>模型管理</h3><label for="model-name">配置名称</label><input id="model-name" maxlength="80" value="DeepSeek" required><label for="model-url">API 地址</label><input id="model-url" type="url" value="https://api.deepseek.com" required><label for="model-name-id">模型名</label><input id="model-name-id" value="deepseek-flash" required><label for="model-key">API 密钥</label><input id="model-key" type="password" autocomplete="new-password" placeholder="已保存密钥可留空；新密钥只写入系统凭据库"><div class="dialog-actions"><button type="button" class="cancel" id="test-model">测试连接</button><button class="primary" type="submit">保存模型</button></div></div></form>
<div class="settings-section"><h3>项目权限</h3><label for="permission-preset">当前项目的权限档位</label><select id="permission-preset"><option value="read_only">只读</option><option value="project_collaboration">项目协作</option><option value="per_action">逐项审批</option><option value="skill_sandbox">审核后沙箱 Skill</option></select><p id="permission-description" class="settings-note"></p></div>
<div class="settings-section"><h3>科研 Skills</h3><p class="settings-note">导入 ZIP 中必须有一个 SKILL.md。含脚本的 Skill 需要按当前版本审核；运行要求本机 Docker 沙箱。</p><input id="skill-upload" type="file" accept=".zip,application/zip"><div id="skills-list"></div></div>
<div class="dialog-actions"><button type="button" class="cancel" id="settings-close">关闭</button></div></dialog>
<script>
const feed=document.querySelector('#feed'),sessions=document.querySelector('#sessions'),projectsNode=document.querySelector('#projects'),input=document.querySelector('#input'),send=document.querySelector('#send');
let active='',allSessions=[],allProjects=[],selectedProject='all',modelConfigured=false;
const remembered=localStorage.getItem('studyui.project');if(remembered)selectedProject=remembered;
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
async function api(path,{method='GET',body}={}){const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw new Error(j.error||'请求失败');return j}
const permissionText={read_only:'可查看项目、节点与科研来源；不能修改或运行工作流。',project_collaboration:'用户明确授权任务后，可在当前项目内建流、改流、运行和迭代。',per_action:'每次工具操作都需单独批准。',skill_sandbox:'项目协作，并允许已审核版本的 Skill 在离线 Docker 沙箱执行。'};
async function loadSettings(){try{const [model,permission,skills]=await Promise.all([api('/api/settings/model'),api(`/api/permissions?project_id=${encodeURIComponent(selectedProject==='all'||selectedProject==='__ungrouped__'?'':selectedProject)}`),api('/api/skills')]);document.querySelector('#model-name').value=model.name||'DeepSeek';document.querySelector('#model-url').value=model.base_url||'https://api.deepseek.com';document.querySelector('#model-name-id').value=model.model||'deepseek-flash';document.querySelector('#model-key').value='';document.querySelector('#model-key').placeholder=model.credential_saved?'密钥已保存在系统凭据库；留空保持不变':'请输入 API 密钥';document.querySelector('#permission-preset').value=permission.preset;document.querySelector('#permission-description').textContent=permissionText[permission.preset]||'';renderSkills(skills.skills||[])}catch(e){toast(e.message)}}
function renderSkills(rows){const root=document.querySelector('#skills-list');root.replaceChildren();if(!rows.length){root.append(el('p','settings-note','尚未导入 Skills'));return}for(const s of rows){const row=el('div','skill-row');row.append(el('strong','',`${s.title||s.name}${s.builtin?' · 内置':''}`),el('p','settings-note',s.description||''));row.append(el('p','settings-note',`版本 ${s.version||'未标记'} · SHA-256 ${String(s.sha256||'').slice(0,16)}… · ${s.enabled?'已启用':'未启用'}`));if(s.version_history?.length)row.append(el('p','settings-note',`历史版本：${s.version_history.map(x=>String(x).slice(0,12)).join('、')}`));if(s.scripts?.length)row.append(el('p','settings-note',`脚本：${s.scripts.join('、')}；${s.trusted?'当前版本已审核':'尚未审核'}`));const actions=el('div','skill-actions');if(!s.builtin){const toggle=el('button','',s.enabled?'停用':'启用');toggle.onclick=async()=>{try{await api(`/api/skills/${encodeURIComponent(s.name)}`,{method:'PATCH',body:{enabled:!s.enabled,session_id:active}});await loadSettings()}catch(e){toast(e.message)}};actions.append(toggle);if(s.scripts?.length&&!s.trusted){const trust=el('button','','审核并信任此版本');trust.onclick=async()=>{if(!window.confirm(`确认已审核 Skill「${s.name}」的全部文件，并信任版本 ${s.sha256.slice(0,16)}…？脚本只会在离线 Docker 沙箱中运行。`))return;try{await api(`/api/skills/${encodeURIComponent(s.name)}/trust`,{method:'POST',body:{sha256:s.sha256,session_id:active}});if(active){const session=await api(`/api/sessions/${active}`);showApprovals(session.pending_approvals)}toast('当前 Skill 版本已提交一次性审核')}catch(e){toast(e.message)}};actions.append(trust)}const remove=el('button','','移除');remove.onclick=async()=>{if(!window.confirm(`移除 Skill「${s.name}」？`))return;try{await api(`/api/skills/${encodeURIComponent(s.name)}/remove`,{method:'POST',body:{session_id:active}});if(active){const session=await api(`/api/sessions/${active}`);showApprovals(session.pending_approvals)}toast('移除申请已提交审批')}catch(e){toast(e.message)}};actions.append(remove)}row.append(actions);root.append(row)}}
async function saveModel(){const body={name:document.querySelector('#model-name').value.trim(),base_url:document.querySelector('#model-url').value.trim(),model:document.querySelector('#model-name-id').value.trim()};const key=document.querySelector('#model-key').value;if(key)body.api_key=key;await api('/api/settings/model',{method:'POST',body});document.querySelector('#model-key').value='';const health=await api('/api/health');modelConfigured=health.model_configured;document.querySelector('#model-status').textContent=modelConfigured?'AI 模型已就绪':'AI 模型未配置';document.querySelector('#model-status').classList.toggle('ready',modelConfigured)}
function addMessage(role,text){feed.append(el('div','msg '+(role==='user'?'user':'assistant'),text));feed.scrollTop=feed.scrollHeight}
function showArtifacts(items){if(!Array.isArray(items)||!items.length)return;const card=el('section','artifact-card');card.append(el('h3','','本次生成文件（含 SHA-256）'));for(const item of items){if(!item||!item.download_url)continue;const row=el('div','artifact-row');const link=document.createElement('a');link.href=item.download_url;link.download=item.name||'studyui-output';link.textContent=`⬇ ${item.name||'下载文件'} · ${Number(item.size||0).toLocaleString()} B`;row.append(link);row.append(el('span','artifact-hash',`SHA-256 ${item.sha256||''}`));card.append(row)}if(card.childElementCount>1){feed.append(card);feed.scrollTop=feed.scrollHeight}}
function showWelcome(){feed.replaceChildren();const welcome=el('div','welcome');welcome.append(el('div','welcome-mark','S'),el('h2','',selectedProject==='all'?'让研究从这里开始':`继续探索「${selectedTitle()}」`),el('p','',`把研究问题、论文依据或原始数据的处理目标告诉 StudyUI。你可以先从一个具体问题开始，再逐步整理证据、节点和工作流。`));const prompts=el('div','prompts');for(const text of ['梳理 DNA Origami 纳米间隙研究的复现条件','检查从原始测量数据到结果图的处理链','根据研究目标规划工作流']){const b=el('button','prompt-chip',text);b.onclick=()=>{input.value=text;input.focus()};prompts.append(b)}welcome.append(prompts);feed.append(welcome)}
function toast(text){const item=el('div','toast',text);document.body.append(item);setTimeout(()=>item.remove(),2600)}
function selectedTitle(){if(selectedProject==='all')return '全部项目';if(selectedProject==='__ungrouped__')return '未归类';return allProjects.find(p=>p.id===selectedProject)?.title||'全部项目'}
async function refresh(){[allProjects,allSessions]=await Promise.all([api('/api/projects'),api('/api/sessions')]);renderProjects();renderSessions();document.querySelector('#view-title').textContent=selectedTitle()==='全部项目'?'研究对话':selectedTitle();document.querySelector('#view-subtitle').textContent=selectedProject==='all'?'围绕研究目标讨论证据、原始数据与工作流。':`当前工作区：${selectedTitle()}。新建会话将归入此项目。`}
function selectProject(id){selectedProject=id;localStorage.setItem('studyui.project',id);active='';renderProjects();renderSessions();syncFlowProject();document.querySelector('#view-title').textContent=id==='all'?'研究对话':selectedTitle();document.querySelector('#view-subtitle').textContent=id==='all'?'围绕研究目标讨论证据、原始数据与工作流。':`当前工作区：${selectedTitle()}。新建会话将归入此项目。`;showWelcome()}
function renderProjects(){projectsNode.replaceChildren();const ungrouped=allSessions.filter(s=>!s.project_id).length;const rows=[{id:'all',title:'全部项目',count:allSessions.length,icon:'⌂'},{id:'__ungrouped__',title:'未归类',count:ungrouped,icon:'◦'},...allProjects.map(p=>({id:p.id,title:p.title,count:p.session_count,icon:'▰',project:true}))];for(const p of rows){const row=el('div',p.project?'project-row':'');const b=el('button','group-label'+(selectedProject===p.id?' active':''));b.append(el('span','',p.icon),el('span','project-name',p.title),el('span','count',String(p.count||0)));b.onclick=()=>selectProject(p.id);row.append(b);if(p.project){const menu=el('button','project-action','⋯');menu.title='管理项目';menu.setAttribute('aria-label',`管理项目：${p.title}`);menu.onclick=async e=>{e.stopPropagation();const choice=window.prompt(`项目：${p.title}\n输入 1 重命名，输入 2 删除项目（保留会话，工作流移入恢复目录）：`,'1');if(choice==='1'){const title=window.prompt('新的项目名称',p.title);if(title?.trim()){try{await api(`/api/projects/${p.id}`,{method:'PATCH',body:{title}});await refresh()}catch(err){toast(err.message)}}}else if(choice==='2'&&window.confirm(`删除项目「${p.title}」？研究会话会保留在「未归类」，项目中的工作流会移入恢复目录。`)){try{await api(`/api/projects/${p.id}`,{method:'DELETE'});if(selectedProject===p.id)selectedProject='__ungrouped__';await refresh();toast('项目已删除，会话已保留，工作流已移入恢复目录')}catch(err){toast(err.message)}}};row.append(menu)}projectsNode.append(row)}}
function renderSessions(){sessions.replaceChildren();let rows=allSessions;if(selectedProject==='__ungrouped__')rows=rows.filter(s=>!s.project_id);else if(selectedProject!=='all')rows=rows.filter(s=>s.project_id===selectedProject);document.querySelector('#session-heading').textContent=selectedProject==='all'?'最近会话':`${selectedTitle()} · 会话`;if(!rows.length){sessions.append(el('div','empty-side',selectedProject==='all'?'还没有研究会话':'暂无会话，点击上方按钮开始'));return}for(const s of rows){const wrap=el('div','session-wrap');const b=el('button','session'+(s.id===active?' active':''),s.title||'研究任务');b.title=s.title||'研究任务';b.onclick=()=>openSession(s.id);wrap.append(b);const action=el('button','session-action','⋯');action.title='会话操作';action.onclick=async e=>{e.stopPropagation();const options=['重命名','移动到项目','移至未归类'];const choice=window.prompt(`会话：${s.title}\n1 重命名\n2 移动到项目\n3 移至未归类`,'1');try{if(choice==='1'){const title=window.prompt('新的会话名称',s.title);if(title?.trim())await api(`/api/sessions/${s.id}`,{method:'PATCH',body:{title}})}else if(choice==='2'){let target=selectedProject!=='all'&&selectedProject!=='__ungrouped__'?selectedProject:'';if(!target&&allProjects.length){const menu=allProjects.map((p,i)=>`${i+1}. ${p.title}`).join('\n');const index=Number(window.prompt(`输入项目序号：\n${menu}`,'1'))-1;target=allProjects[index]?.id||''}if(target)await api(`/api/sessions/${s.id}`,{method:'PATCH',body:{project_id:target}})}else if(choice==='3'){await api(`/api/sessions/${s.id}`,{method:'PATCH',body:{project_id:null}})}else return;await refresh();if(active===s.id&&choice==='3')await openSession(s.id)}catch(err){toast(err.message)}};wrap.append(action);sessions.append(wrap)}}
function showProposals(rows){for(const p of rows||[]){const card=el('article','proposal');card.dataset.id=p.id;card.append(el('h3','',`待审核：${p.summary.flow_name||'工作流改动'}`));card.append(el('p','',p.summary.rationale||''));const ul=el('ul');for(const c of p.summary.changes||[])ul.append(el('li','',c));card.append(ul);const btns=el('div','actions');const a=el('button','approve','批准并保存'),r=el('button','reject','拒绝');a.onclick=()=>decision(p.id,'approve',card);r.onclick=()=>decision(p.id,'reject',card);btns.append(a,r);card.append(btns);feed.append(card)}feed.scrollTop=feed.scrollHeight}
function showApprovals(rows){for(const item of rows||[]){if(feed.querySelector(`[data-approval="${item.id}"]`))continue;const card=el('article','proposal');card.dataset.approval=item.id;const summary=item.summary||{};card.append(el('h3','',`需要审批：${summary.title||item.action}`),el('p','',summary.impact||item.reason||`项目 ${item.project_id||'未归类'} 中的操作等待一次性批准。`));if(summary.nodes?.length)card.append(el('p','settings-note',`节点：${summary.nodes.join('、')}`));if(summary.scripts?.length)card.append(el('p','settings-note',`脚本：${summary.scripts.join('、')}`));card.append(el('p','settings-note',summary.reason||item.reason||''));const btns=el('div','actions');const a=el('button','approve','批准并执行'),r=el('button','reject','拒绝'),c=el('button','','取消');a.onclick=()=>approvalDecision(item.id,'approve',card);r.onclick=()=>approvalDecision(item.id,'reject',card);c.onclick=()=>approvalDecision(item.id,'cancel',card);btns.append(a,r,c);card.append(btns);feed.append(card)}feed.scrollTop=feed.scrollHeight}
async function approvalDecision(id,decision,card){try{const r=await api(`/api/approvals/${id}/${decision}`,{method:'POST',body:{}});card.remove();if(r.status==='completed'){addMessage('assistant',`已执行获批操作。${JSON.stringify(r.result||{}).slice(0,1200)}`);showArtifacts(r.result?.artifacts||[])}else addMessage('assistant',decision==='approve'?'已批准。':decision==='cancel'?'已取消该审批。':'已拒绝该操作。');await loadSettings()}catch(e){addMessage('assistant',e.message)}}
async function decision(id,action,card){try{const r=await api(`/api/proposals/${id}/${action}`,{method:'POST',body:{}});card.remove();addMessage('assistant',action==='approve'?`提案已保存到 Langflow：${r.flow_name||''}`:'已拒绝该提案。')}catch(e){addMessage('assistant',e.message)}}
async function openSession(id){active=id;const s=allSessions.find(row=>row.id===id);if(s){selectedProject=s.project_id||'__ungrouped__';localStorage.setItem('studyui.project',selectedProject)}feed.replaceChildren();renderProjects();renderSessions();try{const data=await api(`/api/sessions/${id}`);const visible=(data.messages||[]).filter(m=>m.role==='user'||m.role==='assistant');if(visible.length){for(const m of visible)addMessage(m.role,m.content||'')}else showWelcome();showArtifacts(data.artifacts||[]);showProposals(data.pending_proposals);showApprovals(data.pending_approvals)}catch(e){addMessage('assistant',e.message)}}
async function newSession(){try{const projectId=selectedProject!=='all'&&selectedProject!=='__ungrouped__'?selectedProject:null;const data=await api('/api/sessions',{method:'POST',body:{title:'研究任务',project_id:projectId}});await refresh();await openSession(data.id);feed.replaceChildren();addMessage('assistant',`你好，我是 StudyUI。${projectId?`本次研究会话属于「${selectedTitle()}」。`:''}告诉我你的研究目标、数据类型或需要检查的工作流，我会先梳理证据和待确认条件。`)}catch(e){toast(e.message)}}
async function submit(){const text=input.value.trim();if(!text||!active)return;input.value='';send.disabled=true;addMessage('user',text);try{const data=await api(`/api/sessions/${active}/messages`,{method:'POST',body:{message:text}});addMessage('assistant',data.message||'');showArtifacts(data.artifacts||[]);showProposals(data.pending_proposals);showApprovals(data.pending_approvals);await refresh()}catch(e){addMessage('assistant',e.message)}finally{send.disabled=false;input.focus()}}
function syncFlowProject(){const frame=document.querySelector('#flow-frame');if(!frame.dataset.loaded)return;const project=allProjects.some(p=>p.id===selectedProject)?selectedProject:'';if(frame.dataset.project!==project){frame.dataset.project=project;frame.src=project?new URL('all/folder/'+encodeURIComponent(project),frame.dataset.src).href:frame.dataset.src}}
function showView(name){const chat=name==='chat';document.querySelector('#chat-view').hidden=!chat;document.querySelector('#flow-view').hidden=chat;document.querySelector('#nav-chat').classList.toggle('active',chat);document.querySelector('#nav-flow').classList.toggle('active',!chat);document.querySelector('#new').hidden=!chat;if(!chat){const frame=document.querySelector('#flow-frame');if(!frame.dataset.loaded){frame.dataset.loaded='1';frame.dataset.project='__initial__';syncFlowProject()}}}
document.querySelector('#nav-chat').onclick=()=>showView('chat');document.querySelector('#nav-flow').onclick=()=>showView('flow');document.querySelector('#new').onclick=newSession;send.onclick=submit;input.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submit()}};
const dialog=document.querySelector('#project-dialog');document.querySelector('#add-project').onclick=()=>{document.querySelector('#project-title').value='';dialog.showModal();setTimeout(()=>document.querySelector('#project-title').focus(),30)};document.querySelector('#cancel-project').onclick=()=>dialog.close();document.querySelector('#project-form').onsubmit=async e=>{e.preventDefault();const title=document.querySelector('#project-title').value.trim();if(!title)return;try{const result=await api('/api/projects',{method:'POST',body:{title}});dialog.close();await refresh();selectProject(result.id);toast('项目已创建')}catch(err){toast(err.message)}};
const settingsDialog=document.querySelector('#settings-dialog');document.querySelector('#settings-open').onclick=async()=>{await loadSettings();settingsDialog.showModal()};document.querySelector('#settings-close').onclick=()=>settingsDialog.close();document.querySelector('#model-form').onsubmit=async e=>{e.preventDefault();try{await saveModel();toast('模型配置已保存')}catch(err){toast(err.message)}};document.querySelector('#test-model').onclick=async()=>{try{await saveModel();await api('/api/settings/model/test',{method:'POST',body:{}});toast('模型连接成功')}catch(err){toast(`连接失败：${err.message}`)}};document.querySelector('#permission-preset').onchange=async e=>{try{const result=await api('/api/permissions',{method:'POST',body:{project_id:selectedProject==='all'||selectedProject==='__ungrouped__'?null:selectedProject,preset:e.target.value,session_id:active}});if(result.status==='pending_approval'){toast('权限升级已提交审批');if(active){const session=await api(`/api/sessions/${active}`);showApprovals(session.pending_approvals)}}else{document.querySelector('#permission-description').textContent=permissionText[result.preset]||'';toast('项目权限已更新')}}catch(err){toast(err.message);await loadSettings()}};document.querySelector('#skill-upload').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;try{if(!active)throw new Error('请先打开研究会话');const response=await fetch('/api/skills/preview',{method:'POST',headers:{'Content-Type':'application/zip','X-Filename':encodeURIComponent(file.name),'X-StudyUI-Session':active},body:file});const data=await response.json();if(!response.ok)throw new Error(data.error||'Skill 导入失败');const session=await api(`/api/sessions/${active}`);showApprovals(session.pending_approvals);toast('Skill 已完成安全检查，等待一次性审批')}catch(err){toast(err.message)}finally{e.target.value=''}};
(async()=>{try{const health=await api('/api/health');modelConfigured=health.model_configured;document.querySelector('#model-status').textContent=modelConfigured?'AI 模型已就绪':'AI 模型未配置';if(modelConfigured)document.querySelector('#model-status').classList.add('ready');await refresh();if(selectedProject!=='all'&&selectedProject!=='__ungrouped__'&&!allProjects.some(p=>p.id===selectedProject))selectedProject='all';renderProjects();renderSessions();const first=allSessions.find(s=>selectedProject==='all'||(selectedProject==='__ungrouped__'?!s.project_id:s.project_id===selectedProject));if(first)await openSession(first.id);else if(!allSessions.length)await newSession();else selectProject(selectedProject)}catch(e){addMessage('assistant',e.message)}})();
</script></body></html>"""

PAGE = PAGE.replace(
    "</body></html>",
    r"""<script>
const profilePicker=document.createElement('select');profilePicker.id='model-profile-picker';profilePicker.setAttribute('aria-label','选择模型配置');profilePicker.style.width='100%';profilePicker.style.margin='4px 0 12px';document.querySelector('#model-form .settings-section').prepend(profilePicker);
const baseApi=api;api=async function(path,options={}){if(path.startsWith('/api/projects/')&&options.method==='DELETE'&&!options.body)options={...options,body:{session_id:active}};const value=await baseApi(path,options);if(path.startsWith('/api/projects/')&&options.method==='DELETE'&&value.status==='pending_approval'){if(active){const session=await baseApi(`/api/sessions/${active}`);showApprovals(session.pending_approvals)}throw new Error('项目删除已提交一次性审批；请在对话中的审批卡片确认')}return value};
const profileActions=document.createElement('div');profileActions.className='dialog-actions';profileActions.innerHTML='<button type="button" id="new-model-profile">新增配置</button><button type="button" id="delete-model-profile">删除当前配置</button>';document.querySelector('#model-form .settings-section').insertBefore(profileActions,document.querySelector('#model-name'));
const originalLoadSettings=loadSettings;loadSettings=async function(){await originalLoadSettings();try{const value=await api('/api/settings/model');profilePicker.replaceChildren();for(const p of value.profiles||[]){const o=document.createElement('option');o.value=p.id;o.textContent=`${p.name} · ${p.model}${p.active?'（当前）':''}`;profilePicker.append(o)}profilePicker.value=value.id||value.profiles?.find(p=>p.active)?.id||'';profilePicker.disabled=!(value.profiles||[]).length;document.querySelector('#delete-model-profile').disabled=(value.profiles||[]).length<2}catch(e){toast(e.message)}};
profilePicker.onchange=async()=>{try{await api('/api/settings/model/activate',{method:'POST',body:{profile_id:profilePicker.value}});await loadSettings()}catch(e){toast(e.message)}};
document.querySelector('#new-model-profile').onclick=()=>{profilePicker.value='';document.querySelector('#model-name').value='新模型';document.querySelector('#model-url').value='https://api.deepseek.com';document.querySelector('#model-name-id').value='deepseek-flash';document.querySelector('#model-key').value='';document.querySelector('#model-key').placeholder='请输入新配置的 API 密钥';document.querySelector('#model-form').dataset.createNew='1'};
saveModel=async function(){const form=document.querySelector('#model-form');const body={name:document.querySelector('#model-name').value.trim(),base_url:document.querySelector('#model-url').value.trim(),model:document.querySelector('#model-name-id').value.trim()};if(form.dataset.createNew==='1')body.create_new=true;else if(profilePicker.value&&profilePicker.value!=='environment')body.profile_id=profilePicker.value;const key=document.querySelector('#model-key').value;if(key)body.api_key=key;await api('/api/settings/model',{method:'POST',body});form.dataset.createNew='';document.querySelector('#model-key').value='';const health=await api('/api/health');modelConfigured=health.model_configured;document.querySelector('#model-status').textContent=modelConfigured?'AI 模型已就绪':'AI 模型未配置';document.querySelector('#model-status').classList.toggle('ready',modelConfigured);await loadSettings()};
document.querySelector('#delete-model-profile').onclick=async()=>{const id=profilePicker.value;if(!id||!window.confirm('删除当前模型配置及其系统凭据？'))return;try{await api('/api/settings/model',{method:'DELETE',body:{profile_id:id}});await loadSettings();toast('模型配置已删除')}catch(e){toast(e.message)}};
</script></body></html>""",
)


class StudyUIHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_handler(harness, langflow_url):
    class Handler(BaseHTTPRequestHandler):
        server_version = "StudyUI/0.1"

        def log_message(self, fmt, *args):
            print("[agent] " + fmt % args, flush=True)

        def _send(self, status, value, content_type="application/json; charset=utf-8"):
            raw = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _local_host(self):
            host = self.headers.get("Host", "")
            parsed = urlsplit("http://" + host)
            return parsed.hostname in {"localhost", "127.0.0.1", "::1"}

        def _same_origin_or_non_browser(self):
            origin = self.headers.get("Origin")
            if not origin:
                return True
            parsed_origin = urlsplit(origin)
            host = urlsplit("http://" + self.headers.get("Host", ""))
            return (
                parsed_origin.scheme == "http"
                and parsed_origin.hostname in {"localhost", "127.0.0.1", "::1"}
                and parsed_origin.port == host.port
            )

        def _body(self):
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 64_000:
                raise ValueError("Request body must be between 1 and 64000 bytes")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Request body must be a JSON object")
            return data

        def _error(self, exc, status=400):
            self._send(status, {"error": str(exc)[:1000]})

        def do_GET(self):
            if not self._local_host():
                return self._error("Only loopback Host headers are accepted", 403)
            path = urlsplit(self.path).path
            if path == "/":
                page = PAGE.replace(
                    "__LANGFLOW_BASE_URL__", html.escape(langflow_url.rstrip("/"), quote=True)
                )
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/api/health":
                profile = harness.model_profiles.active()
                return self._send(
                    200,
                    {
                        "status": "ok",
                        "service": "StudyUI",
                        "model_configured": bool(profile.get("configured")),
                        "langflow_url": getattr(harness.langflow, "base_url", langflow_url),
                        "workflow_storage": "json"
                        if isinstance(harness.langflow, FileWorkflowClient)
                        else "database",
                    },
                )
            if path == "/api/settings/model":
                return self._send(200, harness.model_profiles.public())
            if path == "/api/permissions":
                project_id = parse_qs(urlsplit(self.path).query).get("project_id", [None])[0]
                preset = harness.permissions.get_preset(project_id)
                from .permissions import PRESETS

                return self._send(200, {"project_id": project_id, "preset": preset, "presets": PRESETS})
            if path == "/api/skills":
                return self._send(200, {"skills": harness.skills.list()})
            if path == "/api/sessions":
                return self._send(200, harness.store.list_sessions())
            if path == "/api/projects":
                return self._send(200, harness.store.list_projects())
            if path.startswith("/api/sessions/"):
                parts = path.strip("/").split("/")
                if len(parts) == 5 and parts[3] == "artifacts":
                    session_id, artifact_id = unquote(parts[2]), unquote(parts[4])
                    artifact = harness.store.get_artifact(artifact_id, session_id)
                    if artifact is None:
                        return self._error("Artifact not found", 404)
                    artifact_root = harness.artifact_root.resolve()
                    stored_path = Path(artifact["path"])
                    if stored_path.is_symlink():
                        return self._error("Artifact path is invalid", 404)
                    file_path = stored_path.resolve()
                    if not file_path.is_relative_to(artifact_root) or not file_path.is_file():
                        return self._error("Artifact path is invalid", 404)
                    if (
                        file_path.stat().st_size != artifact["size"]
                        or file_path.stat().st_size > 20 * 1024 * 1024
                    ):
                        return self._error("Artifact changed after it was registered", 409)
                    raw = file_path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
                        return self._error("Artifact checksum mismatch", 409)
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        mimetypes.guess_type(artifact["name"])[0] or "application/octet-stream",
                    )
                    self.send_header(
                        "Content-Disposition",
                        "attachment; filename=studyui-output; filename*=UTF-8''" + quote(artifact["name"]),
                    )
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if len(parts) != 3:
                    return self._error("Not found", 404)
                session_id = unquote(parts[2])
                if not harness.store.has_session(session_id):
                    return self._error("Conversation does not exist", 404)
                return self._send(
                    200,
                    {
                        "messages": [
                            message
                            for message in harness.store.messages(session_id, limit=200)
                            if message.get("role") in {"user", "assistant"} and not message.get("tool_calls")
                        ],
                        "pending_proposals": harness.store.pending_proposals(session_id),
                        "pending_approvals": harness.store.pending_approvals(session_id),
                        "artifacts": harness.store.list_artifacts(session_id),
                    },
                )
            return self._error("Not found", 404)

        def do_POST(self):
            if not self._local_host():
                return self._error("Only loopback Host headers are accepted", 403)
            if not self._same_origin_or_non_browser():
                return self._error("Cross-origin requests are not accepted", 403)
            path = urlsplit(self.path).path
            try:
                if path == "/api/skills/import":
                    return self._error(
                        "Direct Skill installation is disabled; submit a reviewed package for approval", 403
                    )
                if path == "/api/skills/preview":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 2_000_000:
                        return self._error("Skill upload must be between 1 byte and 2 MB", 413)
                    raw = self.rfile.read(length)
                    filename = unquote(self.headers.get("X-Filename", "skill.zip"))
                    session_id = unquote(self.headers.get("X-StudyUI-Session", ""))
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before requesting Skill installation")
                    item = harness.skills.stage_zip(filename, raw)
                    action = item["action"]
                    is_update = action == "skill.update"
                    summary = {
                        "title": f"{'更新' if is_update else '安装'} Skill：{item['title']}",
                        "impact": f"导入版本 SHA-256 {item['sha256']}；Skill 默认停用。"
                        + (f"将替换当前版本 {item['current_sha256']}，并保留历史版本。" if is_update else ""),
                        "scripts": item["scripts"],
                        "reason": "用户上传的 Skill 包已完成路径、大小与清单校验，等待一次性审批。",
                    }
                    try:
                        result = harness.request_approval(
                            session_id,
                            action,
                            summary["reason"],
                            {
                                "kind": "skill.import",
                                "stage_id": item["stage_id"],
                                "filename": filename,
                                "name": item["name"],
                                "sha256": item["sha256"],
                                "replace": is_update,
                                "current_sha256": item["current_sha256"],
                                "summary": summary,
                            },
                            project_id=harness.store.session_context(session_id).get("project_id"),
                        )
                    except Exception:
                        harness.skills.discard_staged(item["stage_id"])
                        raise
                    return self._send(202, {**result, **summary})
                data = self._body()
                if path == "/api/projects":
                    project_id = harness.store.create_project(
                        data.get("title", ""), data.get("description", "")
                    )
                    return self._send(201, {"id": project_id})
                if path == "/api/sessions":
                    session_id = harness.new_session(data.get("title", "科研任务"), data.get("project_id"))
                    return self._send(201, {"id": session_id})
                if path.startswith("/api/sessions/") and path.endswith("/messages"):
                    session_id = unquote(path.split("/")[-2])
                    result = harness.run_turn(session_id, data.get("message"))
                    return self._send(200, result)
                if path.startswith("/api/proposals/"):
                    parts = path.strip("/").split("/")
                    if len(parts) != 4 or parts[1] != "proposals" or parts[3] not in {"approve", "reject"}:
                        return self._error("Not found", 404)
                    proposal_id, decision = unquote(parts[2]), parts[3]
                    result = (
                        harness.approve_proposal(proposal_id)
                        if decision == "approve"
                        else harness.reject_proposal(proposal_id)
                    )
                    return self._send(200, result)
                if path == "/api/settings/model":
                    result = harness.model_profiles.save(
                        name=data.get("name", "DeepSeek"),
                        base_url=data.get("base_url", "https://api.deepseek.com"),
                        model=data.get("model", "deepseek-flash"),
                        api_key=data.get("api_key"),
                        profile_id=data.get("profile_id"),
                        create_new=bool(data.get("create_new")),
                    )
                    harness._refresh_model()
                    return self._send(
                        200,
                        {
                            key: value
                            for key, value in result.items()
                            if key not in {"credential_ref", "api_key"}
                        },
                    )
                if path == "/api/settings/model/activate":
                    result = harness.model_profiles.activate(data.get("profile_id", ""))
                    harness._refresh_model()
                    return self._send(200, result)
                if path == "/api/settings/model/test":
                    harness._refresh_model()
                    response = harness.model.complete(
                        [
                            {"role": "system", "content": "Return exactly the word READY."},
                            {"role": "user", "content": "Connection test. Reply READY."},
                        ],
                        [],
                        max_tokens=16,
                    )
                    return self._send(
                        200, {"ok": True, "model": harness.model.model, "response_received": bool(response)}
                    )
                if path == "/api/permissions":
                    project_id, preset = data.get("project_id"), data.get("preset", "")
                    from .permissions import PRESETS

                    if preset not in PRESETS:
                        return self._error("Unknown permission preset")
                    old = harness.permissions.get_preset(project_id)
                    capability = {
                        "read_only": {"read"},
                        "per_action": {"read", "ask"},
                        "project_collaboration": {"read", "ask", "project_write"},
                        "skill_sandbox": {"read", "ask", "project_write", "skill_script"},
                    }
                    session_id = data.get("session_id", "")
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before changing project permissions")
                    context = harness.store.session_context(session_id) or {}
                    if project_id and context.get("project_id") != project_id:
                        return self._error(
                            "Permission change session must belong to the selected project", 403
                        )
                    if not capability[preset].issubset(capability[old]):
                        summary = {
                            "title": "提升项目 Agent 权限",
                            "impact": f"权限档位将从「{PRESETS[old]['label']}」改为「{PRESETS[preset]['label']}」。",
                            "reason": PRESETS[preset]["description"],
                        }
                        queued = harness.request_approval(
                            session_id,
                            "permission.change",
                            summary["reason"],
                            {"kind": "permission.change", "preset": preset, "summary": summary},
                            project_id=project_id,
                        )
                        return self._send(202, {**queued, **summary})
                    result = harness.permissions.set_preset(project_id, preset)
                    harness.store.append_event(
                        session_id, "permission_changed", {"project_id": project_id, "preset": preset}
                    )
                    return self._send(200, result)
                if path.startswith("/api/skills/") and path.endswith("/trust"):
                    name = unquote(path.strip("/").split("/")[-2])
                    session_id = data.get("session_id", "")
                    item = harness.skills.get(name)
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before reviewing a Skill")
                    if item["sha256"] != data.get("sha256", ""):
                        return self._error("Skill changed since it was displayed; reload settings")
                    summary = {
                        "title": f"审核 Skill 版本：{name}",
                        "impact": f"信任 SHA-256 {item['sha256']}；此版本随后可在离线沙箱中调用。",
                        "scripts": item["scripts"],
                        "reason": "确认审核此确切版本及其所有脚本。",
                    }
                    queued = harness.request_approval(
                        session_id,
                        "skill.trust",
                        summary["reason"],
                        {"kind": "skill.trust", "name": name, "sha256": item["sha256"], "summary": summary},
                        project_id=harness.store.session_context(session_id).get("project_id"),
                    )
                    return self._send(202, {**queued, **summary})
                if path.startswith("/api/skills/") and path.endswith("/remove"):
                    name = unquote(path.strip("/").split("/")[-2])
                    session_id = data.get("session_id", "")
                    item = harness.skills.get(name)
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before requesting Skill removal")
                    summary = {
                        "title": f"移除 Skill：{name}",
                        "impact": f"从活动注册表中移除当前版本 {item['sha256']}。",
                        "reason": "Skill 移除需要一次性审批。",
                    }
                    queued = harness.request_approval(
                        session_id,
                        "skill.remove",
                        summary["reason"],
                        {"kind": "skill.remove", "name": name, "sha256": item["sha256"], "summary": summary},
                        project_id=harness.store.session_context(session_id).get("project_id"),
                    )
                    return self._send(202, {**queued, **summary})
                if path.startswith("/api/approvals/"):
                    parts = path.strip("/").split("/")
                    if len(parts) != 4 or parts[3] not in {"approve", "reject", "cancel"}:
                        return self._error("Not found", 404)
                    decision = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}[parts[3]]
                    result = harness.decide_approval(unquote(parts[2]), decision)
                    return self._send(200, result)
                return self._error("Not found", 404)
            except Exception as exc:
                self.log_message("request failed: %s", type(exc).__name__)
                return self._error(exc)

        def do_PATCH(self):
            if not self._local_host():
                return self._error("Only loopback Host headers are accepted", 403)
            if not self._same_origin_or_non_browser():
                return self._error("Cross-origin requests are not accepted", 403)
            path = urlsplit(self.path).path
            try:
                data = self._body()
                if path.startswith("/api/skills/"):
                    name = unquote(path.rsplit("/", 1)[-1])
                    result = harness.skills.set_enabled(name, data.get("enabled"))
                    session_id = data.get("session_id", "")
                    if not harness.store.has_session(session_id):
                        return self._error("Open a research session before changing Skill state")
                    harness.store.append_event(
                        session_id, "skill_enabled", {"name": result["name"], "enabled": result["enabled"]}
                    )
                    return self._send(200, result)
                if path.startswith("/api/projects/"):
                    project_id = unquote(path.rsplit("/", 1)[-1])
                    harness.store.update_project(project_id, data.get("title", ""))
                    return self._send(200, {"status": "updated"})
                if path.startswith("/api/sessions/"):
                    session_id = unquote(path.rsplit("/", 1)[-1])
                    harness.store.update_session(
                        session_id,
                        title=data.get("title") if "title" in data else None,
                        project_id=data.get("project_id") if "project_id" in data else ...,
                    )
                    return self._send(200, {"status": "updated"})
                return self._error("Not found", 404)
            except Exception as exc:
                self.log_message("request failed: %s", type(exc).__name__)
                return self._error(exc)

        def do_DELETE(self):
            if not self._local_host():
                return self._error("Only loopback Host headers are accepted", 403)
            if not self._same_origin_or_non_browser():
                return self._error("Cross-origin requests are not accepted", 403)
            path = urlsplit(self.path).path
            if path.startswith("/api/projects/"):
                try:
                    project_id = unquote(path.rsplit("/", 1)[-1])
                    data = self._body()
                    session_id = data.get("session_id", "")
                    context = (
                        harness.store.session_context(session_id)
                        if harness.store.has_session(session_id)
                        else None
                    )
                    if not context or context.get("project_id") != project_id:
                        return self._error(
                            "Project deletion approval must come from a session in that project", 403
                        )
                    summary = {
                        "title": f"删除项目：{project_id}",
                        "impact": "研究会话将保留并移至未归类；项目工作流将移入恢复目录。",
                        "reason": "项目删除是不可逆的项目管理操作，需一次性审批。",
                    }
                    result = harness.request_approval(
                        session_id,
                        "project.delete",
                        summary["reason"],
                        {"kind": "project.delete", "project_id": project_id, "summary": summary},
                        project_id=project_id,
                    )
                    return self._send(202, {**result, **summary})
                except Exception as exc:
                    return self._error(exc)
            if path == "/api/settings/model":
                try:
                    data = self._body()
                    result = harness.model_profiles.remove(str(data.get("profile_id", "")))
                    harness._refresh_model()
                    return self._send(200, result)
                except Exception as exc:
                    return self._error(exc)
            if path.startswith("/api/skills/"):
                return self._error("Skill removal requires a one-shot approval", 403)
            return self._error("Not found", 404)

    return Handler


def serve(
    host="127.0.0.1",
    port=7880,
    database=".demo-runtime/agent.sqlite3",
    langflow_url="http://127.0.0.1:7881",
    workflows=None,
    components=None,
):
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("StudyUI must bind to loopback")
    project_root = Path(__file__).resolve().parents[5]
    workflow_client = FileWorkflowClient(
        workflows or project_root / "workflows", components or project_root / ".demo-runtime" / "components"
    )
    harness = StudyUIAgent(database, langflow=workflow_client)
    server = StudyUIHTTPServer((host, port), make_handler(harness, langflow_url))
    print(f"StudyUI ready: http://{host}:{port}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("STUDYUI_PORT", "7880")))
    parser.add_argument(
        "--database", default=os.environ.get("STUDYUI_DATABASE", ".demo-runtime/agent.sqlite3")
    )
    parser.add_argument(
        "--langflow-url", default=os.environ.get("STUDYUI_LANGFLOW_URL", "http://127.0.0.1:7881")
    )
    parser.add_argument("--workflows", default=os.environ.get("STUDYUI_WORKFLOWS_DIR"))
    parser.add_argument("--components", default=os.environ.get("STUDYUI_COMPONENTS_DIR"))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    serve(args.host, args.port, args.database, args.langflow_url, args.workflows, args.components)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
