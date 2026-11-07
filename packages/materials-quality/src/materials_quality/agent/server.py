"""StudyUI's local research-agent application and embedded research canvas."""

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import shutil
import threading
from email.message import Message
from fastapi import FastAPI, Request
from fastapi.responses import Response
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

if __package__ is None or __package__ == "":
    import sys
    _pkg_dir = Path(__file__).resolve().parent
    _src_dir = _pkg_dir.parents[1]
    if str(_src_dir) not in sys.path:
        sys.path.insert(0, str(_src_dir))
    __package__ = "materials_quality.agent"

from .file_workflow_client import FileWorkflowClient
from .harness import StudyUIAgent

DEMO_DATASETS = [
    {
        "id": "ti64_tensile",
        "icon": "📈",
        "title": "钛合金拉伸力学性能",
        "format": "CSV",
        "filename": "01_钛合金拉伸力学性能_Ti64.csv",
        "desc": "20 个钛合金试样拉伸测试，计算弹性模量、0.2% 屈服强度与抗拉性能，绘制应力-应变曲线",
        "prompt": "请读取钛合金拉伸测试数据 {path}，计算各试样弹性模量与0.2%屈服强度，搭建力学分析工作流并绘制应力-应变图与实验报告。",
    },
    {
        "id": "raman_spectra",
        "icon": "🌈",
        "title": "多通道光谱寻峰与校正",
        "format": "CSV",
        "filename": "02_多通道光谱寻峰与校正_Spectra.csv",
        "desc": "包含 A/B 两组共 8 条光谱曲线，进行基线校正、窗口特征峰检测与多曲线拟合",
        "prompt": "请分析多曲线光谱数据 {path}，对 A/B 两组曲线执行基线校正与寻峰分析，绘制光谱拟合图并统计峰位分布。",
    },
    {
        "id": "material_contrast",
        "icon": "📊",
        "title": "材料组间试验与显著性",
        "format": "CSV",
        "filename": "03_材料组间试验与显著性_Contrast.csv",
        "desc": "聚合试样内技术重复测量，消除伪重复误差，执行方差分析与显著性多重比较",
        "prompt": "请分析材料组间对比实验数据 {path}，先聚合单位内技术重复，再进行独立样本方差分析与显著性检验，并出具对比图表。",
    },
    {
        "id": "zirconia_xrd",
        "icon": "⚡",
        "title": "3YSZ 氧化锆 XRD 衍射谱",
        "format": "TXT",
        "filename": "04_3YSZ氧化锆XRD衍射_带仪器头.txt",
        "desc": "前置 20 行仪器元数据文本，测试智能连续数值块嗅探与 2θ 多峰拟合分析",
        "prompt": "请检视氧化锆 XRD 原始测量文本 {path}，自动识别并跳过前置仪器头，搭建衍射分析工作流并对衍射峰进行高斯/洛伦兹拟合。",
    },
    {
        "id": "battery_cycle",
        "icon": "🔋",
        "title": "锂电池充放电循环特性",
        "format": "CSV",
        "filename": "05_锂电池充放电循环特性.csv",
        "desc": "多通道循环测试，测试“主干保留 + 派生分支”拓扑，绘制 SOC-电压充放电特征图",
        "prompt": "请处理锂电池充放电数据 {path}，采用主干保留加派生分支结构，分别绘制充电支路与放电支路的 SOC-电压关系曲线。",
    },
]

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>StudyUI</title><style>
:root{font-family:Inter,"Microsoft YaHei",system-ui,sans-serif;color:#252a31;background:#f6f3eb;--paper:#f6f3eb;--surface:#fffefa;--line:#e8e2d7;--ink:#252a31;--muted:#777b82;--blue:#29476f;--blue-dark:#203958;--blue-soft:#e9eef5;--nav-muted:#747b85}*{box-sizing:border-box}
body{margin:0;height:100vh;overflow:hidden;background:var(--paper)}button,textarea,input{font:inherit}.layout{height:100vh;display:grid;grid-template-columns:286px minmax(0,1fr)}
.side{background:#f1eee6;border-right:1px solid var(--line);padding:17px 13px 12px;display:flex;flex-direction:column;gap:15px;min-height:0}.brand-row{height:39px;display:flex;align-items:center;gap:10px;padding:0 9px}.brand-mark{width:27px;height:27px;border-radius:9px;background:var(--blue);color:#fff;display:grid;place-items:center;font:700 14px Georgia,serif}.brand{font:650 19px Georgia,"Microsoft YaHei",serif;letter-spacing:.15px;color:#242a32}.brand-note{margin-left:auto;color:#98958e;font-size:10px;letter-spacing:.5px}.nav{display:grid;gap:3px}.nav button,.new{border:0;color:#454b55;background:transparent;border-radius:9px;padding:10px 11px;cursor:pointer;text-align:left;display:flex;align-items:center;gap:10px;font-size:13px}.nav button:hover,.nav button.active{background:#e7e3da;color:var(--blue-dark)}.nav .ico{width:18px;text-align:center;font-size:15px;color:var(--nav-muted)}.new{border:1px solid #d9d4c9;background:#fffdf8;color:var(--blue);font-weight:600;justify-content:center;margin:1px 1px 0;padding:10px}.new:hover{background:#fff;color:var(--blue-dark);border-color:#b8c4d4}
.side-scroll{overflow:auto;min-height:0;display:flex;flex-direction:column;gap:10px}
.section-head{display:flex;align-items:center;justify-content:space-between;padding:0 4px 4px;color:#777971;font-size:11px;font-weight:650;letter-spacing:.5px;text-transform:uppercase}
.icon-btn{width:24px;height:24px;border:0;border-radius:6px;background:transparent;color:#69717c;cursor:pointer;font-size:16px;line-height:1;display:grid;place-items:center;transition:all .12s}
.icon-btn:hover{background:#e5e1d8;color:var(--blue)}
.project-dropdown-bar{display:flex;flex-direction:column;gap:5px;padding:0 2px 6px;border-bottom:1px solid #ded9ce}
.project-picker-select-wrap{position:relative;display:flex;align-items:center;background:#fffdf8;border:1px solid #d9d4c9;border-radius:8px;padding:0 8px;height:32px;box-shadow:0 1px 2px rgba(0,0,0,.03);transition:all .15s ease}
.project-picker-select-wrap:hover{border-color:#b8c4d4;background:#fff}
.project-picker-select-wrap:focus-within{border-color:#29476f;box-shadow:0 0 0 2px rgba(41,71,111,.15);background:#fff}
.project-picker-icon{font-size:13px;margin-right:6px;pointer-events:none;line-height:1}
#project-filter-select{flex:1;min-width:0;border:0;outline:none;background:transparent;font-family:inherit;font-size:12px;font-weight:550;color:#272f3a;cursor:pointer;-webkit-appearance:none;appearance:none;padding-right:18px;text-overflow:ellipsis;white-space:nowrap;overflow:hidden}
.project-picker-arrow{position:absolute;right:8px;font-size:10px;color:#7b828d;pointer-events:none}
.project-tree-root{display:flex;flex-direction:column;gap:2px;min-height:0}
.tree-group{display:flex;flex-direction:column}
.tree-head{display:flex;align-items:center;gap:6px;padding:6px 7px;border-radius:7px;cursor:pointer;font-size:12px;font-weight:600;color:#353c48;user-select:none;transition:background .12s,color .12s}
.tree-head:hover{background:#e7e3da;color:#1a222e}
.tree-head.current-project{background:#e4dfd5;color:#203958}
.tree-chevron{font-size:9px;width:13px;height:13px;display:inline-flex;align-items:center;justify-content:center;color:#7b828d;transition:transform .15s ease;flex-shrink:0}
.tree-group.collapsed .tree-chevron{transform:rotate(-90deg)}
.tree-group.expanded .tree-chevron{transform:rotate(0deg)}
.tree-folder-ico{font-size:12.5px;line-height:1;flex-shrink:0}
.tree-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-badge{font-size:10px;color:#787f8a;background:#e4dfd4;padding:1px 6px;border-radius:999px;min-width:16px;text-align:center;font-weight:500;flex-shrink:0}
.tree-actions{display:none;align-items:center;gap:2px;margin-left:2px;flex-shrink:0}
.tree-head:hover .tree-actions,.tree-head:focus-within .tree-actions{display:flex}
.tree-act-btn{width:20px;height:20px;border:0;border-radius:4px;background:transparent;color:#606874;cursor:pointer;display:grid;place-items:center;font-size:12px;line-height:1;padding:0;transition:all .12s}
.tree-act-btn:hover{background:#d8d3c5;color:#203958}
.tree-sessions{margin-left:11px;padding-left:8px;border-left:1.5px solid #ded9ce;display:flex;flex-direction:column;gap:2px;margin-top:2px;margin-bottom:4px}
.tree-session-row{display:flex;align-items:center;gap:2px;border-radius:6px;position:relative}
.tree-session-btn{flex:1;min-width:0;border:0;background:transparent;text-align:left;padding:6px 7px;border-radius:6px;font-size:11.5px;color:#49515d;cursor:pointer;display:flex;align-items:center;gap:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:all .12s}
.tree-session-btn:hover{background:#e7e2d7;color:#1e2632}
.tree-session-btn.active{background:#29476f;color:#ffffff;font-weight:600;box-shadow:0 1px 4px rgba(41,71,111,.15)}
.tree-session-btn.active .tree-session-icon{color:#c4d7ed}
.tree-session-btn.active .tree-session-title{color:#ffffff}
.tree-session-icon{font-size:11.5px;color:#7b828d;flex-shrink:0}
.tree-session-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tree-session-actions{opacity:0;display:flex;align-items:center;gap:1px;flex-shrink:0;transition:opacity .12s}
.tree-session-row:hover .tree-session-actions,.tree-session-row:focus-within .tree-session-actions{opacity:1}
.session-action{opacity:0;width:22px;height:22px;border:0;border-radius:5px;background:transparent;color:#777;cursor:pointer;display:grid;place-items:center;font-size:12px;line-height:1;padding:0}
.tree-session-row:hover .session-action,.tree-session-row:focus-within .session-action{opacity:1}
.session-action:hover{background:#d9d7d0}
.tree-empty-hint{padding:5px 8px;font-size:11px;color:#9a978f;font-style:italic}
.tree-filter-banner{display:flex;align-items:center;justify-content:space-between;padding:4px 8px;background:#e7e3da;border-radius:6px;font-size:11px;color:#48515e;margin-bottom:4px}
.tree-filter-banner .filter-tag{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:160px}
.clear-filter-btn{border:0;background:transparent;color:#29476f;cursor:pointer;font-size:11px;font-weight:600;padding:1px 4px;border-radius:4px}
.clear-filter-btn:hover{background:#d8d3c5}
.empty-side{padding:6px 10px;color:#9b9992;font-size:11px;line-height:1.6}
.side-foot{margin-top:auto;border-top:1px solid #ded9ce;padding:10px 6px 0;color:#89877f;font-size:10px;line-height:1.55}
main{min-width:0;min-height:0;height:100vh;background:var(--paper)}.view{height:100%;min-height:0;display:flex;flex-direction:column}.view[hidden]{display:none}.top{min-height:71px;padding:13px 28px;border-bottom:1px solid var(--line);background:rgba(255,254,250,.82);display:flex;align-items:center;justify-content:space-between;gap:16px}.top h1{font-size:16px;font-weight:650;margin:0 0 4px;color:#282d34}.top p{margin:0;color:var(--muted);font-size:12px}.top-actions{display:flex;align-items:center;gap:11px}.model-status{border:1px solid #e2ddd3;border-radius:999px;padding:6px 10px;color:#737780;font-size:10px;background:#fffdf9}.model-status::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:#c49a56;margin-right:7px;vertical-align:1px}.external{color:var(--blue);text-decoration:none;font-size:12px;white-space:nowrap}.external:hover{text-decoration:underline}
.view-mode-toggle{display:inline-flex;background:#ebe6dc;border-radius:9px;padding:2px;gap:2px;border:1px solid #ddd7cc;margin-right:2px}
.mode-btn{border:0;background:transparent;padding:5px 10px;border-radius:7px;cursor:pointer;font-size:11.5px;color:#555d68;font-weight:550;transition:all .15s}
.mode-btn:hover{color:var(--blue-dark)}
.mode-btn.active{background:#fff;color:var(--blue);box-shadow:0 1px 3px rgba(0,0,0,.08)}
main.split-mode{display:grid !important;grid-template-columns:minmax(380px,46%) minmax(440px,54%) !important;height:100vh}
main.split-mode .view{display:flex !important;height:100% !important;min-height:0;min-width:0}
main.split-mode #chat-view{border-right:1px solid var(--line)}
main.split-mode #flow-view{border-right:0}
.dropzone-overlay{position:absolute;inset:0;background:rgba(246,243,235,.95);border:2.5px dashed var(--blue);border-radius:14px;display:none;flex-direction:column;align-items:center;justify-content:center;gap:10px;z-index:999;color:var(--blue-dark);backdrop-filter:blur(4px);pointer-events:none}
.dropzone-overlay.active{display:flex !important}
.dropzone-overlay[hidden]{display:none !important}
.dropzone-overlay .drop-icon{font-size:40px}
.dropzone-overlay .drop-title{font-size:16px;font-weight:650}
.dropzone-overlay .drop-desc{font-size:12px;color:var(--muted)}
.demo-section{margin:22px auto 0;max-width:760px;text-align:left}
.demo-heading{font-size:12px;font-weight:650;color:#525b67;letter-spacing:.5px;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.demo-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}
.demo-card{background:#fffdf8;border:1px solid #ded8cc;border-radius:11px;padding:12px;cursor:pointer;transition:all .18s;display:flex;flex-direction:column;gap:5px;text-align:left}
.demo-card:hover{border-color:#29476f;background:#fff;box-shadow:0 4px 14px rgba(41,71,111,.1);transform:translateY(-1px)}
.demo-card-head{display:flex;align-items:center;gap:7px}
.demo-card-icon{font-size:16px}
.demo-card-title{font-size:12.5px;font-weight:650;color:#28313e;flex:1}
.demo-card-badge{font-size:9.5px;padding:2px 6px;border-radius:5px;background:#e8edf5;color:var(--blue);font-weight:600}
.demo-card-desc{font-size:11px;color:#777b83;line-height:1.45}
#feed{flex:1;min-height:0;overflow:auto;padding:28px max(24px,calc((100% - 820px)/2));display:flex;flex-direction:column;gap:14px}.msg{max-width:820px;padding:13px 16px;border-radius:14px;white-space:pre-wrap;line-height:1.65;overflow-wrap:anywhere;font-size:13px}.user{align-self:flex-end;background:#e5ebf3;color:#29374a;border:1px solid #dce3ed}.assistant{align-self:flex-start;background:var(--surface);border:1px solid var(--line);color:#343941}.artifact-card{align-self:flex-start;width:min(820px,100%);background:#fffefa;border:1px solid #ded8cc;border-radius:12px;padding:13px 15px}.artifact-card h3{margin:0 0 9px;font-size:12px;color:#4d5662}.artifact-row{padding:8px 0;border-top:1px solid #eee9e0;font-size:11px;overflow-wrap:anywhere}.artifact-row a{color:var(--blue);font-weight:650;text-decoration:none}.artifact-row a:hover{text-decoration:underline}.artifact-hash{display:block;margin-top:4px;color:#85878b;font:10px ui-monospace,monospace}.proposal{max-width:820px;background:#fffdf7;border:1px solid #d9d0bd;border-radius:12px;padding:15px}.proposal h3{margin:0 0 8px;font-size:14px}.proposal ul{margin:8px 0;padding-left:20px}.proposal p{margin:6px 0;color:#62646a;font-size:12px}.actions{display:flex;gap:8px;margin-top:12px}.actions button{border:0;border-radius:7px;padding:9px 13px;cursor:pointer;font-size:12px}.approve{background:var(--blue);color:white}.reject{background:#ece9e1;color:#333b46}
.welcome{margin:auto;max-width:590px;text-align:center;padding:36px 20px 48px}.welcome-mark{width:43px;height:43px;margin:0 auto 17px;border-radius:14px;background:var(--blue);color:white;display:grid;place-items:center;font:700 23px Georgia,serif;box-shadow:0 6px 20px #29476f26}.welcome h2{font:500 25px Georgia,"Microsoft YaHei",serif;color:#283342;margin:0 0 10px}.welcome p{font-size:13px;line-height:1.75;color:#777a80;margin:0 auto 23px;max-width:500px}.prompts{display:flex;flex-wrap:wrap;justify-content:center;gap:8px}.prompt-chip{border:1px solid #e0dbd0;background:#fffdf8;border-radius:999px;padding:8px 12px;color:#4c5868;font-size:11px;cursor:pointer}.prompt-chip:hover{border-color:#b9c5d3;color:var(--blue);background:#fff}
.composer{padding:13px 22px 15px;background:rgba(255,254,250,.84);border-top:1px solid var(--line)}.compose-inner{max-width:820px;margin:auto;display:flex;gap:9px;align-items:end;background:var(--surface);border:1px solid #dcd6ca;border-radius:14px;padding:7px;box-shadow:0 2px 10px #37311a0b}.compose-inner:focus-within{border-color:#a8b7ca;box-shadow:0 0 0 3px #29476f12}textarea{resize:vertical;min-height:45px;max-height:180px;flex:1;border:0;outline:0;background:transparent;border-radius:9px;padding:10px;font:inherit;font-size:13px;color:var(--ink)}textarea::placeholder{color:#9b9b9a}#send{height:39px;padding:0 17px;border:0;border-radius:9px;background:var(--blue);color:#fff;font-weight:600;font-size:12px;cursor:pointer}#send:hover{background:var(--blue-dark)}#send:disabled{opacity:.5;cursor:wait}.hint{max-width:820px;margin:7px auto 0;color:#8a8984;font-size:10px}.flow-top{min-height:71px}#flow-frame{flex:1;width:100%;min-height:0;border:0;background:#fff}
dialog{border:1px solid var(--line);border-radius:16px;background:var(--surface);color:var(--ink);padding:22px;width:min(420px,calc(100vw - 32px));box-shadow:0 18px 70px #22251f30}dialog::backdrop{background:#24283155;backdrop-filter:blur(2px)}dialog h2{font-size:17px;margin:0 0 7px}dialog p{font-size:12px;color:var(--muted);margin:0 0 17px}dialog label{display:block;font-size:12px;color:#656a72;margin-bottom:7px}dialog input{width:100%;border:1px solid #d9d5cc;border-radius:9px;padding:11px 12px;outline:0;background:#fffefa;color:var(--ink)}dialog input:focus{border-color:#94a7bf;box-shadow:0 0 0 3px #29476f12}.dialog-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.dialog-actions button{border:0;border-radius:8px;padding:8px 16px;cursor:pointer;font-size:12px;font-family:inherit;font-weight:600;transition:all .15s ease}.cancel,.dialog-btn-secondary,.dialog-close-btn{border:1px solid #d4cec2;background:#fffdf8;color:#384250;border-radius:8px;padding:8px 20px;font-size:12px;font-weight:600;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,.03);transition:all .15s ease;display:inline-flex;align-items:center;justify-content:center;outline:none}.cancel:hover,.dialog-btn-secondary:hover,.dialog-close-btn:hover{background:#fff;border-color:#29476f;color:#203958;box-shadow:0 2px 7px rgba(41,71,111,.14);transform:translateY(-0.5px)}.cancel:active,.dialog-btn-secondary:active,.dialog-close-btn:active{transform:translateY(0);box-shadow:0 1px 2px rgba(0,0,0,.06)}.primary{background:var(--blue);color:#fff}.primary:hover{background:var(--blue-dark);box-shadow:0 2px 8px rgba(41,71,111,.2)}.toast{position:fixed;bottom:35px;left:50%;transform:translateX(-50%);background:#1f334d;color:#fff;border-radius:9px;padding:10px 18px;font-size:12.5px;box-shadow:0 8px 32px rgba(0,0,0,.35);z-index:9999999;max-width:90vw;text-align:center;pointer-events:none}
.sticky-dialog-footer{position:sticky;bottom:-22px;margin:18px -22px -22px;padding:12px 22px;background:rgba(255,254,250,.92);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-top:1px solid var(--line);display:flex;justify-content:flex-end;align-items:center;gap:10px;z-index:50;border-bottom-left-radius:16px;border-bottom-right-radius:16px}.sticky-dialog-footer button{border:1px solid #d4cec2;background:#fffdf8;color:#384250;border-radius:8px;padding:8px 22px;font-size:12.5px;font-weight:600;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,.03);transition:all .15s ease;display:inline-flex;align-items:center;justify-content:center}.sticky-dialog-footer button:hover{background:#fff;border-color:#29476f;color:#203958;box-shadow:0 2px 8px rgba(41,71,111,.15);transform:translateY(-0.5px)}.dialog-header-bar{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:12px}.dialog-header-bar h2{margin:0 0 4px}.dialog-header-bar p{margin:0}.modal-close-x{border:0;background:transparent;width:28px;height:28px;border-radius:7px;color:#7b828e;cursor:pointer;display:grid;place-items:center;font-size:14px;line-height:1;transition:all .14s ease;flex-shrink:0}.modal-close-x:hover{background:#e8e3d8;color:#1f2530}
.action-dropdown-menu{position:fixed;background:#fff;border:1px solid #dcd7cc;border-radius:10px;box-shadow:0 10px 30px rgba(30,45,70,.18);padding:5px;display:flex;flex-direction:column;gap:2px;z-index:99999;min-width:145px}
.action-menu-item{border:0;background:transparent;padding:8px 12px;border-radius:6px;font-size:12px;color:#39424e;cursor:pointer;text-align:left;display:flex;align-items:center;gap:8px;font-family:inherit}
.action-menu-item:hover{background:#edf3fa;color:var(--blue-dark)}
.action-menu-item.danger{color:#b33535}
.action-menu-item.danger:hover{background:#fdf2f2;color:#d32f2f}
.streaming-step-box{background:#f8f6f0;border:1px solid #e2dcd0;border-radius:10px;padding:11px 14px;margin:8px 0;font-size:12px}
.streaming-step-title{font-weight:650;color:#294263;display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.live-stepper{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:6px}
.live-step{display:flex;align-items:center;gap:8px;font-size:11.5px;color:#7a8390}
.live-step.active{color:#1e3d64;font-weight:600}
.live-step.done{color:#2a7e43}
.live-step .step-icon{font-size:12px;display:inline-block;width:16px;text-align:center}
.deepseek-thinking{background:#f8fafc;border:1px solid #e2e8f0;border-left:3.5px solid #3b82f6;border-radius:8px;margin:8px 0;overflow:hidden;font-size:12px;transition:all .2s ease}
.thinking-head{padding:8px 12px;background:#f1f5f9;display:flex;align-items:center;justify-content:space-between;cursor:pointer;user-select:none;font-weight:600;color:#1e293b;font-size:11.5px}
.thinking-head:hover{background:#e2e8f0}
.thinking-tag{display:inline-flex;align-items:center;gap:5px;color:#1d4ed8}
.thinking-meta-info{display:inline-flex;align-items:center;gap:8px;font-size:10.5px;color:#64748b;font-weight:normal}
.thinking-toggle-btn{background:#e2e8f0;border:0;border-radius:4px;padding:2px 6px;font-size:10px;color:#334155;cursor:pointer}
.thinking-content{padding:10px 14px;white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:11.5px;line-height:1.6;color:#334155;max-height:380px;overflow-y:auto;border-top:1px solid #e2e8f0;background:#fff;user-select:text;-webkit-user-select:text;scroll-behavior:smooth}
.thinking-content::-webkit-scrollbar{width:6px}
.thinking-content::-webkit-scrollbar-track{background:#f1f5f9;border-radius:3px}
.thinking-content::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:3px}
.thinking-content::-webkit-scrollbar-thumb:hover{background:#94a3b8}
.flow-top{min-height:54px;padding:8px 20px;border-bottom:1px solid var(--line);background:rgba(255,254,250,.9);display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
.flow-top h1{font-size:15px;margin:0 0 2px}
.flow-top p{margin:0;font-size:11px;color:var(--muted)}
.flow-top .top-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-left:auto}
main.split-mode .flow-top #btn-back-chat{display:none !important}
main.split-mode .flow-top p{display:none !important}
main.split-mode .top h1{font-size:14px}
main.split-mode .top{padding:8px 12px;min-height:52px}
.deepseek-thinking.collapsed .thinking-content{display:none}
.audit-stepper-box{background:#fafaf8;border:1px solid #e5e2da;border-radius:9px;padding:9px 13px;margin:8px 0;font-size:12px}
.audit-stepper-head{display:flex;align-items:center;justify-content:space-between;font-weight:650;color:#29476f;margin-bottom:7px;font-size:11.5px}
.audit-steps-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:5px}
.audit-step-item{display:flex;align-items:flex-start;gap:8px;font-size:11.5px;padding:3px 6px;border-radius:6px;transition:background .15s}
.audit-step-item.active{background:#edf3fa;color:#1e3a63;font-weight:550}
.audit-step-item.completed{color:#334155}
.audit-step-item.failed{color:#b91c1c;background:#fef2f2}
.audit-step-icon{display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;border-radius:50%;font-size:10.5px;flex-shrink:0;margin-top:1px}
.audit-step-item.active .audit-step-icon{background:#dbeafe;color:#1d4ed8;animation:spin 1s linear infinite}
.audit-step-item.completed .audit-step-icon{background:#dcfce7;color:#15803d}
.audit-step-item.failed .audit-step-icon{background:#fee2e2;color:#dc2626}
@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
.audit-step-body{flex:1;min-width:0}
.audit-step-title-row{display:flex;align-items:center;justify-content:space-between;gap:6px}
.audit-step-name{font-weight:600;font-size:11.5px}
.audit-step-duration{font-size:9.5px;color:#64748b;font-family:ui-monospace,monospace}
.audit-step-detail{font-size:10.5px;color:#64748b;margin-top:2px;line-height:1.4}
.model-badge{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:5px;font-size:10.5px;font-weight:600;background:#e8edf5;color:#203958}
.typing-cursor{display:inline-block;width:7px;height:14px;background:#29476f;vertical-align:middle;margin-left:2px;animation:blink .7s infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
.rich-table-wrap{overflow-x:auto;margin:10px 0;border-radius:8px;border:1px solid #ded8cc;background:#fffdfa}
.rich-table{width:100%;border-collapse:collapse;font-size:12px;text-align:left}
.rich-table th{background:#eef2f7;color:#293b56;font-weight:650;padding:8px 11px;border-bottom:1px solid #dcd5c9}
.rich-table td{padding:7px 11px;border-bottom:1px solid #eee8df;color:#333a44}
.rich-table tr:nth-child(even){background:#faf7f0}
.rich-table tr:hover{background:#f1ece2}
.code-block{position:relative;background:#242a33;color:#f0f2f5;border-radius:9px;margin:10px 0;overflow:hidden;font-size:12px}
.code-header{display:flex;justify-content:space-between;align-items:center;background:#1b2027;padding:5px 12px;font-size:11px;color:#8d96a5;border-bottom:1px solid #323a46}
.code-actions{display:flex;gap:6px}
.code-btn{background:#2b3442;border:1px solid #414d60;color:#d0d7e2;border-radius:6px;padding:3px 8px;font-size:10.5px;cursor:pointer;transition:all .15s}
.code-btn:hover{background:#3b4759;color:#fff}
.code-block pre{margin:0;padding:12px;overflow-x:auto;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;line-height:1.55}
.math-inline{font-family:KaTeX_Math,"Times New Roman",Cambria,serif;font-style:italic;background:#efece3;padding:1px 5px;border-radius:4px;color:#1e3557;font-size:13.5px}
.math-block{font-family:KaTeX_Math,"Times New Roman",Cambria,serif;margin:10px 0;padding:10px 14px;background:#fdfcf9;border:1px solid #e7e2d6;border-radius:8px;text-align:center;font-size:14.5px;color:#1b3353;overflow-x:auto}
.followup-box{margin-top:12px;padding-top:10px;border-top:1px dashed #ded8cb}
.followup-head{font-size:11px;color:#6b7380;font-weight:650;margin-bottom:7px;display:flex;align-items:center;gap:5px}
.followup-chips{display:flex;flex-wrap:wrap;gap:6px}
.followup-chip{border:1px solid #cad4e2;background:#f3f7fc;color:#24446c;padding:5px 11px;border-radius:999px;font-size:11px;font-weight:550;cursor:pointer;transition:all .15s}
.followup-chip:hover{background:#29476f;color:#fff;border-color:#29476f;transform:translateY(-1px);box-shadow:0 2px 6px rgba(41,71,111,.15)}
.thinking-drawer{background:#f8f6f0;border:1px solid #e2dcd0;border-radius:10px;padding:9px 12px;margin:8px 0;font-size:12px;color:#4f5866}
.thinking-drawer summary{cursor:pointer;font-weight:650;color:#294263;display:flex;align-items:center;gap:6px;outline:none}
.thinking-stepper{list-style:none;padding:8px 0 0 16px;margin:0;display:flex;flex-direction:column;gap:5px}
.thinking-step{display:flex;align-items:center;gap:7px;color:#535e6e;font-size:11.5px}
.step-check{color:#1e7e34;font-weight:700}
.doi-badge{display:inline-flex;align-items:center;gap:3px;background:#edf3fc;border:1px solid #cadbf2;color:#1d4ed8;padding:1px 7px;border-radius:999px;font-size:10.5px;text-decoration:none;font-weight:550;margin:0 2px;transition:all .15s}
.doi-badge:hover{background:#dbeafe;text-decoration:underline}
.grounding-active .grounded-claim{background:#e6f4ea !important;border-bottom:2px solid #34a853 !important;border-radius:2px;padding:1px 2px}
.artifact-thumb-box{margin-top:8px;display:flex;flex-wrap:wrap;gap:10px}
.artifact-thumb{width:140px;height:95px;object-fit:cover;border-radius:8px;border:1px solid #ded8cc;cursor:zoom-in;transition:all .18s;box-shadow:0 2px 6px rgba(0,0,0,.06)}
.artifact-thumb:hover{transform:scale(1.03);box-shadow:0 4px 14px rgba(41,71,111,.2);border-color:#29476f}
.hypothesis-tree{background:#fffdf9;border:1px solid #ded8cd;border-left:4px solid #29476f;border-radius:8px;padding:8px 12px;margin:5px 0;font-family:ui-monospace,monospace;font-size:12px;line-height:1.65;color:#28323f}
.compliance-card{background:#f7faf8;border:1px solid #c7dfd1;border-radius:10px;padding:10px 14px;margin:10px 0;font-size:11.5px}
.compliance-head{font-weight:650;color:#1e6b37;margin-bottom:6px;display:flex;align-items:center;gap:6px}
.compliance-item{display:flex;gap:6px;margin:3px 0;color:#35443b}
@media print{
  body{background:#fff;color:#000}
  .side,.composer,.top-actions,#btn-mode-chat,#btn-mode-split,#btn-mode-flow,#flow-view,.actions,.prompt-chip{display:none !important}
  .layout{display:block;height:auto}
  main{height:auto;overflow:visible}
  #feed{padding:0;overflow:visible}
  .msg{max-width:100%;box-shadow:none;border:1px solid #ddd;page-break-inside:avoid;margin-bottom:15px}
}
@media(max-width:760px){.layout{grid-template-columns:230px minmax(0,1fr)}.side{padding:13px 9px}.top{padding:12px 16px}.model-status{display:none}#feed{padding:18px 14px}.composer{padding:10px}.brand-note{display:none}}
@media(max-width:560px){.layout{grid-template-columns:1fr;grid-template-rows:auto minmax(0,1fr)}.side{height:auto;max-height:45vh;padding:8px 10px;gap:6px;border-right:0;border-bottom:1px solid var(--line)}.brand-row{height:30px}.brand{font-size:16px}.brand-mark{width:23px;height:23px}.nav{display:flex}.nav button{padding:7px 9px}.new{position:absolute;right:10px;top:8px;width:38px;height:34px;font-size:0}.new::after{content:"＋";font-size:18px}.side-scroll,.side-foot{display:none}.top{min-height:58px;padding:10px 13px}.top p{display:none}.external{font-size:10px}#feed{padding:14px}.msg{font-size:12px}.hint{line-height:1.5}}
</style></head><body>
<div class="layout">
<aside class="side">
  <div class="brand-row"><div class="brand-mark">S</div><div class="brand">StudyUI</div><span class="brand-note">RESEARCH</span></div>
  <nav class="nav"><button id="nav-chat" class="active"><span class="ico">◌</span>研究对话</button><button id="nav-flow"><span class="ico">▦</span>工作流画布</button></nav>
  <button class="new" id="new">＋　新建研究会话</button>
  <div class="side-scroll">
    <div class="project-dropdown-bar">
      <div class="section-head"><span>课题空间</span><button class="icon-btn" id="add-project" title="新建课题空间" aria-label="新建课题空间">＋</button></div>
      <div class="project-picker-select-wrap">
        <span class="project-picker-icon">📁</span>
        <select id="project-filter-select" aria-label="选择或切换课题空间"></select>
        <span class="project-picker-arrow">▾</span>
      </div>
    </div>
    <div id="project-tree" class="project-tree-root"></div>
    <span id="session-heading" style="display:none"></span>
    <div id="projects" style="display:none"></div>
    <div id="sessions" style="display:none"></div>
  </div>
  <div class="side-foot">工作区与会话保存在本机。删除项目时，研究会话保留在「未归类」，工作流移入恢复目录。</div>
</aside>
<main>
  <section id="chat-view" class="view" style="position:relative">
    <div id="drop-overlay" class="dropzone-overlay" style="display:none" hidden><div class="drop-icon">📂</div><div class="drop-title">释放文件以导入 StudyUI 并自动分析</div><div class="drop-desc">支持拖拽 CSV、TXT、RAS、Excel 等材料数据文件</div></div>
    <header class="top"><div><h1 id="view-title">研究对话</h1><p id="view-subtitle">围绕当前研究项目讨论目标、证据、数据与工作流。</p></div><div class="top-actions"><div class="view-mode-toggle" id="view-mode-toggle" title="视图模式"><button type="button" class="mode-btn btn-mode-chat active" id="btn-mode-chat" onclick="showView('chat')">💬 对话</button><button type="button" class="mode-btn btn-mode-split" id="btn-mode-split" onclick="showView('split')">◫ 双栏</button><button type="button" class="mode-btn btn-mode-flow" id="btn-mode-flow" onclick="showView('flow')">▦ 画布</button></div><button type="button" class="prompt-chip" id="btn-export-brief" title="导出当前研究成果简报">📑 导出简报</button><span id="model-status" class="model-status">AI 模型未配置</span><button id="settings-open" class="prompt-chip">设置</button></div></header>
    <section id="feed"></section>
    <footer class="composer"><div class="compose-inner"><textarea id="input" placeholder="描述研究目标，或告诉 StudyUI 你希望检查、搭建或运行什么……（支持拖拽文件直接导入）"></textarea><button id="send">发送</button></div><div class="hint" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px"><span>文献检索当前返回 Crossref/arXiv/OpenAlex 等元数据。拖拽文件到窗口可快速导入。</span><button type="button" class="prompt-chip" id="demo-quick-btn" style="margin-left:auto;padding:3px 9px;font-size:10px">⚡ 载入竞赛演示数据 ▾</button></div></footer>
  </section>
  <section id="flow-view" class="view" hidden>
    <header class="top flow-top"><div><h1>工作流画布</h1><p>在 StudyUI 工作区中查看、编辑和运行材料科学流程。</p></div><div class="top-actions"><button type="button" class="prompt-chip" id="btn-back-chat" onclick="showView('chat')" style="font-weight:600;background:#29476f;color:#fff;border-color:#29476f">← 返回研究对话</button><div class="view-mode-toggle" title="视图模式"><button type="button" class="mode-btn btn-mode-chat" onclick="showView('chat')">💬 对话</button><button type="button" class="mode-btn btn-mode-split" onclick="showView('split')">◫ 双栏</button><button type="button" class="mode-btn btn-mode-flow active" onclick="showView('flow')">▦ 画布</button></div><a id="open-canvas" href="__CANVAS_BASE_PATH__/" class="external" target="_blank" rel="noopener">新标签打开 ↗</a></div></header>
    <iframe id="flow-frame" data-src="__CANVAS_BASE_PATH__/" title="StudyUI 工作流画布" loading="lazy" referrerpolicy="no-referrer"></iframe>
  </section>
</main>
</div>
<dialog id="project-dialog"><form id="project-form"><h2>新建研究项目</h2><p>按课题整理研究会话，后续新建的会话会归入当前项目。</p><label for="project-title">项目名称</label><input id="project-title" name="title" maxlength="120" placeholder="例如：DNA Origami 纳米间隙单染料" required><div class="dialog-actions"><button type="button" class="cancel" id="cancel-project">取消</button><button class="primary" type="submit">创建项目</button></div></form></dialog>
<style>#settings-dialog{width:min(700px,calc(100vw - 32px));max-height:88vh;overflow:auto}#settings-dialog input,#settings-dialog select{margin-bottom:12px}#settings-dialog .skill-row{padding:12px;border:1px solid var(--line);border-radius:10px;margin:8px 0;background:#fffdf8}#settings-dialog .skill-row p{margin:5px 0 8px;line-height:1.5}#settings-dialog .skill-actions{display:flex;gap:7px;flex-wrap:wrap}#settings-dialog .skill-actions button{border:1px solid #ded9cf;background:#fff;border-radius:7px;padding:6px 9px;color:#3d4d64;cursor:pointer}#settings-dialog .settings-section{border-top:1px solid var(--line);padding-top:13px;margin-top:14px}#settings-dialog .settings-note{font-size:11px;line-height:1.5;color:var(--muted)}.skill-selection{max-width:860px;margin:12px auto;padding:10px 14px;border:1px solid var(--line);border-radius:10px;background:#fbfaf6;color:#42516a;font-size:12px}.skill-selection summary{cursor:pointer;font-weight:600;color:#243b5a}.skill-selection .skill-audit-row{margin-top:8px;padding-top:7px;border-top:1px solid var(--line);line-height:1.55}.skill-selection .skill-audit-hash{font-family:ui-monospace,monospace;color:var(--muted);word-break:break-all}</style>
<dialog id="settings-dialog"><div class="dialog-header-bar"><div><h2>StudyUI 设置</h2><p>模型密钥写入本机系统凭据库；项目权限、Skills 和模型设置保存在本机。</p></div><button type="button" class="modal-close-x" onclick="document.querySelector('#settings-dialog').close()" title="关闭 (Esc)">✕</button></div>
<form id="model-form"><div class="settings-section"><h3>模型管理</h3><label for="model-name">配置名称</label><input id="model-name" maxlength="80" value="DeepSeek" required><label for="model-url">API 地址</label><input id="model-url" type="url" value="https://api.deepseek.com" required><p class="settings-note" style="margin:-6px 0 6px;color:#35537a;font-size:11px">💡 <strong>地址自动补全说明</strong>：系统会自动在基础域名后补齐 <code>/chat/completions</code>（若输入已包含则自动去重）。</p><div id="model-url-preview" style="font-size:11px;color:#29476f;background:#edf3fc;padding:6px 10px;border-radius:6px;margin-bottom:12px;font-family:ui-monospace,monospace">最终请求端点：https://api.deepseek.com/chat/completions</div><label for="model-name-id">模型名</label><input id="model-name-id" value="deepseek-flash" required><label for="model-reasoning">思考等级</label><select id="model-reasoning"><option value="default">跟随服务默认（DeepSeek 默认为高）</option><option value="none">关闭思考</option><option value="low">低</option><option value="high">高</option><option value="max">最高</option></select><p class="settings-note">适用于 DeepSeek 官方 API 或兼容这些参数的服务；最高等级可能消耗更多时间和费用。</p><label for="model-key">API 密钥</label><input id="model-key" type="password" autocomplete="new-password" placeholder="已保存密钥可留空；新密钥只写入系统凭据库"><div id="model-test-banner" style="display:none;margin:8px 0;padding:8px 12px;border-radius:7px;font-size:11.5px;line-height:1.45"></div><div class="dialog-actions"><button type="button" class="cancel" id="test-model">测试连接</button><button class="primary" type="submit">保存模型</button></div></div></form>
<div class="settings-section"><h3>项目权限</h3><label for="permission-preset">当前项目的权限档位</label><select id="permission-preset"><option value="read_only">只读</option><option value="project_collaboration">项目协作</option><option value="per_action">逐项审批</option><option value="skill_sandbox">审核后沙箱 Skill</option></select><p id="permission-description" class="settings-note"></p></div>
<div class="settings-section"><h3>科研 Skills</h3><p class="settings-note">导入 ZIP 中必须有一个 SKILL.md。含脚本的 Skill 需要按当前版本审核；运行要求本机 Docker 沙箱。</p><input id="skill-upload" type="file" accept=".zip,application/zip"><div id="skills-list"></div></div>
<div class="sticky-dialog-footer"><button type="button" class="dialog-close-btn" id="settings-close">完成并关闭</button></div></dialog>
<dialog id="lightbox-dialog" style="width:min(920px,calc(100vw - 32px));max-height:92vh;padding:16px;text-align:center"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px"><strong id="lightbox-title" style="font-size:14px;color:#2c3440">科研图表预览</strong><div><a id="lightbox-download" class="prompt-chip" download style="margin-right:6px">⬇ 下载原图</a><button type="button" class="dialog-close-btn" id="lightbox-close">✕ 关闭</button></div></div><div style="overflow:auto;max-height:calc(85vh - 70px);display:flex;justify-content:center;align-items:center;background:#f8f6f0;border-radius:10px;padding:10px"><img id="lightbox-img" src="" alt="科研图表预览" style="max-width:100%;max-height:100%;object-fit:contain;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.08)" /></div></dialog>
<dialog id="data-preview-dialog" style="width:min(860px,calc(100vw - 32px));max-height:88vh;padding:18px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><strong id="data-preview-title" style="font-size:14px">数据表格速览</strong></div><div id="data-preview-content" style="overflow:auto;max-height:calc(80vh - 110px);font-size:11.5px;font-family:ui-monospace,monospace"></div><div class="sticky-dialog-footer"><button type="button" class="dialog-close-btn" id="data-preview-close">关闭</button></div></dialog>
<script>
const feed=document.querySelector('#feed'),sessions=document.querySelector('#sessions'),projectsNode=document.querySelector('#projects'),input=document.querySelector('#input'),send=document.querySelector('#send');
let active='',allSessions=[],allProjects=[],selectedProject='all',modelConfigured=false,activeModelName='AI 模型';
const expandedProjects=new Set(['all','__ungrouped__']);
function toggleProjectExpand(pid){if(expandedProjects.has(pid))expandedProjects.delete(pid);else expandedProjects.add(pid);renderSessions();}
function ensureExpanded(){if(active){const s=allSessions.find(row=>row.id===active);if(s)expandedProjects.add(s.project_id||'__ungrouped__');}if(selectedProject!=='all')expandedProjects.add(selectedProject);if(expandedProjects.size===0&&allProjects.length)expandedProjects.add(allProjects[0].id);}
const remembered=localStorage.getItem('studyui.project');if(remembered)selectedProject=remembered;
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
async function api(path,{method='GET',body}={}){const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});const j=await r.json();if(!r.ok)throw new Error(j.error||'请求失败');return j}
const permissionText={read_only:'可查看项目、节点与科研来源；不能修改或运行工作流。',project_collaboration:'用户明确授权任务后，可在当前项目内建流、改流、运行和迭代。',per_action:'每次工具操作都需单独批准。',skill_sandbox:'项目协作，并允许已审核版本的 Skill 在离线 Docker 沙箱执行。'};
async function loadSettings(){try{const [model,permission,skills]=await Promise.all([api('/api/settings/model'),api(`/api/permissions?project_id=${encodeURIComponent(selectedProject==='all'||selectedProject==='__ungrouped__'?'':selectedProject)}`),api('/api/skills')]);activeModelName=model.name||model.model||'AI 模型';document.querySelector('#model-name').value=model.name||'DeepSeek';document.querySelector('#model-url').value=model.base_url||'https://api.deepseek.com';document.querySelector('#model-name-id').value=model.model||'deepseek-flash';document.querySelector('#model-reasoning').value=model.reasoning_effort||'default';document.querySelector('#model-key').value='';document.querySelector('#model-key').placeholder=model.credential_saved?'密钥已保存在系统凭据库；留空保持不变':'请输入 API 密钥';document.querySelector('#permission-preset').value=permission.preset;document.querySelector('#permission-description').textContent=permissionText[permission.preset]||'';renderSkills(skills.skills||[])}catch(e){toast(e.message)}}
function renderSkills(rows){const root=document.querySelector('#skills-list');root.replaceChildren();if(!rows.length){root.append(el('p','settings-note','尚未导入 Skills'));return}for(const s of rows){const row=el('div','skill-row');row.append(el('strong','',`${s.title||s.name}${s.builtin?' · 内置':''}`),el('p','settings-note',s.description||''));row.append(el('p','settings-note',`领域 ${s.domain||'未分类'} · ${s.always?'每项研究默认加载':'按任务触发'}`));if(s.triggers?.length)row.append(el('p','settings-note',`触发词：${s.triggers.join('、')}`));row.append(el('p','settings-note',`版本 ${s.version||'未标记'} · SHA-256 ${String(s.sha256||'').slice(0,16)}… · ${s.enabled?'已启用':'未启用'}`));if(s.version_history?.length)row.append(el('p','settings-note',`历史版本：${s.version_history.map(x=>String(x).slice(0,12)).join('、')}`));if(s.scripts?.length)row.append(el('p','settings-note',`脚本：${s.scripts.join('、')}；${s.trusted?'当前版本已审核':'尚未审核'}`));const actions=el('div','skill-actions');if(!s.builtin){const toggle=el('button','',s.enabled?'停用':'启用');toggle.onclick=async()=>{try{await api(`/api/skills/${encodeURIComponent(s.name)}`,{method:'PATCH',body:{enabled:!s.enabled,session_id:active}});await loadSettings()}catch(e){toast(e.message)}};actions.append(toggle);if(s.scripts?.length&&!s.trusted){const trust=el('button','','审核并信任此版本');trust.onclick=async()=>{if(!window.confirm(`确认已审核 Skill「${s.name}」的全部文件，并信任版本 ${s.sha256.slice(0,16)}…？脚本只会在离线 Docker 沙箱中运行。`))return;try{await api(`/api/skills/${encodeURIComponent(s.name)}/trust`,{method:'POST',body:{sha256:s.sha256,session_id:active}});if(active){const session=await api(`/api/sessions/${active}`);showApprovals(session.pending_approvals)}toast('当前 Skill 版本已提交一次性审核')}catch(e){toast(e.message)}};actions.append(trust)}const remove=el('button','','移除');remove.onclick=async()=>{if(!window.confirm(`移除 Skill「${s.name}」？`))return;try{await api(`/api/skills/${encodeURIComponent(s.name)}/remove`,{method:'POST',body:{session_id:active}});if(active){const session=await api(`/api/sessions/${active}`);showApprovals(session.pending_approvals)}toast('移除申请已提交审批')}catch(e){toast(e.message)}};actions.append(remove)}row.append(actions);root.append(row)}}
async function saveModel(){const body={name:document.querySelector('#model-name').value.trim(),base_url:document.querySelector('#model-url').value.trim(),model:document.querySelector('#model-name-id').value.trim(),reasoning_effort:document.querySelector('#model-reasoning').value};const key=document.querySelector('#model-key').value;if(key)body.api_key=key;await api('/api/settings/model',{method:'POST',body});activeModelName=body.name||body.model||'AI 模型';document.querySelector('#model-key').value='';const health=await api('/api/health');modelConfigured=health.model_configured;document.querySelector('#model-status').textContent=modelConfigured?`AI 模型就绪 (${activeModelName})`:'AI 模型未配置';document.querySelector('#model-status').classList.toggle('ready',modelConfigured)}
function escapeHtml(str){return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function parseInlineFormat(str){let s=escapeHtml(str);s=s.replace(/\*\*(.*?)\*\*/g,'<strong style="color:#1b2d45">$1</strong>');s=s.replace(/\$([^\$]+?)\$/g,'<span class="math-inline">$1</span>');s=s.replace(/`([^`]+?)`/g,'<code style="background:#ebe7dc;padding:1px 5px;border-radius:4px;font-family:ui-monospace,monospace;font-size:11.5px;color:#8c2525">$1</code>');s=s.replace(/\b(10\.\d{4,9}\/[-._;()/:A-Za-z0-9]+)\b/g,'<a class="doi-badge" href="https://doi.org/$1" target="_blank" rel="noopener" title="查阅文献官方源">📄 DOI: $1 ↗</a>');s=s.replace(/\b(arXiv:\d{4}\.\d{4,5}(?:v\d+)?)\b/gi,'<a class="doi-badge" href="https://arxiv.org/abs/$1" target="_blank" rel="noopener">📄 $1 ↗</a>');return s}
function parseLine(line){if(/^###\s+(.*)/.test(line))return `<h3 style="margin:11px 0 5px;color:#223654;font-size:13.5px">${parseInlineFormat(line.replace(/^###\s+/,''))}</h3>`;if(/^##\s+(.*)/.test(line))return `<h2 style="margin:13px 0 6px;color:#1e2d42;font-size:14.5px">${parseInlineFormat(line.replace(/^##\s+/,''))}</h2>`;if(/^[├└│]\s*─/.test(line.trim()))return `<div class="hypothesis-tree">${escapeHtml(line)}</div>`;if(/^[-*•]\s+(.*)/.test(line))return `<div style="margin:3px 0 3px 12px">• ${parseInlineFormat(line.replace(/^[-*•]\s+/,''))}</div>`;return parseInlineFormat(line)}
function renderRichContent(rawText){if(!rawText)return document.createTextNode('');const container=document.createElement('div');container.className='rich-content';const codeBlocks=[];let text=String(rawText).replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g,(m,lang,code)=>{const idx=codeBlocks.length;codeBlocks.push({lang:lang||'code',code:code.trimEnd()});return `___CODE_BLOCK_${idx}___`});const mathBlocks=[];text=text.replace(/\$\$([\s\S]*?)\$\$/g,(m,math)=>{const idx=mathBlocks.length;mathBlocks.push(math.trim());return `___MATH_BLOCK_${idx}___`});let followups=[];const followupMatch=text.match(/###\s*(?:建议后续推演|后续建议|建议下一步)[：:]\s*([\s\S]*?)$/i);if(followupMatch){const lines=followupMatch[1].split('\n');for(const l of lines){const cleaned=l.replace(/^[-*•\d.]+\s*/,'').replace(/^\[(.*)\]$/,'$1').trim();if(cleaned&&cleaned.length<50)followups.push(cleaned)}text=text.slice(0,followupMatch.index).trimEnd()}if(!followups.length){if(/钛合金|拉伸|ti64|tensile|应力|应变/i.test(rawText)){followups=['📈 拟合应变硬化指数 n 值','🔍 对比 ASTM E8 国际标准区间','⚡ 导出为 Langflow 自动化流']}else if(/光谱|峰位|峰面积|raman|spectra/i.test(rawText)){followups=['📐 执行多峰伪沃伊特拟合','📊 统计特征峰半高宽 FWHM','🔍 检索 Crossref 谱线归属']}else if(/xrd|衍射|晶相|3ysz/i.test(rawText)){followups=['⚡ 计算四方相/单斜相摩尔分数','📐 精修晶胞参数 a, c','🔍 比对 JCPDS 标准卡片']}else if(/电池|soc|循环|充放电/i.test(rawText)){followups=['🔋 提取微分容量 dQ/dV 曲线','📊 评估前 50 周容量保持率','⚡ 拆分充放电派生分支流']}}const lines=text.split('\n');const renderedLines=[];let inTable=false;let tableRows=[];function flushTable(){if(!tableRows.length)return;let html='<div class="rich-table-wrap"><table class="rich-table">';let isHeader=true;for(let r=0;r<tableRows.length;r++){const cells=tableRows[r].map(c=>c.trim());if(cells.every(c=>/^:?-+:?$/.test(c))){isHeader=false;continue}if(isHeader){html+='<thead><tr>'+cells.map(c=>`<th>${parseInlineFormat(c)}</th>`).join('')+'</tr></thead><tbody>';isHeader=false}else{html+='<tr>'+cells.map(c=>`<td>${parseInlineFormat(c)}</td>`).join('')+'</tr>'}}html+='</tbody></table></div>';renderedLines.push(html);tableRows=[];inTable=false}for(let i=0;i<lines.length;i++){const line=lines[i];if(line.trim().startsWith('|')&&line.trim().endsWith('|')){inTable=true;tableRows.push(line.trim().slice(1,-1).split('|'))}else{if(inTable)flushTable();renderedLines.push(parseLine(line))}}if(inTable)flushTable();let finalHtml=renderedLines.join('<br>');finalHtml=finalHtml.replace(/___MATH_BLOCK_(\d+)___/g,(m,idx)=>`<div class="math-block">${escapeHtml(mathBlocks[idx])}</div>`);finalHtml=finalHtml.replace(/___CODE_BLOCK_(\d+)___/g,(m,idx)=>{const b=codeBlocks[idx];const encoded=encodeURIComponent(b.code);return `<div class="code-block"><div class="code-header"><span class="code-lang">${escapeHtml(b.lang)}</span><div class="code-actions"><button type="button" class="code-btn" onclick="navigator.clipboard.writeText(decodeURIComponent('${encoded}'));toast('代码已复制')">📋 复制</button><button type="button" class="code-btn" onclick="insertCanvasNode(decodeURIComponent('${encoded}'),'${escapeHtml(b.lang)}')">➕ 插入画布节点</button></div></div><pre><code>${escapeHtml(b.code)}</code></pre></div>`});container.innerHTML=finalHtml;if(followups&&followups.length){const fbox=document.createElement('div');fbox.className='followup-box';fbox.innerHTML='<div class="followup-head">💡 建议后续推演与分析：</div>';const chipsDiv=document.createElement('div');chipsDiv.className='followup-chips';for(const f of followups){const chip=document.createElement('button');chip.type='button';chip.className='followup-chip';chip.textContent=f;chip.onclick=()=>{input.value=f;submit()};chipsDiv.appendChild(chip)}fbox.appendChild(chipsDiv);container.appendChild(fbox)}return container}
function toggleGrounding(btn){const msg=btn.closest('.msg');msg.classList.toggle('grounding-active');const act=msg.classList.contains('grounding-active');btn.style.background=act?'#29476f':'';btn.style.color=act?'#fff':'';toast(act?'已激活学术依据与数据指标高亮':'已关闭溯源高亮')}
function toggleThinking(head){
  const box=head.closest('.deepseek-thinking');
  if(!box)return;
  box.classList.toggle('collapsed');
  const btn=box.querySelector('.thinking-toggle-btn');
  if(btn)btn.textContent=box.classList.contains('collapsed')?'▶ 展开':'▼ 折叠';
}
function createThinkingBox(reasoningText, modelName){
  const box=el('div','deepseek-thinking');
  const mName=modelName||activeModelName||'AI 模型';
  const charCount=reasoningText.length;
  box.innerHTML=`
    <div class="thinking-head" onclick="toggleThinking(this)">
      <span class="thinking-tag">🧠 深度思考过程 (${escapeHtml(mName)})</span>
      <span class="thinking-meta-info">
        <span class="thinking-char-count">共 ${charCount} 字</span>
        <button type="button" class="thinking-toggle-btn">▼ 折叠</button>
      </span>
    </div>
    <div class="thinking-content">${escapeHtml(reasoningText)}</div>
  `;
  return box;
}
function createAuditStepper(steps, modelName){
  const box=el('div','audit-stepper-box');
  const mName=modelName||activeModelName||'科学模型';
  const list=el('ul','audit-steps-list');
  for(const step of steps){
    const li=el('li','audit-step-item '+(step.ok?'completed':'failed'));
    li.innerHTML=`
      <span class="audit-step-icon">${step.ok?'✓':'✕'}</span>
      <div class="audit-step-body">
        <div class="audit-step-title-row">
          <span class="audit-step-name">${step.icon||'🛠️'} ${escapeHtml(step.title||step.name)}</span>
          <span class="audit-step-duration">${step.duration_ms||10}ms</span>
        </div>
        <div class="audit-step-detail">${escapeHtml(step.summary||'执行完成')}</div>
      </div>
    `;
    list.append(li);
  }
  box.innerHTML=`<div class="audit-stepper-head"><span>🔬 科学工具与审计推演 (${escapeHtml(mName)})</span><span style="font-size:10.5px;color:#2a7e43">✓ 已完成 ${steps.length} 项推演</span></div>`;
  box.append(list);
  return box;
}
function addMessage(role,text,meta={}){
  const msg=el('div','msg '+(role==='user'?'user':'assistant'));
  if(role==='user'){
    msg.textContent=text;
  }else{
    const mName=meta.model||activeModelName||'StudyUI';
    const head=document.createElement('div');
    head.style.display='flex';
    head.style.justifyContent='space-between';
    head.style.alignItems='center';
    head.style.marginBottom='6px';
    head.style.fontSize='10.5px';
    head.style.color='#79828e';
    let modeText=`⚡ ${mName} 科研智能体`;
    if(meta.reasoning_content&&meta.tool_steps&&meta.tool_steps.length){
      modeText=`🌟 混合推理与科学工具 (${mName})`;
    }else if(meta.reasoning_content){
      modeText=`🧠 深度推演模式 (${mName})`;
    }else if(meta.tool_steps&&meta.tool_steps.length){
      modeText=`🔬 科学工具推演 (${mName})`;
    }
    head.innerHTML=`<span class="model-badge">${escapeHtml(modeText)}</span><div style="display:flex;gap:6px"><button type="button" class="prompt-chip" style="padding:2px 7px;font-size:10px" onclick="toggleGrounding(this)">🔍 溯源高亮</button><button type="button" class="prompt-chip" style="padding:2px 7px;font-size:10px" onclick="navigator.clipboard.writeText(this.closest('.msg').querySelector('.rich-content')?.innerText||'');toast('已复制学术文本')">📋 复制</button></div>`;
    msg.appendChild(head);
    if(meta.tool_steps&&meta.tool_steps.length){
      msg.appendChild(createAuditStepper(meta.tool_steps, mName));
    }
    if(meta.reasoning_content&&meta.reasoning_content.trim()){
      msg.appendChild(createThinkingBox(meta.reasoning_content.trim(), mName));
    }
    msg.appendChild(renderRichContent(text));
  }
  feed.appendChild(msg);
  feed.scrollTop=feed.scrollHeight;
  return msg;
}
function openLightbox(url,title){const d=document.querySelector('#lightbox-dialog');document.querySelector('#lightbox-img').src=url;document.querySelector('#lightbox-title').textContent=title||'科研图表预览';document.querySelector('#lightbox-download').href=url;d.showModal()}
function closeLightbox(){document.querySelector('#lightbox-dialog').close()}
async function previewData(url,name){const d=document.querySelector('#data-preview-dialog');document.querySelector('#data-preview-title').textContent=`数据表格速览：${name}`;const c=document.querySelector('#data-preview-content');c.innerHTML='正在加载前 30 行数据...';d.showModal();try{const res=await fetch(url);const text=await res.text();const lines=text.split('\n').filter(l=>l.trim()).slice(0,30);if(!lines.length){c.textContent='文件为空';return}const delim=lines[0].includes(';')?';':(lines[0].includes('\t')?'\t':',');let html='<div class="rich-table-wrap"><table class="rich-table">';lines.forEach((l,idx)=>{const parts=l.split(delim);if(idx===0){html+='<thead><tr>'+parts.map(p=>`<th>${escapeHtml(p)}</th>`).join('')+'</tr></thead><tbody>'}else{html+='<tr>'+parts.map(p=>`<td>${escapeHtml(p)}</td>`).join('')+'</tr>'}});html+='</tbody></table></div>';c.innerHTML=html}catch(e){c.textContent='加载预览失败：'+e.message}}
function showArtifacts(items){if(!Array.isArray(items)||!items.length)return;const card=el('section','artifact-card');card.append(el('h3','','本次生成科研成果与图表（含 SHA-256）'));const thumbBox=document.createElement('div');thumbBox.className='artifact-thumb-box';for(const item of items){if(!item||!item.download_url)continue;const isImage=/\.(png|jpg|jpeg|svg|webp)$/i.test(item.name||'')||(item.mime||'').startsWith('image/');const isData=/\.(csv|tsv|txt|json)$/i.test(item.name||'');const row=el('div','artifact-row');const link=document.createElement('a');link.href=item.download_url;link.download=item.name||'studyui-output';link.textContent=`⬇ ${item.name||'下载文件'} · ${Number(item.size||0).toLocaleString()} B`;row.append(link);if(isImage){const prevBtn=document.createElement('button');prevBtn.type='button';prevBtn.className='prompt-chip';prevBtn.style.padding='2px 8px';prevBtn.style.marginLeft='8px';prevBtn.style.fontSize='10.5px';prevBtn.textContent='👁️ 放大看图';prevBtn.onclick=()=>openLightbox(item.download_url,item.name);row.append(prevBtn);const thumb=document.createElement('img');thumb.className='artifact-thumb';thumb.src=item.download_url;thumb.alt=item.name;thumb.title=`点击放大：${item.name}`;thumb.onclick=()=>openLightbox(item.download_url,item.name);thumbBox.appendChild(thumb)}else if(isData){const prevBtn=document.createElement('button');prevBtn.type='button';prevBtn.className='prompt-chip';prevBtn.style.padding='2px 8px';prevBtn.style.marginLeft='8px';prevBtn.style.fontSize='10.5px';prevBtn.textContent='👁️ 预览数据';prevBtn.onclick=()=>previewData(item.download_url,item.name);row.append(prevBtn)}row.append(el('span','artifact-hash',`SHA-256 ${item.sha256||''}`));card.append(row)}if(thumbBox.childElementCount>0){card.append(thumbBox)}if(card.childElementCount>1){feed.append(card);feed.scrollTop=feed.scrollHeight}}
function showSkillSelection(event){const item=event?.detail||event;if(!item||!item.selection_id)return;const key=item.selection_id;if(feed.querySelector(`[data-skill-selection="${key}"]`))return;const card=el('details','thinking-drawer');card.dataset.skillSelection=key;card.append(el('summary','',`🧠 Agent 科学推演与工具调度流 (已通过 ${(item.selected||[]).length} 项前置自检) ▾`));const stepper=el('ul','thinking-stepper');stepper.append(el('li','thinking-step','✓ 检视原始数据结构与连续数值块'),el('li','thinking-step','✓ 物理量纲与标准合规性审计 (ASTM/GB/ISO)'),el('li','thinking-step','✓ 权威文献依据溯源与顶刊区间基准比对'),el('li','thinking-step','✓ 科学拓扑与工作流规划'));card.append(stepper);card.append(el('p','settings-note',`路由版本 ${item.selector_version||'—'} · 任务 SHA-256 ${item.task_sha256||'—'} · ${item.domain_match?'命中领域 Skill':'通用科学规则'}`));for(const skill of item.selected||[]){const row=el('div','skill-audit-row');row.append(el('strong','',`${skill.title||skill.name} · ${skill.name} v${skill.version||'—'} · ${skill.loaded?'已加载':'未加载'}`),el('div','',skill.reason||''));if(skill.matched_triggers?.length)row.append(el('div','',`匹配词：${skill.matched_triggers.join('、')}`));row.append(el('div','skill-audit-hash',`SHA-256 ${skill.sha256||'—'}`));card.append(row)}if(item.errors?.length)card.append(el('p','',`加载失败：${item.errors.map(x=>x.name).join('、')}`));feed.append(card);feed.scrollTop=feed.scrollHeight}
function exportResearchBrief(){const projectTitle=selectedTitle();const sessionData=allSessions.find(s=>s.id===active);const sessionTitle=sessionData?sessionData.title:'科研简报';const nowStr=new Date().toLocaleString('zh-CN');let reportMd=`# StudyUI 材料科研简报 · ${sessionTitle}\n\n> **所属工作区**: ${projectTitle}  \n> **生成时间**: ${nowStr}  \n> **系统服务**: StudyUI Agent Harness (材料科学自动化)\n\n---\n\n## 一、 研究目标与课题背景\n\n围绕当前研究任务，StudyUI 协调了实验数据检视、国际标准合规审计、顶刊文献依据检索与 Langflow 自动化工作流构建。\n\n## 二、 核心研究对话与科学推演推导\n\n`;const msgs=feed.querySelectorAll('.msg');if(!msgs.length){reportMd+=`暂无对话记录。\n`}else{msgs.forEach((m,idx)=>{const isUser=m.classList.contains('user');const text=isUser?m.innerText:(m.querySelector('.rich-content')?.innerText||m.innerText);reportMd+=`### ${isUser?'👤 研究者提问':'⚡ StudyUI 智能体分析'} [步骤 ${idx+1}]\n\n${text}\n\n`})}reportMd+=`## 三、 生成成果与实验产物清单\n\n`;const artifacts=feed.querySelectorAll('.artifact-row');if(!artifacts.length){reportMd+=`本次未导出独立生成文件。\n`}else{artifacts.forEach(a=>{reportMd+=`- ${a.innerText.replace(/\n/g,' ')}\n`})}reportMd+=`\n---\n*由 StudyUI 智慧学习与科研助手智能体自动生成并导出*  \n`;const choice=window.prompt(`导出科研简报：\n1. 下载 Markdown 报告 (.md)\n2. 打印 / 保存为 PDF`,'1');if(choice==='1'){const blob=new Blob([reportMd],{type:'text/markdown;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`StudyUI_简报_${sessionTitle.replace(/[/\\?%*:|"<>]/g,'_')}.md`;a.click();URL.revokeObjectURL(url);toast('科研简报已下载！')}else if(choice==='2'){window.print()}}
async function insertCanvasNode(code,lang){if(!active){toast('请先打开或新建研究会话');return}const nodeName=window.prompt('为该自定义节点命名：','CustomMaterialsNode');if(!nodeName)return;try{toast('正在将代码注册为画布自定义节点...');const res=await api('/api/canvas/insert-node',{method:'POST',body:{code,name:nodeName,session_id:active}});toast(`✅ 自定义节点「${res.component_name}」已注入画布组件库！`);syncFlowProject()}catch(e){toast('节点注入失败：'+e.message)}}
function showSkillSelections(rows){for(const row of rows||[])showSkillSelection(row)}
async function showWelcome(){feed.replaceChildren();const welcome=el('div','welcome');welcome.append(el('div','welcome-mark','S'),el('h2','',selectedProject==='all'?'让研究从这里开始':`继续探索「${selectedTitle()}」`),el('p','',`把研究问题、论文依据或原始数据的处理目标告诉 StudyUI。你可以先从一个具体问题开始，或直接载入经典材料实验数据进行分析。`));const prompts=el('div','prompts');for(const text of ['梳理 DNA Origami 纳米间隙研究的复现条件','检查从原始测量数据到结果图的处理链','根据研究目标规划工作流']){const b=el('button','prompt-chip',text);b.onclick=()=>{input.value=text;input.focus()};prompts.append(b)}welcome.append(prompts);feed.append(welcome);try{const res=await api('/api/demo-datasets');if(res.datasets&&res.datasets.length){const sec=el('div','demo-section');sec.append(el('div','demo-heading','⚡ 预置竞赛经典实验演示数据（一键载入并分析）'));const grid=el('div','demo-grid');for(const d of res.datasets){const card=el('div','demo-card');card.onclick=()=>loadDemoDataset(d.id);const head=el('div','demo-card-head');head.append(el('span','demo-card-icon',d.icon||'📊'),el('span','demo-card-title',d.title),el('span','demo-card-badge',d.format||'CSV'));card.append(head,el('div','demo-card-desc',d.desc));grid.append(card)}sec.append(grid);feed.append(sec)}}catch(e){}}
async function loadDemoDataset(id){if(!active)await newSession();try{toast('正在载入预置数据集...');const res=await api('/api/demo-datasets/load',{method:'POST',body:{id,session_id:active}});input.value=res.prompt||`请分析材料实验数据文件 ${res.path}，检查其数据质量与物理特征，并给出建议的处理与分析工作流。`;input.focus();toast(`已载入：${res.title||'演示数据集'}`)}catch(e){toast('载入失败：'+e.message)}}
function toast(text){const item=el('div','toast',text);const openDialog=document.querySelector('dialog[open]');if(openDialog){openDialog.append(item)}else{document.body.append(item)}setTimeout(()=>item.remove(),3200)}
let currentActionMenu=null;
function closeActionMenu(){if(currentActionMenu){currentActionMenu.remove();currentActionMenu=null}}
document.addEventListener('click',()=>closeActionMenu());
window.addEventListener('resize',()=>closeActionMenu());
function openActionMenu(anchorBtn,items){
  closeActionMenu();
  const rect=anchorBtn.getBoundingClientRect();
  const menu=el('div','action-dropdown-menu');
  menu.style.top=`${rect.bottom+4}px`;
  menu.style.left=`${Math.max(10,Math.min(rect.left,window.innerWidth-165))}px`;
  items.forEach(it=>{
    const btn=el('button','action-menu-item'+(it.danger?' danger':''),it.label);
    btn.onclick=e=>{e.stopPropagation();closeActionMenu();it.onClick()};
    menu.append(btn);
  });
  document.body.append(menu);
  currentActionMenu=menu;
}
function selectedTitle(){if(selectedProject==='all')return '全部项目';if(selectedProject==='__ungrouped__')return '未归类';return allProjects.find(p=>p.id===selectedProject)?.title||'全部项目'}
async function refresh(){[allProjects,allSessions]=await Promise.all([api('/api/projects'),api('/api/sessions')]);renderProjects();renderSessions();document.querySelector('#view-title').textContent=selectedTitle()==='全部项目'?'研究对话':selectedTitle();document.querySelector('#view-subtitle').textContent=selectedProject==='all'?'围绕研究目标讨论证据、原始数据与工作流。':`当前课题空间：${selectedTitle()}。新建会话将归入此项目。`}
function selectProject(id){selectedProject=id;localStorage.setItem('studyui.project',id);if(id!=='all')expandedProjects.add(id);active='';renderProjects();renderSessions();syncFlowProject();document.querySelector('#view-title').textContent=id==='all'?'研究对话':selectedTitle();document.querySelector('#view-subtitle').textContent=id==='all'?'围绕研究目标讨论证据、原始数据与工作流。':`当前课题空间：${selectedTitle()}。新建会话将归入此项目。`;showWelcome()}
async function newSessionInProject(projectId){
  try{
    const pid=(projectId&&projectId!=='__ungrouped__')?projectId:null;
    const proj=allProjects.find(p=>p.id===pid);
    const title=proj?`${proj.title} · 研究任务`:'研究任务';
    const data=await api('/api/sessions',{method:'POST',body:{title,project_id:pid}});
    if(pid)expandedProjects.add(pid);else expandedProjects.add('__ungrouped__');
    await refresh();
    await openSession(data.id);
    feed.replaceChildren();
    addMessage('assistant',`你好，我是 StudyUI。${proj?`本次研究会话属于「${proj.title}」。`:''}告诉我你的研究目标、数据类型或需要检查的工作流，我会先梳理证据和待确认条件。`);
  }catch(err){toast(err.message)}
}
function renderProjects(){
  const sel=document.querySelector('#project-filter-select');
  if(sel){
    sel.replaceChildren();
    const ungrouped=allSessions.filter(s=>!s.project_id).length;
    const optAll=el('option','',`📁 全部课题空间 (${allSessions.length})`);
    optAll.value='all';
    sel.append(optAll);
    for(const p of allProjects){
      const count=allSessions.filter(s=>s.project_id===p.id).length;
      const opt=el('option','',`📁 ${p.title} (${count})`);
      opt.value=p.id;
      sel.append(opt);
    }
    if(ungrouped>0||allProjects.length===0){
      const optUn=el('option','',`◦ 未归类工作区 (${ungrouped})`);
      optUn.value='__ungrouped__';
      sel.append(optUn);
    }
    sel.value=selectedProject;
    sel.onchange=()=>selectProject(sel.value);
  }
  if(projectsNode)projectsNode.replaceChildren();
}
function renderSessions(){
  ensureExpanded();
  const tree=document.querySelector('#project-tree');
  if(!tree)return;
  tree.replaceChildren();
  let groupsToShow=[];
  if(selectedProject==='all'){
    for(const p of allProjects){
      const pSessions=allSessions.filter(s=>s.project_id===p.id);
      groupsToShow.push({id:p.id,title:p.title,sessions:pSessions,isProject:true,icon:'📁'});
    }
    const ungroupedSessions=allSessions.filter(s=>!s.project_id);
    if(ungroupedSessions.length>0||allProjects.length===0){
      groupsToShow.push({id:'__ungrouped__',title:'未归类工作区',sessions:ungroupedSessions,isProject:false,icon:'◦'});
    }
  }else if(selectedProject==='__ungrouped__'){
    const ungroupedSessions=allSessions.filter(s=>!s.project_id);
    groupsToShow.push({id:'__ungrouped__',title:'未归类工作区',sessions:ungroupedSessions,isProject:false,icon:'◦'});
  }else{
    const p=allProjects.find(x=>x.id===selectedProject);
    if(p){
      const pSessions=allSessions.filter(s=>s.project_id===p.id);
      groupsToShow.push({id:p.id,title:p.title,sessions:pSessions,isProject:true,icon:'📁'});
    }
  }
  if(selectedProject!=='all'){
    const bar=el('div','tree-filter-banner');
    bar.innerHTML=`<span class="filter-tag">已筛选：${escapeHtml(selectedTitle())}</span><button type="button" class="clear-filter-btn" title="查看所有课题空间">显示全部</button>`;
    bar.querySelector('.clear-filter-btn').onclick=()=>selectProject('all');
    tree.append(bar);
  }
  if(groupsToShow.length===0){
    tree.append(el('div','empty-side','暂无课题空间，点击右上角 ＋ 新建'));
    return;
  }
  for(const g of groupsToShow){
    const isExpanded=expandedProjects.has(g.id);
    const groupEl=el('div','tree-group'+(isExpanded?' expanded':' collapsed'));
    groupEl.dataset.projectId=g.id;
    const head=el('div','tree-head'+(selectedProject===g.id?' current-project':''));
    const chev=el('span','tree-chevron',isExpanded?'▾':'▸');
    const ico=el('span','tree-folder-ico',g.icon);
    const titleSpan=el('span','tree-title',g.title);
    titleSpan.title=g.title;
    const badge=el('span','tree-badge',String(g.sessions.length));
    const actions=el('div','tree-actions');
    const addBtn=el('button','tree-act-btn','＋');
    addBtn.title=`在「${g.title}」中新建会话`;
    addBtn.onclick=e=>{e.stopPropagation();newSessionInProject(g.id);};
    actions.append(addBtn);
    if(g.isProject){
      const menuBtn=el('button','tree-act-btn','⋯');
      menuBtn.title=`管理项目：${g.title}`;
      menuBtn.onclick=e=>{
        e.stopPropagation();
        openActionMenu(menuBtn,[
          {label:'✏️ 重命名项目',onClick:async()=>{
            const newTitle=window.prompt('新的项目名称',g.title);
            if(newTitle?.trim()){try{await api(`/api/projects/${g.id}`,{method:'PATCH',body:{title:newTitle.trim()}});await refresh()}catch(err){toast(err.message)}}
          }},
          {label:'🗑️ 删除此项目',danger:true,onClick:async()=>{
            if(window.confirm(`确认删除项目「${g.title}」？研究会话会保留在「未归类」，工作流移入恢复目录。`)){
              try{await api(`/api/projects/${g.id}`,{method:'DELETE'});if(selectedProject===g.id)selectedProject='all';await refresh();toast('项目已删除')}catch(err){toast(err.message)}
            }
          }}
        ]);
      };
      actions.append(menuBtn);
    }
    head.append(chev,ico,titleSpan,badge,actions);
    head.onclick=e=>{if(e.target.closest('.tree-actions'))return;toggleProjectExpand(g.id);};
    groupEl.append(head);
    if(isExpanded){
      const sessList=el('div','tree-sessions');
      if(g.sessions.length===0){
        sessList.append(el('div','tree-empty-hint','暂无会话，点击 ＋ 创建'));
      }else{
        for(const s of g.sessions){
          const row=el('div','tree-session-row');
          const isCurrentActive=(s.id===active);
          const sBtn=el('button','tree-session-btn'+(isCurrentActive?' active':''));
          sBtn.title=s.title||'研究任务';
          sBtn.innerHTML=`<span class="tree-session-icon">💬</span><span class="tree-session-title">${escapeHtml(s.title||'研究任务')}</span>`;
          sBtn.onclick=()=>openSession(s.id);
          row.append(sBtn);
          const sActions=el('div','tree-session-actions');
          const sMenuBtn=el('button','session-action','⋯');
          sMenuBtn.title='会话操作';
          sMenuBtn.onclick=e=>{
            e.stopPropagation();
            openActionMenu(sMenuBtn,[
              {label:'✏️ 重命名会话',onClick:async()=>{
                const newTitle=window.prompt('新的会话名称',s.title);
                if(newTitle?.trim()){try{await api(`/api/sessions/${s.id}`,{method:'PATCH',body:{title:newTitle.trim()}});await refresh()}catch(err){toast(err.message)}}
              }},
              {label:'📁 移动到指定项目',onClick:async()=>{
                if(!allProjects.length){toast('当前尚无项目');return}
                const menu=allProjects.map((p,i)=>`${i+1}. ${p.title}`).join('\n');
                const idx=Number(window.prompt(`输入目标项目序号：\n${menu}`,'1'))-1;
                const target=allProjects[idx]?.id;
                if(target){try{await api(`/api/sessions/${s.id}`,{method:'PATCH',body:{project_id:target}});expandedProjects.add(target);await refresh()}catch(err){toast(err.message)}}
              }},
              {label:'◦ 移至未归类',onClick:async()=>{
                try{await api(`/api/sessions/${s.id}`,{method:'PATCH',body:{project_id:null}});expandedProjects.add('__ungrouped__');await refresh();if(active===s.id)await openSession(s.id)}catch(err){toast(err.message)}
              }},
              {label:'🗑️ 删除此会话',danger:true,onClick:async()=>{
                if(window.confirm(`确认删除会话「${s.title}」？此操作不可撤销。`)){
                  try{await api(`/api/sessions/${s.id}`,{method:'DELETE'});toast('会话已删除');await refresh();if(active===s.id){if(allSessions.length)await openSession(allSessions[0].id);else await newSession();}}catch(err){toast(err.message)}
                }
              }}
            ]);
          };
          const sDelBtn=el('button','session-action','✕');
          sDelBtn.title='删除会话';
          sDelBtn.style.color='#9c4d4d';
          sDelBtn.onclick=async e=>{
            e.stopPropagation();
            if(window.confirm(`确认删除会话「${s.title}」？`)){
              try{await api(`/api/sessions/${s.id}`,{method:'DELETE'});toast('会话已删除');await refresh();if(active===s.id){if(allSessions.length)await openSession(allSessions[0].id);else await newSession();}}catch(err){toast(err.message)}
            }
          };
          sActions.append(sMenuBtn,sDelBtn);
          row.append(sActions);
          sessList.append(row);
        }
      }
      groupEl.append(sessList);
    }
    tree.append(groupEl);
  }
}
function showProposals(rows){for(const p of rows||[]){const card=el('article','proposal');card.dataset.id=p.id;card.append(el('h3','',`待审核：${p.summary.flow_name||'工作流改动'}`));card.append(el('p','',p.summary.rationale||''));const ul=el('ul');for(const c of p.summary.changes||[])ul.append(el('li','',c));card.append(ul);const btns=el('div','actions');const a=el('button','approve','批准并保存'),r=el('button','reject','拒绝');a.onclick=()=>decision(p.id,'approve',card);r.onclick=()=>decision(p.id,'reject',card);btns.append(a,r);card.append(btns);feed.append(card)}feed.scrollTop=feed.scrollHeight}
function showApprovals(rows){for(const item of rows||[]){if(feed.querySelector(`[data-approval="${item.id}"]`))continue;const card=el('article','proposal');card.dataset.approval=item.id;const summary=item.summary||{};card.append(el('h3','',`需要审批：${summary.title||item.action}`),el('p','',summary.impact||item.reason||`项目 ${item.project_id||'未归类'} 中的操作等待一次性批准。`));if(summary.nodes?.length)card.append(el('p','settings-note',`节点：${summary.nodes.join('、')}`));if(summary.scripts?.length)card.append(el('p','settings-note',`脚本：${summary.scripts.join('、')}`));card.append(el('p','settings-note',summary.reason||item.reason||''));const btns=el('div','actions');const a=el('button','approve','批准并执行'),r=el('button','reject','拒绝'),c=el('button','','取消');a.onclick=()=>approvalDecision(item.id,'approve',card);r.onclick=()=>approvalDecision(item.id,'reject',card);c.onclick=()=>approvalDecision(item.id,'cancel',card);btns.append(a,r,c);card.append(btns);feed.append(card)}feed.scrollTop=feed.scrollHeight}
async function approvalDecision(id,decision,card){try{const r=await api(`/api/approvals/${id}/${decision}`,{method:'POST',body:{}});card.remove();if(r.status==='completed'){addMessage('assistant',`✅ 已执行获批操作：\n\`\`\`json\n${JSON.stringify(r.result||{},null,2).slice(0,1200)}\n\`\`\``);showArtifacts(r.result?.artifacts||[]);if(r.result?.flow_id)syncFlowProject()}else addMessage('assistant',decision==='approve'?'已批准。':decision==='cancel'?'已取消该审批。':'已拒绝该操作。');await loadSettings()}catch(e){addMessage('assistant',`操作未完成：${e.message}`)}}
async function decision(id,action,card){try{const r=await api(`/api/proposals/${id}/${action}`,{method:'POST',body:{}});card.remove();addMessage('assistant',action==='approve'?`提案已保存到 StudyUI：${r.flow_name||''}`:'已拒绝该提案。')}catch(e){addMessage('assistant',e.message)}}
async function openSession(id){
  active=id;
  const s=allSessions.find(row=>row.id===id);
  if(s){
    const pid=s.project_id||'__ungrouped__';
    expandedProjects.add(pid);
  }
  syncFlowProject();
  feed.replaceChildren();
  renderProjects();
  renderSessions();
  try{
    const data=await api(`/api/sessions/${id}`);
    const visible=(data.messages||[]).filter(m=>m.role==='user'||m.role==='assistant');
    if(visible.length){for(const m of visible)addMessage(m.role,m.content||'',{reasoning_content:m.reasoning_content,tool_steps:m.tool_steps,model:m.model||activeModelName})}else showWelcome();
    showSkillSelections(data.skill_selections||[]);
    showArtifacts(data.artifacts||[]);
    showProposals(data.pending_proposals);
    showApprovals(data.pending_approvals);
  }catch(e){addMessage('assistant',e.message)}
}
async function newSession(){
  try{
    let pid=null;
    if(selectedProject!=='all'&&selectedProject!=='__ungrouped__'){
      pid=selectedProject;
    }else if(active){
      const cur=allSessions.find(s=>s.id===active);
      if(cur&&cur.project_id)pid=cur.project_id;
    }
    const proj=allProjects.find(p=>p.id===pid);
    const data=await api('/api/sessions',{method:'POST',body:{title:'研究任务',project_id:pid}});
    if(pid)expandedProjects.add(pid);else expandedProjects.add('__ungrouped__');
    await refresh();
    await openSession(data.id);
    feed.replaceChildren();
    addMessage('assistant',`你好，我是 StudyUI。${pid?`本次研究会话属于「${selectedTitle()}」。`:''}告诉我你的研究目标、数据类型或需要检查的工作流，我会先梳理证据和待确认条件。`);
  }catch(e){toast(e.message)}
}
async function submit(){
  const text=input.value.trim();
  if(!text||!active)return;
  input.value='';
  send.disabled=true;
  addMessage('user',text);

  const assistantMsg=el('div','msg assistant');
  assistantMsg.style.position='relative';
  const headBar=el('div','msg-header-bar');
  headBar.style.cssText='display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;font-size:10.5px;color:#788290;border-bottom:1px solid #ebe6dc;padding-bottom:5px;';
  const initialMName=activeModelName||'StudyUI';
  headBar.innerHTML=`<span class="model-badge">⚡ ${escapeHtml(initialMName)} 正在实时推演...</span><span class="live-timer" style="color:#29476f;font-weight:600">⏱️ 0.0s</span>`;
  assistantMsg.append(headBar);

  const auditBox=el('div','audit-stepper-box');
  auditBox.innerHTML=`
    <div class="audit-stepper-head"><span>🔬 科学工具与审计推演 (${escapeHtml(initialMName)})</span><span style="font-size:10.5px;color:#64748b">实时执行中</span></div>
    <ul class="audit-steps-list" id="live-audit-steps">
      <li class="audit-step-item active" id="step-live-init">
        <span class="audit-step-icon">⟳</span>
        <div class="audit-step-body">
          <div class="audit-step-title-row"><span class="audit-step-name">初始化推理上下文与安全沙盒</span><span class="audit-step-duration">running</span></div>
          <div class="audit-step-detail">载入材料科学安全域与上下文守卫</div>
        </div>
      </li>
    </ul>
  `;
  assistantMsg.append(auditBox);

  const thinkingBox=el('div','deepseek-thinking');
  thinkingBox.style.display='none';
  thinkingBox.innerHTML=`
    <div class="thinking-head" onclick="toggleThinking(this)">
      <span class="thinking-tag">🧠 深度思考过程 (${escapeHtml(initialMName)})</span>
      <span class="thinking-meta-info"><span class="thinking-live-timer">思考中...</span><span class="thinking-char-count"></span><button type="button" class="thinking-toggle-btn">▼ 折叠</button></span>
    </div>
    <div class="thinking-content" id="live-thinking-text"></div>
  `;
  assistantMsg.append(thinkingBox);

  const contentBox=el('div','rich-content');
  contentBox.innerHTML='<span class="typing-cursor"></span>';
  assistantMsg.append(contentBox);
  feed.append(assistantMsg);
  feed.scrollTop=feed.scrollHeight;

  const startTime=Date.now();
  const timerInterval=setInterval(()=>{
    const elapsed=((Date.now()-startTime)/1000).toFixed(1);
    const timerSpan=headBar.querySelector('.live-timer');
    if(timerSpan)timerSpan.textContent=`⏱️ ${elapsed}s`;
    const thinkTimer=thinkingBox.querySelector('.thinking-live-timer');
    if(thinkTimer&&thinkingBox.style.display!=='none')thinkTimer.textContent=`已思考 ${elapsed}s`;
  },100);

  let displayedText='';
  let fullTargetText='';
  let turnFinishedData=null;
  let typingDone=false;
  let collectedReasoning='';
  let reasoningDirty=false;
  let reasoningRaf=null;

  function flushReasoningDisplay(){
    if(!collectedReasoning)return;
    thinkingBox.style.display='block';
    const tBox=thinkingBox.querySelector('#live-thinking-text');
    if(tBox){
      const isUserScrolledUp=tBox.scrollHeight - tBox.scrollTop - tBox.clientHeight > 45;
      tBox.textContent=collectedReasoning;
      if(!isUserScrolledUp){tBox.scrollTop=tBox.scrollHeight;}
    }
    const countSpan=thinkingBox.querySelector('.thinking-char-count');
    if(countSpan)countSpan.textContent=`· 共 ${collectedReasoning.length} 字`;
    const isFeedScrolledUp=feed.scrollHeight - feed.scrollTop - feed.clientHeight > 80;
    if(!isFeedScrolledUp){feed.scrollTop=feed.scrollHeight;}
  }

  function scheduleReasoningRender(){
    if(reasoningDirty)return;
    reasoningDirty=true;
    reasoningRaf=requestAnimationFrame(()=>{
      reasoningDirty=false;
      flushReasoningDisplay();
    });
  }

  function renderFinalView(data){
    if(typingDone)return;
    typingDone=true;
    if(reasoningRaf){cancelAnimationFrame(reasoningRaf);reasoningRaf=null;}
    clearInterval(timerInterval);
    clearInterval(typeInterval);
    send.disabled=false;
    const elapsed=((Date.now()-startTime)/1000).toFixed(1);
    const timerSpan=headBar.querySelector('.live-timer');
    if(timerSpan)timerSpan.textContent=`⏱️ ${elapsed}s`;

    const finalMName=data.model||activeModelName||'StudyUI';
    let modeText=`⚡ ${finalMName} 科研智能体`;
    if(data.reasoning_content&&data.tool_steps&&data.tool_steps.length){
      modeText=`🌟 混合推理与科学工具 (${finalMName})`;
    }else if(data.reasoning_content){
      modeText=`🧠 深度推演模式 (${finalMName})`;
    }else if(data.tool_steps&&data.tool_steps.length){
      modeText=`🔬 科学工具推演 (${finalMName})`;
    }
    const mb=headBar.querySelector('.model-badge');
    if(mb)mb.textContent=modeText;

    if(data.tool_steps&&data.tool_steps.length){
      auditBox.replaceWith(createAuditStepper(data.tool_steps,finalMName));
    }else{
      auditBox.remove();
    }

    const finalReasoning=(data.reasoning_content||collectedReasoning||'').trim();
    if(finalReasoning){
      thinkingBox.style.display='block';
      const thinkText=thinkingBox.querySelector('.thinking-content');
      if(thinkText)thinkText.textContent=finalReasoning;
      const countSpan=thinkingBox.querySelector('.thinking-char-count');
      if(countSpan)countSpan.textContent=`· 共 ${finalReasoning.length} 字`;
      const thinkTimer=thinkingBox.querySelector('.thinking-live-timer');
      if(thinkTimer)thinkTimer.textContent=`思考耗时 ${elapsed}s`;
    }else{
      thinkingBox.remove();
    }

    const fullText=data.message||fullTargetText||'';
    if(!fullText.trim()){
      contentBox.textContent='(无回复内容)';
    }else{
      const finalNode=renderRichContent(fullText);
      contentBox.replaceWith(finalNode);
    }
    const actDiv=document.createElement('div');
    actDiv.style.display='flex';
    actDiv.style.gap='6px';
    actDiv.innerHTML=`<button type="button" class="prompt-chip" style="padding:2px 7px;font-size:10px" onclick="toggleGrounding(this)">🔍 溯源高亮</button><button type="button" class="prompt-chip" style="padding:2px 7px;font-size:10px" onclick="navigator.clipboard.writeText(this.closest('.msg').querySelector('.rich-content')?.innerText||'');toast('已复制学术文本')">📋 复制</button>`;
    headBar.append(actDiv);
    showArtifacts(data.artifacts||[]);
    showProposals(data.pending_proposals);
    showApprovals(data.pending_approvals);
    const isFeedScrolledUp=feed.scrollHeight - feed.scrollTop - feed.clientHeight > 80;
    if(!isFeedScrolledUp){feed.scrollTop=feed.scrollHeight;}
    refresh();
  }

  // Smooth progressive typing cadence pump with adaptive catch-up:
  const typeInterval=setInterval(()=>{
    if(turnFinishedData){
      displayedText=fullTargetText;
      renderFinalView(turnFinishedData);
      return;
    }
    if(displayedText.length<fullTargetText.length){
      const remaining=fullTargetText.length-displayedText.length;
      const step=remaining>300?Math.max(20,Math.ceil(remaining/5)):(remaining>100?Math.max(12,Math.ceil(remaining/8)):(remaining>40?Math.max(6,Math.ceil(remaining/10)):Math.min(remaining,3)));
      displayedText+=fullTargetText.slice(displayedText.length,displayedText.length+step);
      contentBox.innerHTML=escapeHtml(displayedText)+'<span class="typing-cursor"></span>';
      const isFeedScrolledUp=feed.scrollHeight - feed.scrollTop - feed.clientHeight > 80;
      if(!isFeedScrolledUp){feed.scrollTop=feed.scrollHeight;}
    }
  },35);

  try{
    const res=await fetch(`/api/sessions/${active}/messages`,{
      method:'POST',
      headers:{'Content-Type':'application/json','Accept':'text/event-stream'},
      body:JSON.stringify({message:text})
    });
    if(!res.ok){
      const err=await res.json().catch(()=>({error:'请求失败'}));
      throw new Error(err.error||`HTTP ${res.status}`);
    }
    const contentType=res.headers.get('content-type')||'';
    if(contentType.includes('text/event-stream')){
      const reader=res.body.getReader();
      const decoder=new TextDecoder();
      let buffer='';
      while(true){
        const {done,value}=await reader.read();
        if(done)break;
        buffer+=decoder.decode(value,{stream:true});
        let boundary=buffer.indexOf('\n\n');
        while(boundary!==-1){
          const rawEvent=buffer.slice(0,boundary);
          buffer=buffer.slice(boundary+2);
          boundary=buffer.indexOf('\n\n');
          let eventType='message';
          let dataStr='';
          for(const line of rawEvent.split('\n')){
            if(line.startsWith('event: '))eventType=line.slice(7).trim();
            else if(line.startsWith('data: '))dataStr=line.slice(6);
          }
          if(dataStr){
            try{
              const payload=JSON.parse(dataStr);
              if(payload.model){
                activeModelName=payload.model;
                const mBadge=headBar.querySelector('.model-badge');
                if(mBadge&&!typingDone)mBadge.textContent=`⚡ ${payload.model} 正在实时推演...`;
              }
              if(eventType==='tool_start'){
                const list=auditBox.querySelector('#live-audit-steps');
                const initStep=list.querySelector('#step-live-init');
                if(initStep)initStep.remove();
                const li=document.createElement('li');
                li.className='audit-step-item active';
                li.id='step-'+payload.id;
                li.innerHTML=`<span class="audit-step-icon">⟳</span><div class="audit-step-body"><div class="audit-step-title-row"><span class="audit-step-name">${payload.icon||'🛠️'} ${escapeHtml(payload.title||payload.name)}</span><span class="audit-step-duration">running</span></div><div class="audit-step-detail">正在执行工具调度并校验数据合规性...</div></div>`;
                list.append(li);
                feed.scrollTop=feed.scrollHeight;
              }else if(eventType==='tool_end'||eventType==='step_end'){
                const step=payload.step||payload;
                const list=auditBox.querySelector('#live-audit-steps');
                let li=list.querySelector('#step-'+step.id);
                if(!li){
                  const initStep=list.querySelector('#step-live-init');
                  if(initStep)initStep.remove();
                  li=document.createElement('li');
                  list.append(li);
                }
                li.className='audit-step-item '+(step.ok?'completed':'failed');
                li.id='step-'+step.id;
                li.innerHTML=`<span class="audit-step-icon">${step.ok?'✓':'✕'}</span><div class="audit-step-body"><div class="audit-step-title-row"><span class="audit-step-name">${step.icon||'🛠️'} ${escapeHtml(step.title||step.name)}</span><span class="audit-step-duration">${step.duration_ms||10}ms</span></div><div class="audit-step-detail">${escapeHtml(step.summary||'执行完成')}</div></div>`;
                feed.scrollTop=feed.scrollHeight;
              }else if(eventType==='reasoning'){
                if(payload.reasoning_content){
                  collectedReasoning=payload.reasoning_content;
                }else if(payload.delta){
                  collectedReasoning+=payload.delta;
                }
                scheduleReasoningRender();
              }else if(eventType==='content_chunk'){
                if(payload.delta){
                  fullTargetText+=payload.delta;
                }
              }else if(eventType==='content_ready'){
                if(payload.content&&payload.content.length>fullTargetText.length){
                  fullTargetText=payload.content;
                }
              }else if(eventType==='done'){
                if(reasoningRaf){cancelAnimationFrame(reasoningRaf);reasoningRaf=null;}
                const data=payload.result||payload;
                if(data.model)activeModelName=data.model;
                if(data.message&&data.message.length>fullTargetText.length){
                  fullTargetText=data.message;
                }
                turnFinishedData=data;
                displayedText=fullTargetText;
                flushReasoningDisplay();
                renderFinalView(data);
                return;
              }
            }catch(err){}
          }
        }
      }
    }else{
      const data=await res.json();
      if(data.model)activeModelName=data.model;
      fullTargetText=data.message||'';
      turnFinishedData=data;
      displayedText=fullTargetText;
      renderFinalView(data);
    }
  }catch(e){
    if(reasoningRaf){cancelAnimationFrame(reasoningRaf);reasoningRaf=null;}
    clearInterval(timerInterval);
    clearInterval(typeInterval);
    auditBox.remove();
    thinkingBox.remove();
    contentBox.innerHTML=`<span style="color:#b32626">出错了：${escapeHtml(e.message)}</span>`;
  }finally{
    if(reasoningRaf){cancelAnimationFrame(reasoningRaf);reasoningRaf=null;}
    send.disabled=false;
    input.focus();
  }
}
function syncFlowProject(){const frame=document.querySelector('#flow-frame');const project=allProjects.some(p=>p.id===selectedProject)?selectedProject:'';const url=new URL(frame.dataset.src,location.origin);if(project)url.pathname=url.pathname.replace(/\/$/,'')+'/all/folder/'+encodeURIComponent(project);if(active)url.searchParams.set('studyui_session_id',active);else url.searchParams.delete('studyui_session_id');const context=project+'|'+active;const changed=frame.dataset.context!==context;frame.dataset.context=context;if(frame.dataset.loaded&&(changed||!frame.hasAttribute('src')))frame.src=url.href;document.querySelector('#open-canvas').href=url.href}
function showView(name, pushHistory=true){const main=document.querySelector('main');const chatView=document.querySelector('#chat-view');const flowView=document.querySelector('#flow-view');const isChat=name==='chat';const isFlow=name==='flow';const isSplit=name==='split';main.classList.toggle('split-mode',isSplit);chatView.hidden=isFlow;flowView.hidden=isChat;document.querySelectorAll('.btn-mode-chat').forEach(b=>b.classList.toggle('active',isChat));document.querySelectorAll('.btn-mode-split').forEach(b=>b.classList.toggle('active',isSplit));document.querySelectorAll('.btn-mode-flow').forEach(b=>b.classList.toggle('active',isFlow));document.querySelector('#btn-mode-chat')?.classList.toggle('active',isChat);document.querySelector('#btn-mode-split')?.classList.toggle('active',isSplit);document.querySelector('#btn-mode-flow')?.classList.toggle('active',isFlow);document.querySelector('#nav-chat')?.classList.toggle('active',isChat||isSplit);document.querySelector('#nav-flow')?.classList.toggle('active',isFlow);if(pushHistory&&window.history&&window.history.pushState){try{window.history.pushState({view:name},'',location.pathname+(isChat?'':'#'+name))}catch(e){}}if(isFlow||isSplit){const frame=document.querySelector('#flow-frame');if(!frame.dataset.loaded){frame.dataset.loaded='1';frame.dataset.project='__initial__';syncFlowProject()}}}
window.addEventListener('popstate',e=>{const v=e.state?.view||(location.hash==='#flow'?'flow':(location.hash==='#split'?'split':'chat'));showView(v,false)});
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('#flow-view').hidden&&!document.querySelector('dialog[open]')){showView('chat')}});
document.querySelector('#btn-mode-chat')?.addEventListener('click',()=>showView('chat'));
document.querySelector('#btn-mode-split')?.addEventListener('click',()=>showView('split'));
document.querySelector('#btn-mode-flow')?.addEventListener('click',()=>showView('flow'));
document.querySelector('#nav-chat').onclick=()=>showView('chat');
document.querySelector('#nav-flow').onclick=()=>showView('flow');
document.querySelector('#btn-export-brief')?.addEventListener('click',exportResearchBrief);
document.querySelector('#lightbox-close')?.addEventListener('click',closeLightbox);
document.querySelector('#data-preview-close')?.addEventListener('click',()=>document.querySelector('#data-preview-dialog').close());
document.querySelector('#new').onclick=newSession;
send.onclick=submit;
input.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submit()}};
document.querySelector('#demo-quick-btn')?.addEventListener('click',async()=>{try{const res=await api('/api/demo-datasets');const list=res.datasets||[];const text=list.map((d,i)=>`${i+1}. ${d.title} (${d.filename})`).join('\n');const choice=window.prompt(`选择要载入的材料科学经典演示数据（输入 1-${list.length}）：\n${text}`,'1');if(choice){const idx=parseInt(choice,10)-1;if(list[idx])await loadDemoDataset(list[idx].id)}}catch(e){toast(e.message)}});
const dropOverlay=document.querySelector('#drop-overlay');
let dragCounter=0;
window.addEventListener('dragenter',e=>{if(e.dataTransfer&&e.dataTransfer.types&&Array.from(e.dataTransfer.types).includes('Files')){dragCounter++;if(dropOverlay){dropOverlay.classList.add('active');dropOverlay.style.display='flex';dropOverlay.hidden=false}}});
window.addEventListener('dragleave',e=>{dragCounter--;if(dragCounter<=0){dragCounter=0;if(dropOverlay){dropOverlay.classList.remove('active');dropOverlay.style.display='none';dropOverlay.hidden=true}}});
window.addEventListener('dragover',e=>{e.preventDefault()});
window.addEventListener('drop',async e=>{e.preventDefault();dragCounter=0;if(dropOverlay){dropOverlay.classList.remove('active');dropOverlay.style.display='none';dropOverlay.hidden=true}const files=e.dataTransfer?.files;if(!files||!files.length)return;if(!active)await newSession();const file=files[0];toast(`正在上传「${file.name}」...`);try{const res=await fetch('/api/upload',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Filename':encodeURIComponent(file.name),'X-StudyUI-Session':active},body:file});const data=await res.json();if(!res.ok)throw new Error(data.error||'上传失败');toast(`文件「${file.name}」上传成功！`);input.value=data.prompt||`请检查并分析已上传的数据文件 ${data.path}，识别其数据结构、关键指标与异常值，并给出适用的数据处理工作流。`;input.focus()}catch(err){toast('上传失败：'+err.message)}});
window.addEventListener('message',async event=>{const frame=document.querySelector('#flow-frame');const item=event.data;if(event.origin!==location.origin||event.source!==frame.contentWindow||!item||item.type!=='studyui-agent-run-complete'||typeof item.session_id!=='string')return;try{await refresh();if(allSessions.some(row=>row.id===item.session_id)){await openSession(item.session_id);showView('chat')}}catch(error){toast(error.message)}});
document.querySelectorAll('dialog').forEach(d=>{d.addEventListener('click',e=>{const rect=d.getBoundingClientRect();const inside=(rect.top<=e.clientY&&e.clientY<=rect.bottom&&rect.left<=e.clientX&&e.clientX<=rect.right);if(!inside)d.close()})});
const urlInput=document.querySelector('#model-url');
const urlPreview=document.querySelector('#model-url-preview');
function updateUrlPreview(){if(!urlInput||!urlPreview)return;const raw=urlInput.value.trim();if(!raw){urlPreview.textContent='最终请求端点：(请输入 API 地址)';return}const clean=raw.replace(/\/+$/,'');const finalEndpoint=clean.endsWith('/chat/completions')?clean:`${clean}/chat/completions`;urlPreview.textContent=`最终请求端点：${finalEndpoint}`}
urlInput?.addEventListener('input',updateUrlPreview);
const dialog=document.querySelector('#project-dialog');document.querySelector('#add-project').onclick=()=>{document.querySelector('#project-title').value='';dialog.showModal();setTimeout(()=>document.querySelector('#project-title').focus(),30)};document.querySelector('#cancel-project').onclick=()=>dialog.close();document.querySelector('#project-form').onsubmit=async e=>{e.preventDefault();const title=document.querySelector('#project-title').value.trim();if(!title)return;try{const result=await api('/api/projects',{method:'POST',body:{title}});dialog.close();await refresh();selectProject(result.id);toast('项目已创建')}catch(err){toast(err.message)}};
const settingsDialog=document.querySelector('#settings-dialog');document.querySelector('#settings-open').onclick=async()=>{await loadSettings();updateUrlPreview();settingsDialog.showModal()};document.querySelector('#settings-close').onclick=()=>settingsDialog.close();document.querySelector('#model-form').onsubmit=async e=>{e.preventDefault();try{await saveModel();toast('模型配置已保存')}catch(err){toast(err.message)}};document.querySelector('#test-model').onclick=async()=>{const banner=document.querySelector('#model-test-banner');if(banner){banner.style.display='block';banner.style.background='#eef4fb';banner.style.color='#1f3e66';banner.style.border='1px solid #c9daf0';banner.innerHTML='⏳ 正在测试连接 API 端点...'}try{await saveModel();await api('/api/settings/model/test',{method:'POST',body:{}});if(banner){banner.style.background='#eaf7ee';banner.style.color='#1b6332';banner.style.border='1px solid #b7e4c3';banner.innerHTML='✅ 模型连接成功！API 端点响应正常。'}toast('✅ 模型连接成功')}catch(err){if(banner){banner.style.display='block';banner.style.background='#fdf0f0';banner.style.color='#9c2424';banner.style.border='1px solid #f3c2c2';banner.innerHTML=`❌ 连接失败：${escapeHtml(err.message)}`}toast(`连接失败：${err.message}`)}};document.querySelector('#permission-preset').onchange=async e=>{try{const result=await api('/api/permissions',{method:'POST',body:{project_id:selectedProject==='all'||selectedProject==='__ungrouped__'?null:selectedProject,preset:e.target.value,session_id:active}});if(result.status==='pending_approval'){toast('权限升级已提交审批');if(active){const session=await api(`/api/sessions/${active}`);showApprovals(session.pending_approvals)}}else{document.querySelector('#permission-description').textContent=permissionText[result.preset]||'';toast('项目权限已更新')}}catch(err){toast(err.message);await loadSettings()}};document.querySelector('#skill-upload').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;try{if(!active)throw new Error('请先打开研究会话');const response=await fetch('/api/skills/preview',{method:'POST',headers:{'Content-Type':'application/zip','X-Filename':encodeURIComponent(file.name),'X-StudyUI-Session':active},body:file});const data=await response.json();if(!response.ok)throw new Error(data.error||'Skill 导入失败');const session=await api(`/api/sessions/${active}`);showApprovals(session.pending_approvals);toast('Skill 已完成安全检查，等待一次性审批')}catch(err){toast(err.message)}finally{e.target.value=''}};
(async()=>{try{const health=await api('/api/health');modelConfigured=health.model_configured;if(health.model_name)activeModelName=health.model_name;document.querySelector('#model-status').textContent=modelConfigured?`AI 模型就绪 (${activeModelName})`:'AI 模型未配置';if(modelConfigured)document.querySelector('#model-status').classList.add('ready');await refresh();if(selectedProject!=='all'&&selectedProject!=='__ungrouped__'&&!allProjects.some(p=>p.id===selectedProject))selectedProject='all';renderProjects();renderSessions();const requested=new URLSearchParams(location.search).get('session_id');const first=requested&&allSessions.some(s=>s.id===requested)?allSessions.find(s=>s.id===requested):allSessions.find(s=>selectedProject==='all'||(selectedProject==='__ungrouped__'?!s.project_id:s.project_id===selectedProject));if(first)await openSession(first.id);else if(!allSessions.length)await newSession();else selectProject(selectedProject)}catch(e){addMessage('assistant',e.message)}})();
</script></body></html>"""

PAGE = PAGE.replace(
    "</body></html>",
    r"""<script>
const profilePicker=document.createElement('select');profilePicker.id='model-profile-picker';profilePicker.setAttribute('aria-label','选择模型配置');profilePicker.style.width='100%';profilePicker.style.margin='4px 0 12px';document.querySelector('#model-form .settings-section').prepend(profilePicker);
const baseApi=api;api=async function(path,options={}){if(path.startsWith('/api/projects/')&&options.method==='DELETE'&&!options.body)options={...options,body:{session_id:active}};const value=await baseApi(path,options);if(path.startsWith('/api/projects/')&&options.method==='DELETE'&&value.status==='pending_approval'){if(active){const session=await baseApi(`/api/sessions/${active}`);showApprovals(session.pending_approvals)}throw new Error('项目删除已提交一次性审批；请在对话中的审批卡片确认')}return value};
const profileActions=document.createElement('div');profileActions.className='dialog-actions';profileActions.innerHTML='<button type="button" id="new-model-profile">新增配置</button><button type="button" id="delete-model-profile">删除当前配置</button>';document.querySelector('#model-form .settings-section').insertBefore(profileActions,document.querySelector('#model-name'));
const originalLoadSettings=loadSettings;loadSettings=async function(){await originalLoadSettings();try{const value=await api('/api/settings/model');profilePicker.replaceChildren();for(const p of value.profiles||[]){const o=document.createElement('option');o.value=p.id;o.textContent=`${p.name} · ${p.model}${p.active?'（当前）':''}`;profilePicker.append(o);if(p.active){activeModelName=p.name||p.model||'AI 模型'}}profilePicker.value=value.id||value.profiles?.find(p=>p.active)?.id||'';profilePicker.disabled=!(value.profiles||[]).length;document.querySelector('#delete-model-profile').disabled=(value.profiles||[]).length<2;document.querySelector('#model-status').textContent=modelConfigured?`AI 模型就绪 (${activeModelName})`:'AI 模型未配置';updateUrlPreview()}catch(e){toast(e.message)}};
profilePicker.onchange=async()=>{try{await api('/api/settings/model/activate',{method:'POST',body:{profile_id:profilePicker.value}});await loadSettings()}catch(e){toast(e.message)}};
document.querySelector('#new-model-profile').onclick=()=>{profilePicker.value='';document.querySelector('#model-name').value='新模型';document.querySelector('#model-url').value='https://api.deepseek.com';document.querySelector('#model-name-id').value='deepseek-chat';document.querySelector('#model-reasoning').value='default';document.querySelector('#model-key').value='';document.querySelector('#model-key').placeholder='请输入新配置的 API 密钥';document.querySelector('#model-form').dataset.createNew='1';updateUrlPreview()};
saveModel=async function(){const form=document.querySelector('#model-form');const body={name:document.querySelector('#model-name').value.trim(),base_url:document.querySelector('#model-url').value.trim(),model:document.querySelector('#model-name-id').value.trim(),reasoning_effort:document.querySelector('#model-reasoning').value};if(form.dataset.createNew==='1')body.create_new=true;else if(profilePicker.value&&profilePicker.value!=='environment')body.profile_id=profilePicker.value;const key=document.querySelector('#model-key').value;if(key)body.api_key=key;await api('/api/settings/model',{method:'POST',body});form.dataset.createNew='';document.querySelector('#model-key').value='';const health=await api('/api/health');modelConfigured=health.model_configured;if(health.model_name)activeModelName=health.model_name;document.querySelector('#model-status').textContent=modelConfigured?`AI 模型就绪 (${activeModelName})`:'AI 模型未配置';document.querySelector('#model-status').classList.toggle('ready',modelConfigured);await loadSettings()};
document.querySelector('#delete-model-profile').onclick=async()=>{const id=profilePicker.value;if(!id||!window.confirm('删除当前模型配置及其系统凭据？'))return;try{await api('/api/settings/model',{method:'DELETE',body:{profile_id:id}});await loadSettings();toast('模型配置已删除')}catch(e){toast(e.message)}};
</script></body></html>""",
)


def make_handler(harness, canvas_path):
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
                    "__CANVAS_BASE_PATH__", html.escape(canvas_path.rstrip("/"), quote=True)
                )
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/api/health":
                profile = harness.model_profiles.active()
                m_name = (
                    getattr(harness.model, "model", None)
                    if getattr(harness, "_custom_model", False)
                    else (profile.get("name") or profile.get("model") or getattr(harness.model, "model", "") or "AI 模型")
                )
                if not m_name or m_name == "deepseek-flash":
                    m_name = profile.get("name") or profile.get("model") or "AI 模型"
                return self._send(
                    200,
                    {
                        "status": "ok",
                        "service": "StudyUI",
                        "model_configured": bool(profile.get("configured")),
                        "model_name": m_name,
                        "canvas_url": canvas_path,
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
            if path == "/api/demo-datasets":
                return self._send(200, {"datasets": DEMO_DATASETS})
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
                            {
                                "role": message.get("role"),
                                "content": message.get("content"),
                                "reasoning_content": message.get("reasoning_content"),
                                "tool_steps": message.get("tool_steps"),
                                "model": message.get("model"),
                            }
                            for message in harness.store.messages(session_id, limit=200)
                            if message.get("role") in {"user", "assistant"} and not message.get("tool_calls")
                        ],
                        "pending_proposals": harness.store.pending_proposals(session_id),
                        "pending_approvals": harness.store.pending_approvals(session_id),
                        "artifacts": harness.store.latest_artifacts(session_id),
                        "skill_selections": [
                            event for event in harness.store.events(session_id, limit=500)
                            if event.get("kind") == "skill_selection"
                        ],
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
                if path == "/api/upload":
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 50_000_000:
                        return self._error("上传文件大小必须在 1 字节至 50MB 之间", 413)
                    raw = self.rfile.read(length)
                    raw_filename = unquote(self.headers.get("X-Filename", "uploaded_file.csv"))
                    filename = Path(raw_filename).name or "uploaded_file.csv"
                    session_id = unquote(self.headers.get("X-StudyUI-Session", "")).strip()
                    project_root = getattr(harness, "project_root", Path(__file__).resolve().parents[5])
                    target_dir = project_root / "uploads" / (session_id if session_id else "shared")
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_file = target_dir / filename
                    target_file.write_bytes(raw)
                    saved_path = str(target_file.resolve())
                    prompt = (
                        f"请检查并分析已上传的材料数据文件 {saved_path}，"
                        f"识别其数据结构、关键特征与异常值，并给出适用的数据处理工作流。"
                    )
                    return self._send(200, {
                        "status": "ok",
                        "filename": filename,
                        "path": saved_path,
                        "size": len(raw),
                        "prompt": prompt,
                    })
                data = self._body()
                if path == "/api/demo-datasets/load":
                    dataset_id = data.get("id", "")
                    session_id = data.get("session_id", "").strip()
                    item = next((d for d in DEMO_DATASETS if d["id"] == dataset_id), None)
                    if not item:
                        return self._error("未找到指定的演示数据集", 404)
                    project_root = getattr(harness, "project_root", None) or Path(__file__).resolve().parents[5]
                    candidate_dirs = [
                        project_root / "demo_datasets",
                        Path(__file__).resolve().parents[5] / "demo_datasets",
                        Path(__file__).resolve().parents[1] / "demo_datasets",
                    ]
                    demo_file = None
                    for cdir in candidate_dirs:
                        if cdir and (cdir / item["filename"]).exists():
                            demo_file = cdir / item["filename"]
                            break
                    if not demo_file or not demo_file.exists():
                        return self._error(f"演示数据文件不存在: {item['filename']}", 404)
                    target_dir = project_root / "uploads" / (session_id if session_id else "demo")
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_file = target_dir / item["filename"]
                    shutil.copy2(demo_file, target_file)
                    saved_path = str(target_file.resolve())
                    prompt_template = item.get("prompt") or "请分析材料实验数据文件 {path}，搭建相应的数据处理工作流。"
                    prompt = prompt_template.format(path=saved_path)
                    return self._send(200, {
                        "status": "ok",
                        "id": item["id"],
                        "title": item["title"],
                        "filename": item["filename"],
                        "path": saved_path,
                        "prompt": prompt,
                    })
                if path == "/api/canvas/insert-node":
                    code = data.get("code", "").strip()
                    name = data.get("name", "CustomNode").strip() or "CustomNode"
                    session_id = data.get("session_id", "").strip()
                    if not code:
                        return self._error("代码内容不能为空")
                    project_root = getattr(harness, "project_root", None) or Path(__file__).resolve().parents[5]
                    custom_dir = project_root / ".demo-runtime" / "components" / "materials_custom"
                    custom_dir.mkdir(parents=True, exist_ok=True)
                    slug = re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()
                    target_file = custom_dir / f"{slug}.py"
                    target_file.write_text(code, encoding="utf-8")
                    if hasattr(harness, "langflow") and harness.langflow:
                        with getattr(harness.langflow, "_catalog_lock", threading.Lock()):
                            harness.langflow._catalog = None
                    return self._send(200, {
                        "status": "ok",
                        "component_name": name,
                        "file": str(target_file.name),
                    })
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
                        reasoning_effort=data.get("reasoning_effort"),
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
            if path.startswith("/api/sessions/"):
                try:
                    session_id = unquote(path.rsplit("/", 1)[-1])
                    success = harness.store.delete_session(session_id)
                    if not success:
                        return self._error("Session not found", 404)
                    return self._send(200, {"status": "deleted", "id": session_id})
                except Exception as exc:
                    return self._error(exc)
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


def _dispatch_studyui_handler(handler_type, method, path, headers, body):
    """Run the existing StudyUI route handler behind the shared ASGI listener."""
    handler = object.__new__(handler_type)
    handler.command = method
    handler.path = path
    handler.headers = Message()
    for name, value in headers.items():
        handler.headers.add_header(name, value)
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    response = {"status": 500, "headers": {}}

    def send_response(status, message=None):
        response["status"] = int(status)

    def send_header(name, value):
        response["headers"][name] = value

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = lambda: None
    handler.log_message = lambda *args: None
    route = getattr(handler, "do_" + method, None)
    if route is None:
        handler._send(405, {"error": "Method not allowed"})
    else:
        route()
    return response["status"], response["headers"], handler.wfile.getvalue()


def create_app(database, workflows, components, frontend):
    """Serve the StudyUI agent and its workflow canvas through one local listener."""
    from starlette.concurrency import run_in_threadpool

    from .workbench import create_app as create_workbench_app

    project_root = Path(__file__).resolve().parents[5]
    if isinstance(database, (str, Path)):
        db_path = Path(database)
        if not db_path.is_absolute() and not db_path.exists():
            candidate = project_root / db_path
            if candidate.parent.exists() or candidate.exists():
                database = str(candidate)
    workflow_client = FileWorkflowClient(
        workflows or project_root / "workflows",
        components or project_root / ".demo-runtime" / "components",
    )
    harness = StudyUIAgent(database, langflow=workflow_client)

    def run_canvas_workflow(flow_id, payload):
        result = harness.run_canvas_workflow(
            flow_id,
            session_id=payload.get("studyui_session_id"),
        )
        native_result = result.get("workflow_result")
        if not isinstance(native_result, dict):
            native_result = {"flow_id": flow_id, "outputs": []}
        native_result["studyui_run"] = {
            "session_id": result["session_id"],
            "flow_id": flow_id,
            "status": "completed" if result.get("workflow_result") is not None else "agent_report",
            "message": result.get("message", ""),
            "artifacts": result.get("artifacts", []),
            "pending_approvals": result.get("pending_approvals", []),
        }
        return native_result

    handler_type = make_handler(harness, "/canvas")
    app = FastAPI(title="StudyUI")
    app.state.harness = harness
    app.mount(
        "/canvas",
        create_workbench_app(
            Path(workflows or project_root / "workflows"),
            Path(components or project_root / ".demo-runtime" / "components"),
            Path(frontend or project_root / ".demo-runtime" / "workbench-ui"),
            workflow_run_handler=run_canvas_workflow,
        ),
    )

    @app.post("/api/sessions/{session_id}/messages")
    async def post_session_message_route(session_id: str, request: Request):
        from urllib.parse import unquote
        clean_id = unquote(session_id)
        if not harness.store.has_session(clean_id):
            return Response(content=json.dumps({"error": "Conversation does not exist"}, ensure_ascii=False).encode(), status_code=404, media_type="application/json")
        try:
            data = await request.json()
        except Exception:
            return Response(content=json.dumps({"error": "Malformed JSON"}, ensure_ascii=False).encode(), status_code=400, media_type="application/json")

        user_msg = data.get("message")
        accept = request.headers.get("accept", "")
        stream_requested = "text/event-stream" in accept or request.query_params.get("stream") == "true"

        if not stream_requested:
            try:
                res = await run_in_threadpool(harness.run_turn, clean_id, user_msg)
                return Response(content=json.dumps(res, ensure_ascii=False).encode(), status_code=200, media_type="application/json")
            except Exception as exc:
                return Response(content=json.dumps({"error": str(exc)}, ensure_ascii=False).encode(), status_code=400, media_type="application/json")

        from starlette.responses import StreamingResponse

        async def event_generator():
            import asyncio
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def progress_cb(evt):
                loop.call_soon_threadsafe(queue.put_nowait, evt)

            async def runner():
                try:
                    res = await run_in_threadpool(harness.run_turn, clean_id, user_msg, on_progress=progress_cb)
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "done", "result": res})
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(exc)})
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            asyncio.create_task(runner())
            yield f"event: start\ndata: {json.dumps({'session_id': clean_id}, ensure_ascii=False)}\n\n".encode("utf-8")

            while True:
                item = await queue.get()
                if item is None:
                    break
                evt_type = item.get("type", "message")
                payload = json.dumps(item, ensure_ascii=False)
                yield f"event: {evt_type}\ndata: {payload}\n\n".encode("utf-8")

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    @app.api_route(
        "/{path:path}", methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS", "PUT"]
    )
    async def studyui_routes(request: Request, path: str = ""):
        request_path = request.url.path
        if request.url.query:
            request_path += "?" + request.url.query
        status, response_headers, content = await run_in_threadpool(
            _dispatch_studyui_handler,
            handler_type,
            request.method,
            request_path,
            dict(request.headers.items()),
            await request.body(),
        )
        headers = {
            name: value
            for name, value in response_headers.items()
            if name.lower() not in {"content-length", "transfer-encoding"}
        }
        return Response(content=content, status_code=status, headers=headers)

    return app


def serve(
    host="127.0.0.1",
    port=7880,
    database=".demo-runtime/agent.sqlite3",
    workflows=None,
    components=None,
    frontend=None,
):
    import uvicorn

    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("StudyUI must bind to loopback")
    app = create_app(database, workflows, components, frontend)
    print(f"StudyUI ready: http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, access_log=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("STUDYUI_PORT", "7880")))
    parser.add_argument(
        "--database", default=os.environ.get("STUDYUI_DATABASE", ".demo-runtime/agent.sqlite3")
    )
    parser.add_argument("--workflows", default=os.environ.get("STUDYUI_WORKFLOWS_DIR"))
    parser.add_argument("--components", default=os.environ.get("STUDYUI_COMPONENTS_DIR"))
    parser.add_argument("--frontend", default=os.environ.get("STUDYUI_FRONTEND_DIR"))
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    serve(args.host, args.port, args.database, args.workflows, args.components, args.frontend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
