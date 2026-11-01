from __future__ import annotations


PAGE_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="rbackup-token" content="__TOKEN__">
<title>rbackup 配置</title>
<style>
  :root {
    --bg: #f5f7fb;
    --card: #ffffff;
    --text: #172033;
    --muted: #667085;
    --line: #e4e9f1;
    --soft: #f2f5fa;
    --accent: #2457d6;
    --accent-strong: #1b46b4;
    --ok: #08775a;
    --ok-bg: #e8f7f0;
    --warn: #a55a00;
    --warn-bg: #fff5df;
    --err: #b42318;
    --err-bg: #fef0ef;
    --shadow: 0 10px 30px rgba(22, 35, 58, .06);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1420;
      --card: #161e2e;
      --text: #e7ecf5;
      --muted: #98a4b8;
      --line: #2a3548;
      --soft: #1c2638;
      --accent: #7aa2ff;
      --accent-strong: #9ab8ff;
      --ok: #6ee7b7;
      --ok-bg: #12352b;
      --warn: #fbbf24;
      --warn-bg: #3a2a0c;
      --err: #fca5a5;
      --err-bg: #3b1717;
      --shadow: 0 10px 30px rgba(0, 0, 0, .25);
    }
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font: 14px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
  }
  code { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
  .wrap { max-width: 1060px; margin: 0 auto; padding: 30px 20px 90px; }
  .hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 18px; }
  .eyebrow { margin: 0 0 4px; color: var(--accent); font-size: 12px; letter-spacing: .14em; text-transform: uppercase; font-weight: 700; }
  h1 { margin: 0; font-size: 30px; letter-spacing: -.02em; }
  .hero p { margin: 7px 0 0; color: var(--muted); max-width: 680px; }
  .hero-status { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
  .badge { display: inline-flex; align-items: center; border: 1px solid var(--line); background: var(--card); color: var(--muted); border-radius: 999px; padding: 5px 10px; font-size: 12px; white-space: nowrap; }
  .badge.dirty { color: var(--warn); background: var(--warn-bg); border-color: transparent; }
  .pathbar { display: flex; gap: 10px; align-items: baseline; padding: 11px 14px; margin-bottom: 16px; background: var(--soft); border: 1px solid var(--line); border-radius: 10px; color: var(--muted); overflow-wrap: anywhere; }
  .pathbar code { color: var(--text); }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 22px; margin: 0 0 16px; box-shadow: var(--shadow); }
  .card h2 { margin: 0 0 4px; font-size: 18px; }
  .card .sub { margin: 0 0 18px; color: var(--muted); font-size: 13px; }
  .section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
  .section-head h2 { margin-bottom: 4px; }
  .section-head p { margin: 0; color: var(--muted); font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
  .grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .field > span, .field > label { color: var(--muted); font-size: 12px; font-weight: 650; letter-spacing: .02em; }
  .field small { color: var(--muted); font-size: 11px; }
  .inline { display: flex; gap: 8px; align-items: stretch; }
  .inline input { flex: 1; min-width: 0; }
  input[type="text"], input[type="number"], textarea, select {
    width: 100%; color: var(--text); background: var(--bg); border: 1px solid var(--line);
    border-radius: 9px; padding: 9px 11px; font: inherit; outline: none; transition: border-color .15s, box-shadow .15s;
  }
  input[type="text"]:focus, input[type="number"]:focus, textarea:focus, select:focus {
    border-color: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
  }
  textarea { resize: vertical; min-height: 58px; }
  .checkline { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 13px; padding: 7px 0; }
  .checkline input { width: 16px; height: 16px; accent-color: var(--accent); }
  button {
    appearance: none; border: 1px solid var(--line); border-radius: 9px; padding: 8px 13px;
    background: var(--card); color: var(--text); font: inherit; font-weight: 650; cursor: pointer;
    transition: background .15s, border-color .15s, transform .05s; white-space: nowrap;
  }
  button:hover { background: var(--soft); }
  button:active { transform: translateY(1px); }
  button:disabled { opacity: .5; cursor: not-allowed; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button.primary:hover { background: var(--accent-strong); }
  button.danger { color: var(--err); }
  button.danger:hover { background: var(--err-bg); }
  button.small { padding: 6px 10px; font-size: 12px; }
  .category-card { border: 1px dashed var(--line); border-radius: 12px; padding: 14px; margin-bottom: 12px; background: color-mix(in srgb, var(--soft) 55%, transparent); }
  .cat-head { display: grid; grid-template-columns: 190px minmax(0, 1fr) auto auto; gap: 12px; align-items: end; }
  .cat-foot { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: end; margin-top: 12px; }
  .switch { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 12px; padding-bottom: 8px; white-space: nowrap; }
  .switch input { width: 16px; height: 16px; accent-color: var(--accent); }
  .status-grid { display: grid; grid-template-columns: 180px 180px minmax(0, 1fr); gap: 16px; align-items: start; }
  .status-item { min-width: 0; }
  .status-item .k { color: var(--muted); font-size: 12px; display: block; margin-bottom: 5px; }
  .status-item .v { font-weight: 700; overflow-wrap: anywhere; }
  .status-item .v.good { color: var(--ok); }
  .status-item .v.bad { color: var(--err); }
  .status-item .v.warn { color: var(--warn); }
  .status-item code { overflow-wrap: anywhere; }
  .actions {
    position: sticky; bottom: 0; z-index: 5; display: flex; gap: 10px; justify-content: flex-end;
    padding: 14px 0 0; background: linear-gradient(to bottom, transparent, var(--bg) 35%);
  }
  .message { border-radius: 11px; padding: 12px 14px; margin: 0 0 16px; border: 1px solid transparent; white-space: pre-wrap; }
  .message.ok { background: var(--ok-bg); color: var(--ok); }
  .message.warn { background: var(--warn-bg); color: var(--warn); }
  .message.error { background: var(--err-bg); color: var(--err); }
  .checks { display: flex; flex-direction: column; gap: 8px; }
  .check { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 10px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 9px; background: var(--bg); }
  .check .mark { font-size: 11px; font-weight: 800; letter-spacing: .06em; }
  .check.ok .mark { color: var(--ok); }
  .check.warn .mark { color: var(--warn); }
  .check.fail .mark { color: var(--err); }
  .check .detail { overflow-wrap: anywhere; }
  .muted { color: var(--muted); }
  .tiny { font-size: 12px; }
  details.card { padding: 0; overflow: hidden; }
  details.card summary { cursor: pointer; padding: 20px 22px; font-weight: 700; list-style: none; }
  details.card summary::-webkit-details-marker { display: none; }
  details.card summary::after { content: "展开"; float: right; color: var(--muted); font-weight: 500; font-size: 12px; }
  details.card[open] summary::after { content: "收起"; }
  .details-body { padding: 0 22px 22px; }
  .footer { color: var(--muted); font-size: 12px; margin-top: 18px; line-height: 1.7; }
  .toolbar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 0 0 14px; padding: 11px 13px; background: var(--soft); border: 1px solid var(--line); border-radius: 11px; }
  .toolbar .grow { flex: 1; min-width: 0; }
  .toolbar label.checkline { padding: 0; }
  .toolbar .field { min-width: 200px; }
  .difftable { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
  .difftable th, .difftable td { text-align: left; padding: 7px 9px; border-bottom: 1px solid var(--line); vertical-align: top; }
  .difftable th { color: var(--muted); font-size: 12px; font-weight: 700; }
  .difftable td.path { overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
  .difftable td.num { white-space: nowrap; color: var(--muted); font-size: 12px; }
  .difftable td.mark { width: 34px; }
  .difftable tr:hover td { background: var(--soft); }
  .difftable tbody tr { cursor: pointer; }
  .tag { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px; border: 1px solid var(--line); white-space: nowrap; }
  .tag.same { color: var(--muted); }
  .tag.local { color: var(--ok); background: var(--ok-bg); border-color: transparent; }
  .tag.remote { color: var(--warn); background: var(--warn-bg); border-color: transparent; }
  .tag.modified { color: var(--err); background: var(--err-bg); border-color: transparent; }
  .tag.dir { color: var(--accent); background: var(--soft); }
  .group-title { display: flex; align-items: baseline; gap: 8px; margin: 16px 0 8px; font-size: 13px; font-weight: 700; color: var(--muted); }
  .cat-block + .cat-block { margin-top: 22px; padding-top: 18px; border-top: 1px solid var(--line); }
  .empty { padding: 22px; text-align: center; color: var(--muted); font-size: 13px; border: 1px dashed var(--line); border-radius: 11px; }
  .result-list { margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: var(--muted); }
  @media (max-width: 780px) {
    .hero { display: block; }
    .hero-status { justify-content: flex-start; margin-top: 12px; }
    .grid, .grid.three, .status-grid, .cat-head, .cat-foot { grid-template-columns: 1fr; }
    .cat-head .switch { padding-bottom: 0; }
    .actions { flex-wrap: wrap; }
    .actions button { flex: 1; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div>
      <p class="eyebrow">rbackup</p>
      <h1>备份配置</h1>
      <p>配置 A 明文目录到 B 本地同步目录的 rclone crypt 加密备份。保存前可先运行检查。</p>
    </div>
    <div class="hero-status">
      <span id="dirty" class="badge">已加载</span>
      <span id="config-exists" class="badge">配置文件</span>
    </div>
  </header>

  <div class="pathbar">配置文件 <code id="config-path">加载中…</code></div>
  <div id="message" class="message" hidden></div>

  <form id="config-form" autocomplete="off">
    <section class="card">
      <h2>基本设置</h2>
      <p class="sub">B 由 rclone crypt 透明加密；网盘客户端负责把 B 同步到云端。</p>
      <div class="grid">
        <label class="field">
          <span>设备名 device</span>
          <input id="device" type="text" placeholder="my-laptop">
          <small>每台设备唯一；会成为 B 内的设备前缀。</small>
        </label>
        <div class="field">
          <span>rclone crypt remote</span>
          <div class="inline">
            <input id="remote" type="text" list="remote-list" placeholder="b_crypt">
            <button id="refresh-remotes" type="button" class="small">刷新</button>
            <button id="inspect-remote" type="button" class="small">检测 B</button>
          </div>
          <datalist id="remote-list"></datalist>
          <small>必须是 crypt remote；底层 remote 指向 B 本地目录的绝对路径。</small>
        </div>
        <label class="field">
          <span>rclone 可执行文件</span>
          <input id="rclone-bin" type="text" placeholder="rclone">
          <small>留空不推荐；可填绝对路径。</small>
        </label>
        <label class="field">
          <span>rclone.conf（可选）</span>
          <input id="rclone-config" type="text" placeholder="留空使用 rclone 默认配置">
        </label>
        <label class="field">
          <span>轮询间隔（秒）</span>
          <input id="poll-interval" type="number" min="1" max="86400" step="1">
          <small>B 在本地时建议 2-5 秒。</small>
        </label>
        <label class="field">
          <span>限速 bwlimit（可选）</span>
          <input id="bwlimit" type="text" placeholder="例如 8M:off">
        </label>
      </div>
      <div class="grid three" style="margin-top:16px">
        <label class="field"><span>并发传输 transfers</span><input id="transfers" type="number" min="1" max="64"></label>
        <label class="field"><span>并发检查 checkers</span><input id="checkers" type="number" min="1" max="64"></label>
        <label class="field"><span>重试 retries</span><input id="retries" type="number" min="0" max="20"></label>
      </div>
    </section>

    <section class="card">
      <div class="section-head">
        <div>
          <h2>B 本地同步目录</h2>
          <p>从 crypt remote 的底层 remote 自动识别；A 与 B 不能相同或互相嵌套。</p>
        </div>
        <span class="badge" id="b-badge">未检测</span>
      </div>
      <div class="status-grid">
        <div class="status-item"><span class="k">remote 类型</span><span id="remote-type" class="v">未检测</span></div>
        <div class="status-item"><span class="k">B 目录状态</span><span id="b-status" class="v">未检测</span></div>
        <div class="status-item"><span class="k">B 路径</span><code id="b-path" class="v">未检测</code></div>
      </div>
      <p class="tiny muted" style="margin:12px 0 0">B 内的 <code>_versions</code> 和 <code>_state</code> 会占用本地磁盘，并随 B 同步上云。</p>
    </section>

    <section class="card">
      <div class="section-head">
        <div>
          <h2>数据类别</h2>
          <p>每个类别对应 B 内的 <code>&lt;device&gt;/&lt;类别&gt;/</code>。排除规则每行一个，使用 rclone 语法。</p>
        </div>
        <button id="add-category" type="button">+ 添加类别</button>
      </div>
      <div id="categories"></div>
    </section>

    <details class="card">
      <summary>高级设置</summary>
      <div class="details-body">
        <div class="grid">
          <label class="field"><span>状态前缀</span><input id="state-prefix" type="text" placeholder="_state"><small>B 内状态目录名，默认 _state。</small></label>
          <label class="field"><span>版本前缀</span><input id="versions-prefix" type="text" placeholder="_versions"><small>B 内历史版本目录名，默认 _versions。</small></label>
          <label class="field"><span>保留版本数</span><input id="keep-versions" type="number" min="1" max="100000"><small>prune 默认保留最新 N 个版本。</small></label>
          <div class="field">
            <span>行为</span>
            <label class="checkline"><input id="create-empty-dirs" type="checkbox"> 备份空目录</label>
            <label class="checkline"><input id="follow-symlinks" type="checkbox"> 跟随符号链接（可能递归）</label>
          </div>
        </div>
      </div>
    </details>

    <div class="actions">
      <button id="reload" type="button">重新加载</button>
      <button id="check" type="button">检查配置</button>
      <button id="save" type="button" class="primary">保存配置</button>
    </div>
  </form>

  <section id="browser" class="card">
    <div class="section-head">
      <div>
        <h2>对比与操作</h2>
        <p>
          A（明文）与 B（当前版本）逐项对比。上传会把被覆盖的旧内容留在
          <code>_versions</code>；“从 B 删除”会同步到云端且不留版本；
          “从 A 删除”只动本机明文，B 中的备份仍然保留。文件和文件夹都支持。
        </p>
      </div>
    </div>
    <div class="toolbar">
      <label class="field">
        <span>类别</span>
        <select id="browse-category"></select>
      </label>
      <button id="load-diff" type="button" class="primary">对比</button>
      <button id="run-backup" type="button">整类别备份到 B</button>
      <label class="checkline"><input id="force-backup" type="checkbox"> 覆盖远端漂移</label>
      <label class="checkline"><input id="only-diff" type="checkbox" checked> 只看差异</label>
      <label class="checkline"><input id="dry-run" type="checkbox"> 仅预演</label>
    </div>
    <div id="diff-summary" class="tiny muted" style="margin-bottom:12px">尚未对比。</div>
    <div class="toolbar" id="diff-toolbar" hidden>
      <label class="checkline"><input id="select-all" type="checkbox"> 全选</label>
      <span id="selection-count" class="tiny muted">已选 0 项</span>
      <span class="grow"></span>
      <button id="upload-selected" type="button" class="small primary">上传到 B</button>
      <button id="delete-selected" type="button" class="small danger">从 B 删除</button>
      <button id="delete-local-selected" type="button" class="small danger">从 A 删除</button>
      <button id="rebaseline" type="button" class="small">重设基线</button>
    </div>
    <div id="diff-body"></div>
  </section>

  <section id="result" class="card" hidden>
    <h2>检查结果</h2>
    <p class="sub" id="result-summary"></p>
    <div id="checks" class="checks"></div>
  </section>

  <p class="footer">
    页面只监听 127.0.0.1，并使用一次性访问令牌。配置保存后可在终端运行
    <code>rbackup backup --dry-run</code> 预览备份。<br>
    关闭终端或按 Ctrl+C 停止配置页。
  </p>
</div>

<script>
(() => {
  "use strict";
  const token = document.querySelector('meta[name="rbackup-token"]').content;
  const $ = (id) => document.getElementById(id);
  let busy = false;
  let dirty = false;
  let currentPayload = null;
  let diffData = null;

  async function api(path, options = {}) {
    const headers = Object.assign({ "X-RBackup-Token": token }, options.headers || {});
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    let response;
    try {
      response = await fetch(path, Object.assign({}, options, { headers }));
    } catch (err) {
      throw new Error("无法连接配置服务：" + err);
    }
    const text = await response.text();
    let data = {};
    if (text) {
      try { data = JSON.parse(text); } catch (_) { data = {}; }
    }
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || ("HTTP " + response.status));
    }
    return data;
  }

  function showMessage(kind, text) {
    const box = $("message");
    box.className = "message " + kind;
    box.textContent = text;
    box.hidden = false;
  }

  function clearMessage() {
    const box = $("message");
    box.hidden = true;
    box.textContent = "";
  }

  function setDirty(value) {
    dirty = value;
    const badge = $("dirty");
    badge.textContent = value ? "有未保存修改" : "未修改";
    badge.className = "badge" + (value ? " dirty" : "");
  }

  function markDirty() { setDirty(true); }

  function setBusy(value) {
    busy = value;
    ["reload", "check", "save", "refresh-remotes", "inspect-remote", "add-category",
     "load-diff", "run-backup", "upload-selected", "delete-selected",
     "delete-local-selected", "rebaseline", "force-backup"].forEach((id) => {
      const el = $(id);
      if (el) el.disabled = value;
    });
    document.querySelectorAll(".category-card button").forEach((el) => {
      if (value) el.disabled = true;
    });
  }

  function textValue(id) {
    return $(id).value;
  }

  function numberValue(id) {
    const value = $(id).value.trim();
    return value === "" ? null : Number(value);
  }

  function collect() {
    const categories = Array.from(document.querySelectorAll(".category-card")).map((card) => ({
      name: card.querySelector(".cat-name").value.trim(),
      path: card.querySelector(".cat-path").value,
      excludes: card.querySelector(".cat-excludes").value
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean),
      enabled: card.querySelector(".cat-enabled").checked,
    }));
    return {
      device: textValue("device"),
      remote: textValue("remote"),
      rclone_bin: textValue("rclone-bin"),
      rclone_config: textValue("rclone-config"),
      poll_interval: numberValue("poll-interval"),
      transfers: numberValue("transfers"),
      checkers: numberValue("checkers"),
      retries: numberValue("retries"),
      bwlimit: textValue("bwlimit"),
      state_prefix: textValue("state-prefix"),
      versions_prefix: textValue("versions-prefix"),
      follow_symlinks: $("follow-symlinks").checked,
      create_empty_dirs: $("create-empty-dirs").checked,
      keep_versions: numberValue("keep-versions"),
      categories,
    };
  }

  function fill(payload) {
    currentPayload = payload;
    $("device").value = payload.device || "";
    $("remote").value = payload.remote || "";
    $("rclone-bin").value = payload.rclone_bin || "";
    $("rclone-config").value = payload.rclone_config || "";
    $("poll-interval").value = payload.poll_interval ?? "";
    $("transfers").value = payload.transfers ?? "";
    $("checkers").value = payload.checkers ?? "";
    $("retries").value = payload.retries ?? "";
    $("bwlimit").value = payload.bwlimit || "";
    $("state-prefix").value = payload.state_prefix || "";
    $("versions-prefix").value = payload.versions_prefix || "";
    $("keep-versions").value = payload.keep_versions ?? "";
    $("follow-symlinks").checked = Boolean(payload.follow_symlinks);
    $("create-empty-dirs").checked = Boolean(payload.create_empty_dirs);
    renderCategories(payload.categories || []);
    fillCategorySelect();
  }

  function makeCategoryCard(category) {
    const card = document.createElement("div");
    card.className = "category-card";
    card.innerHTML = `
      <div class="cat-head">
        <label class="field"><span>类别名</span><input class="cat-name" type="text" placeholder="documents"></label>
        <label class="field"><span>A 目录（明文）</span><input class="cat-path" type="text" placeholder="C:/Users/me/Documents"></label>
        <label class="switch"><input class="cat-enabled" type="checkbox"> 启用</label>
        <button class="danger small remove-cat" type="button">删除</button>
      </div>
      <div class="cat-foot">
        <label class="field"><span>排除规则（每行一个）</span><textarea class="cat-excludes" rows="2" placeholder="**/.git/**"></textarea></label>
        <span class="tiny muted">rclone --exclude 语法</span>
      </div>`;
    card.querySelector(".cat-name").value = category.name || "";
    card.querySelector(".cat-path").value = category.path || "";
    card.querySelector(".cat-enabled").checked = category.enabled !== false;
    card.querySelector(".cat-excludes").value = (category.excludes || []).join("\n");
    card.querySelectorAll("input, textarea").forEach((el) => {
      el.addEventListener("input", markDirty);
      el.addEventListener("change", markDirty);
    });
    card.querySelector(".remove-cat").addEventListener("click", () => {
      card.remove();
      updateCategoryButtons();
      fillCategorySelect();
      markDirty();
    });
    return card;
  }

  function renderCategories(categories) {
    const host = $("categories");
    host.replaceChildren();
    categories.forEach((cat) => host.appendChild(makeCategoryCard(cat)));
    if (!categories.length) addCategory();
    updateCategoryButtons();
  }

  function updateCategoryButtons() {
    const cards = document.querySelectorAll(".category-card");
    cards.forEach((card) => {
      const button = card.querySelector(".remove-cat");
      if (button) button.disabled = cards.length <= 1 || busy;
    });
  }

  function addCategory() {
    const host = $("categories");
    const index = host.querySelectorAll(".category-card").length + 1;
    host.appendChild(makeCategoryCard({
      name: "category_" + index,
      path: "",
      excludes: [],
      enabled: true,
    }));
    updateCategoryButtons();
    fillCategorySelect();
    markDirty();
    const latest = host.lastElementChild;
    if (latest) latest.querySelector(".cat-name").focus();
  }

  function setBInfo(data) {
    const type = data.type || "未知";
    $("remote-type").textContent = type;
    $("remote-type").className = "v " + (type === "crypt" ? "good" : "bad");
    const bPath = data.b_path;
    $("b-path").textContent = bPath || "（crypt 直接指向云端）";
    const badge = $("b-badge");
    const status = $("b-status");
    if (!bPath) {
      badge.textContent = "云端模式";
      badge.className = "badge";
      status.textContent = "未检测到本地 B；crypt remote 直接指向云端";
      status.className = "v";
    } else if (data.b_exists && data.b_is_dir) {
      badge.textContent = "本地 B";
      badge.className = "badge";
      status.textContent = "目录存在";
      status.className = "v good";
    } else {
      badge.textContent = "B 不可用";
      badge.className = "badge dirty";
      status.textContent = "目录不存在或不是目录";
      status.className = "v bad";
    }
  }

  function clearBInfo() {
    $("remote-type").textContent = "未检测";
    $("remote-type").className = "v";
    $("b-path").textContent = "未检测";
    $("b-status").textContent = "未检测";
    $("b-status").className = "v";
    $("b-badge").textContent = "未检测";
    $("b-badge").className = "badge";
  }

  async function refreshRemotes(show) {
    const data = await api("/api/remotes", {
      method: "POST",
      body: JSON.stringify({
        rclone_bin: textValue("rclone-bin"),
        rclone_config: textValue("rclone-config"),
      }),
    });
    const list = $("remote-list");
    list.replaceChildren();
    (data.remotes || []).forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      list.appendChild(option);
    });
    if (show) showMessage("ok", "已刷新 rclone remotes：" + ((data.remotes || []).join(", ") || "无"));
  }

  async function inspectRemote(show) {
    const remote = textValue("remote").trim();
    if (!remote) {
      clearBInfo();
      if (show) showMessage("warn", "请先填写 remote。");
      return;
    }
    const data = await api("/api/remote-info", {
      method: "POST",
      body: JSON.stringify({
        remote,
        rclone_bin: textValue("rclone-bin"),
        rclone_config: textValue("rclone-config"),
      }),
    });
    setBInfo(data);
    if (show) showMessage(data.type === "crypt" ? "ok" : "warn",
      data.type === "crypt" ? "已识别 crypt remote。" : "该 remote 不是 crypt，不能用于备份。");
  }

  function renderChecks(checks, passed) {
    $("result").hidden = false;
    $("result-summary").textContent = passed ? "关键检查通过。" : "存在关键检查失败，请修正后再备份。";
    const host = $("checks");
    host.replaceChildren();
    (checks || []).forEach((check) => {
      const row = document.createElement("div");
      row.className = "check " + (check.ok ? "ok" : (check.critical ? "fail" : "warn"));
      const mark = document.createElement("span");
      mark.className = "mark";
      mark.textContent = check.ok ? "OK" : (check.critical ? "FAIL" : "WARN");
      const detail = document.createElement("span");
      detail.className = "detail";
      detail.textContent = check.name + "：" + check.detail;
      row.append(mark, detail);
      host.appendChild(row);
    });
  }

  async function loadConfig() {
    const data = await api("/api/config");
    fill(data.payload);
    $("config-path").textContent = data.path;
    $("config-exists").textContent = data.exists
      ? (data.load_error ? "配置无效" : "已保存")
      : "新建配置";
    setDirty(false);
    if (data.load_error) {
      showMessage("error", "现有配置无法加载，已显示默认值：\n" + data.load_error);
    } else {
      clearMessage();
    }
    try { await inspectRemote(false); } catch (_) { clearBInfo(); }
  }

  async function checkConfig() {
    const data = await api("/api/check", {
      method: "POST",
      body: JSON.stringify({ payload: collect() }),
    });
    renderChecks(data.checks, data.passed);
    if (data.b_path) {
      $("b-path").textContent = data.b_path;
      $("b-badge").textContent = "本地 B";
    }
    showMessage(data.passed ? "ok" : "warn",
      data.passed ? "检查通过，可以保存。" : "检查完成，但有关键问题需要处理。");
  }

  async function saveConfig() {
    const data = await api("/api/save", {
      method: "POST",
      body: JSON.stringify({ payload: collect() }),
    });
    $("config-path").textContent = data.path;
    $("config-exists").textContent = "已保存";
    setDirty(false);
    if (data.payload) fill(data.payload);
    showMessage("ok", "配置已保存。" + (data.backup ? " 旧配置备份：" + data.backup : ""));
    try { await inspectRemote(false); } catch (_) { clearBInfo(); }
  }

  async function reloadConfig() {
    if (dirty && !confirm("有未保存修改，确定重新加载？")) return;
    const data = await api("/api/reload");
    fill(data.payload);
    $("config-path").textContent = data.path;
    $("config-exists").textContent = data.exists
      ? (data.load_error ? "配置无效" : "已保存")
      : "新建配置";
    setDirty(false);
    clearMessage();
    if (data.load_error) showMessage("error", "配置无法加载：" + data.load_error);
    try { await inspectRemote(false); } catch (_) { clearBInfo(); }
  }

  // ---- A/B 对比与操作 ------------------------------------------------

  const FILE_TAG = { same: "same", modified: "modified", local_only: "local", remote_only: "remote" };
  const DIR_TAG = {
    both: ["same", "两边都有"],
    local: ["local", "只在 A"],
    remote: ["remote", "只在 B"],
  };

  function fillCategorySelect() {
    const select = $("browse-category");
    if (!select) return;
    const previous = select.value;
    const names = Array.from(document.querySelectorAll(".category-card .cat-name"))
      .map((el) => el.value.trim())
      .filter(Boolean);
    select.replaceChildren();
    names.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      select.appendChild(option);
    });
    if (previous && names.includes(previous)) select.value = previous;
  }

  function formatSize(value) {
    if (value === null || value === undefined) return "—";
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let size = Number(value);
    let index = 0;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
    return (index === 0 ? String(Math.round(size)) : size.toFixed(1)) + " " + units[index];
  }

  function dirState(item) {
    if (item.in_a && item.in_b) return "both";
    return item.in_a ? "local" : "remote";
  }

  function makeTag(className, text) {
    const tag = document.createElement("span");
    tag.className = "tag " + className;
    tag.textContent = text;
    return tag;
  }

  function makeTable(kind, rows) {
    const table = document.createElement("table");
    table.className = "difftable";
    const colgroup = document.createElement("colgroup");
    [34, 0, 130, 92, 92].forEach((width) => {
      const col = document.createElement("col");
      if (width) col.style.width = width + "px";
      colgroup.appendChild(col);
    });
    table.appendChild(colgroup);

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    const titles = kind === "dir"
      ? ["", "文件夹", "状态", "A", "B"]
      : ["", "文件", "状态", "A 大小", "B 大小"];
    titles.forEach((titleText) => {
      const th = document.createElement("th");
      th.textContent = titleText;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    rows.forEach((item) => tbody.appendChild(makeRow(kind, item)));
    table.appendChild(tbody);
    return table;
  }

  function makeRow(kind, item) {
    const tr = document.createElement("tr");

    const markCell = document.createElement("td");
    markCell.className = "mark";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "row-check";
    box.dataset.path = item.path;
    box.dataset.kind = kind;
    box.addEventListener("change", updateSelection);
    markCell.appendChild(box);

    const pathCell = document.createElement("td");
    pathCell.className = "path";
    pathCell.textContent = item.path;

    const stateCell = document.createElement("td");
    const wrap = document.createElement("span");
    wrap.style.display = "inline-flex";
    wrap.style.gap = "4px";
    wrap.style.alignItems = "center";
    if (kind === "dir") {
      wrap.appendChild(makeTag("dir", "目录"));
      const [tagClass, label] = DIR_TAG[dirState(item)];
      wrap.appendChild(makeTag(tagClass, label));
    } else {
      wrap.appendChild(makeTag(FILE_TAG[item.state] || "same", item.label || item.state));
    }
    stateCell.appendChild(wrap);

    const aCell = document.createElement("td");
    aCell.className = "num";
    const bCell = document.createElement("td");
    bCell.className = "num";
    if (kind === "dir") {
      aCell.textContent = item.in_a ? "有" : "—";
      bCell.textContent = item.in_b ? "有" : "—";
    } else {
      aCell.textContent = item.local_size === null ? "—" : formatSize(item.local_size);
      bCell.textContent = item.remote_size === null ? "—" : formatSize(item.remote_size);
    }

    tr.append(markCell, pathCell, stateCell, aCell, bCell);
    tr.addEventListener("click", (event) => {
      if (event.target && event.target.tagName === "INPUT") return;
      box.checked = !box.checked;
      updateSelection();
    });
    return tr;
  }

  function summarizeDiff(data) {
    const totals = { same: 0, modified: 0, local_only: 0, remote_only: 0, dirs: 0 };
    (data.categories || []).forEach((cat) => {
      const counts = cat.counts || {};
      totals.same += counts.same || 0;
      totals.modified += counts.modified || 0;
      totals.local_only += counts.local_only || 0;
      totals.remote_only += counts.remote_only || 0;
      totals.dirs += (cat.dirs || []).length;
    });
    const parts = [
      "一致 " + totals.same,
      "有差异 " + totals.modified,
      "只在 A " + totals.local_only,
      "只在 B " + totals.remote_only,
      "文件夹 " + totals.dirs,
    ];
    return parts.join(" · ") + (data.truncated ? "（结果已截断，只显示部分）" : "");
  }

  function renderDiff(data) {
    const host = $("diff-body");
    host.replaceChildren();
    $("diff-summary").textContent = summarizeDiff(data);
    $("diff-toolbar").hidden = false;
    const onlyDiff = $("only-diff").checked;

    (data.categories || []).forEach((cat) => {
      const block = document.createElement("div");
      block.className = "cat-block";

      const head = document.createElement("div");
      head.className = "group-title";
      const name = document.createElement("span");
      name.textContent = cat.name;
      const source = document.createElement("span");
      source.className = "tiny muted";
      source.textContent = "A: " + cat.local_path;
      head.append(name, source);
      block.appendChild(head);

      if (cat.local_missing) {
        const warn = document.createElement("div");
        warn.className = "message warn";
        warn.textContent = "A 目录不存在，下面只列出 B 中的内容。";
        block.appendChild(warn);
      }

      const dirs = (cat.dirs || []).filter((item) => !onlyDiff || dirState(item) !== "both");
      const files = (cat.files || []).filter((item) => !onlyDiff || item.state !== "same");

      if (!dirs.length && !files.length) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = onlyDiff ? "没有差异。" : "没有内容。";
        block.appendChild(empty);
      }
      if (dirs.length) {
        const title = document.createElement("div");
        title.className = "group-title";
        title.textContent = "文件夹 " + dirs.length;
        block.appendChild(title);
        block.appendChild(makeTable("dir", dirs));
      }
      if (files.length) {
        const title = document.createElement("div");
        title.className = "group-title";
        title.textContent = "文件 " + files.length;
        block.appendChild(title);
        block.appendChild(makeTable("file", files));
      }
      host.appendChild(block);
    });
    updateSelection();
  }

  function selectedRows() {
    return Array.from(document.querySelectorAll(".row-check:checked")).map((el) => ({
      path: el.dataset.path,
      kind: el.dataset.kind,
    }));
  }

  function updateSelection() {
    const boxes = Array.from(document.querySelectorAll(".row-check"));
    const checked = boxes.filter((box) => box.checked);
    $("selection-count").textContent = "已选 " + checked.length + " 项";
    const all = $("select-all");
    all.checked = boxes.length > 0 && checked.length === boxes.length;
    all.indeterminate = checked.length > 0 && checked.length < boxes.length;
  }

  async function loadDiff() {
    const category = $("browse-category").value;
    if (!category) {
      showMessage("warn", "请先添加并填写类别。");
      return;
    }
    const data = await api("/api/diff", {
      method: "POST",
      body: JSON.stringify({ payload: collect(), categories: [category] }),
    });
    diffData = data;
    renderDiff(data);
  }

  async function operate(kind) {
    const category = $("browse-category").value;
    if (!category) {
      showMessage("warn", "请先添加类别。");
      return;
    }
    const rows = selectedRows();
    if (!rows.length) {
      showMessage("warn", "请先勾选要操作的项。");
      return;
    }
    const dry = $("dry-run").checked;
    const isUpload = kind === "upload";
    const isLocal = kind === "delete-local";

    if (!isUpload && !dry) {
      const message = isLocal
        ? "确定从 A（明文源）删除选中的 " + rows.length + " 项？\n\n" +
          "只删本机文件，B 中的备份不受影响，之后仍可恢复。\n" +
          "被删除的内容不会进入任何回收站。"
        : "确定从 B 删除选中的 " + rows.length + " 项？\n\n" +
          "删除会随网盘客户端同步到云端，且不会进入 _versions。";
      if (!confirm(message)) return;
    }

    const endpoint = isUpload ? "/api/upload" : (isLocal ? "/api/delete-local" : "/api/delete");
    const data = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({
        payload: collect(),
        category,
        paths: rows.map((row) => row.path),
        dry_run: dry,
      }),
    });
    const done = (isUpload ? data.uploaded : data.deleted) || 0;
    const failures = (data.results || []).filter((item) => !item.ok);
    const verb = isUpload ? "上传" : (isLocal ? "从 A 删除" : "从 B 删除");
    let text = (dry ? "[预演] " : "") + verb + "完成：" + done + " 项成功";
    if (failures.length) {
      text += "，" + failures.length + " 项失败：\n" + failures.slice(0, 5)
        .map((item) => "  " + item.path + " — " + item.error).join("\n");
    }
    if (data.state_stale) {
      text += "\n提示：B 已变化，基线已过期；可点“整类别备份到 B”或“重设基线”消除漂移。";
    } else if (isLocal && done && !dry) {
      text += "\n提示：这些文件现在只剩 B 里的一份，可随时恢复。";
    }
    showMessage(failures.length ? "warn" : "ok", text);
    await loadDiff();
  }

  async function backupCategory() {
    const category = $("browse-category").value;
    if (!category) {
      showMessage("warn", "请先添加类别。");
      return;
    }
    const force = $("force-backup").checked;
    const extra = force
      ? "\n\n已勾选“覆盖远端漂移”：会用 A 覆盖 B 的同名文件，旧内容进入 _versions。"
      : "\n\n若 B 相对基线发生变化，本次会被拒绝（退出码 3）；确认要覆盖请勾选“覆盖远端漂移”。";
    if (!confirm("把类别 " + category + " 整体备份到 B？" + extra)) return;
    const data = await api("/api/backup", {
      method: "POST",
      body: JSON.stringify({ payload: collect(), categories: [category], force: force }),
    });
    const entry = (data.categories || {})[category] || {};
    showMessage("ok", "备份完成：版本 " + data.version_id + "，" + (entry.files || 0) + " 个文件。");
    await loadDiff();
  }

  async function rebaseline() {
    const category = $("browse-category").value;
    if (!category) {
      showMessage("warn", "请先添加类别。");
      return;
    }
    if (!confirm("用 B 的当前内容重写 _state 基线？\n只改状态文件，不动任何备份数据。")) return;
    const data = await api("/api/rebaseline", {
      method: "POST",
      body: JSON.stringify({ payload: collect(), categories: [category] }),
    });
    showMessage("ok", "基线已重写：" + (data.updated || []).join(", "));
    await loadDiff();
  }

  function wire() {
    $("load-diff").addEventListener("click", () => run(loadDiff));
    $("run-backup").addEventListener("click", () => run(backupCategory));
    $("upload-selected").addEventListener("click", () => run(() => operate("upload")));
    $("delete-selected").addEventListener("click", () => run(() => operate("delete")));
    $("delete-local-selected").addEventListener("click", () => run(() => operate("delete-local")));
    $("rebaseline").addEventListener("click", () => run(rebaseline));
    $("select-all").addEventListener("change", (event) => {
      const checked = event.target.checked;
      document.querySelectorAll(".row-check").forEach((box) => { box.checked = checked; });
      updateSelection();
    });
    $("only-diff").addEventListener("change", () => {
      if (diffData) renderDiff(diffData);
    });
    $("browse-category").addEventListener("change", () => {
      diffData = null;
      $("diff-body").replaceChildren();
      $("diff-toolbar").hidden = true;
      $("diff-summary").textContent = "已切换类别，请重新对比。";
    });
    $("add-category").addEventListener("click", addCategory);
    $("refresh-remotes").addEventListener("click", () => {
      run(async () => refreshRemotes(true));
    });
    $("inspect-remote").addEventListener("click", () => {
      run(async () => inspectRemote(true));
    });
    $("check").addEventListener("click", () => run(checkConfig));
    $("save").addEventListener("click", () => run(saveConfig));
    $("reload").addEventListener("click", () => run(reloadConfig));
    $("remote").addEventListener("change", () => {
      run(async () => inspectRemote(false));
    });
    $("config-form").addEventListener("submit", (event) => event.preventDefault());
    $("config-form").addEventListener("input", markDirty);
    $("config-form").addEventListener("change", markDirty);
    window.addEventListener("beforeunload", (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });
  }

  async function run(fn) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      showMessage("error", err && err.message ? err.message : String(err));
    } finally {
      setBusy(false);
      updateCategoryButtons();
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    wire();
    run(async () => {
      await loadConfig();
      try {
        await refreshRemotes(false);
      } catch (_) {
        // rclone 还没配置好时，检查/保存仍可用。
      }
    });
  });
})();
</script>
</body>
</html>
"""


def render_page(token: str) -> str:
    return PAGE_TEMPLATE.replace("__TOKEN__", token)
