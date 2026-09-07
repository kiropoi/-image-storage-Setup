// 图片分类器前端
let state = null;
let selTags = [];          // 多选标签（同时包含=AND 过滤）
let quickMode = "all";     // all | untagged | failed
let fnameKw = "";          // 文件名搜索关键字
let prevTagging = false;   // 打标状态机（用于完成通知）
let diffGroups = [];       // 差分检测结果：[[path,...], ...]
let activeDiff = -1;       // 当前查看的差分数组下标（-1 = 不按差分过滤）
let diffBusy = false;
let diffView = false;      // true = 网格按 差分组分块显示（文件夹头 + 组内缩略图）
let pollTimer = null;
let catFilter = "all";      // 标签分类筛选：all | 衣服 | 姿势 | 配饰 | 其他
let imgObserver = null;
let loadMoreObserver = null;
let viewerIndex = -1;
let zoom = 1;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      const j = await r.json();
      if (j && typeof j.detail === "string") msg = j.detail;
      else msg = JSON.stringify(j || msg);
    } catch (e) { /* fallthrough */ }
    throw new Error(msg || r.statusText);
  }
  return r.json();
}

// ---------- 缩略图网格（原生懒加载，浏览器按 img 固有比例缩放，绝不变形） ----------
function renderFiles() {
  const grid = $("grid");
  grid.innerHTML = "";
  if (imgObserver) imgObserver.disconnect();
  imgObserver = null;
  if (loadMoreObserver) loadMoreObserver.disconnect();
  loadMoreObserver = null;

  if (!state || !state.files.length) {
    grid.innerHTML = '<div class="empty">请先在上方输入文件夹路径并点「扫描」</div>';
    return;
  }
  // 过滤：差分数组 > 快捷状态(未标/失败) > 多选标签(AND) > 全部；文件名关键字叠加
  let files = state.files;
  if (fnameKw) files = files.filter(f => f.name.toLowerCase().includes(fnameKw));
  if (activeDiff >= 0 && diffGroups[activeDiff]) {
    const inGroup = new Set(diffGroups[activeDiff]);
    files = files.filter(f => inGroup.has(f.path));
  } else if (quickMode === "untagged") {
    files = files.filter(f => !(f.tags && f.tags.length));
  } else if (quickMode === "failed") {
    files = files.filter(f => (f.tags || []).includes("打标失败"));
  } else if (selTags.length) {
    files = files.filter(f => selTags.every(t => f.tags.includes(t)));
  }
  // 分组视图：网格顶部按 差分组 分块，每组一个“文件夹”头（带菜单）
  const showGroups = diffView && diffGroups.length && activeDiff < 0 &&
    !selTags.length && quickMode === "all";
  if (!files.length) {
    grid.innerHTML = '<div class="empty"><span class="ico">🗂️</span>没有匹配的图片<br>换个标签 / 状态 / 清掉文件名搜索试试</div>';
    return;
  }

  imgObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const t = e.target;
      if (e.isIntersecting) {
        t.classList.add("near");   // 进入视野才允许 shimmer
        if (t.dataset.bg) {
          t.style.backgroundImage = 'url("' + t.dataset.bg + '")';
          t.classList.add("ok");      // 关掉 shimmer
          delete t.dataset.bg;
          imgObserver.unobserve(t);
        }
      } else {
        t.classList.remove("near");
      }
    }
  }, { rootMargin: "400px" });

  if (showGroups) {
    const byPath = new Map(files.map(f => [f.path, f]));
    const used = new Set();
    let shownHeads = 0;
    diffGroups.forEach((g, i) => {
      const members = g.map(p => byPath.get(p)).filter(Boolean);
      if (!members.length) return;
      shownHeads++;
      const head = document.createElement("div");
      head.className = "diffhead";
      head.title = "右键或点 ⋯ 打开菜单";
      const name = `差分图组${i + 1}`;
      head.innerHTML =
        `<span class="fico">📁</span><span class="fname">${name}</span>` +
        `<span class="fcount">${members.length} 张</span><span class="fsp"></span>` +
        `<button class="fbtn" title="菜单">⋯</button>`;
      const btn = head.querySelector(".fbtn");
      const openM = (x, y) => openGroupMenuAt(x, y, i, name);
      head.oncontextmenu = (e) => { e.preventDefault(); e.stopPropagation(); openM(e.clientX, e.clientY); };
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const r = btn.getBoundingClientRect();
        openM(r.left, r.bottom + 4);
      });
      grid.appendChild(head);
      for (const f of members) {
        addThumbCard(grid, f);
        used.add(f.path);
      }
    });
    const ungrouped = files.filter(f => !used.has(f.path));
    if (ungrouped.length) {
      const tail = document.createElement("div");
      tail.className = "sechead";
      tail.textContent = `未分组图片（${ungrouped.length}）`;
      grid.appendChild(tail);
      for (const f of ungrouped) addThumbCard(grid, f);
    }
    if (!shownHeads && !ungrouped.length) {
      grid.innerHTML = '<div class="empty">当前没有可显示的图片</div>';
    }
    return;
  }

  if (!files.length) {
    grid.innerHTML = '<div class="empty">没有匹配的图片（换一个分组/标签，或先扫描）</div>';
    return;
  }
  renderFlatChunked(files);
}

// 分块渐进渲染：先渲染一批，滚动接近底部再追加下一批，避免一次性建几千个节点
const RENDER_CHUNK = 240;
function renderFlatChunked(files) {
  const grid = $("grid");
  let pos = 0;
  loadMoreObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      loadMoreObserver.unobserve(e.target);
      e.target.remove();
      addChunk();
      break;
    }
  }, { rootMargin: "800px" });

  function addChunk() {
    const end = Math.min(pos + RENDER_CHUNK, files.length);
    for (let i = pos; i < end; i++) addThumbCard(grid, files[i]);
    pos = end;
    if (pos < files.length) {
      const sent = document.createElement("div");
      sent.className = "loadmore";
      grid.appendChild(sent);
      loadMoreObserver.observe(sent);
    }
  }
  addChunk();
}

function thumbURL(f) {
  const s = "/api/thumbnail?path=" + encodeURIComponent(f.path);
  const off = $("gifoff") && $("gifoff").checked;
  return /\.gif$/i.test(f.path) && off ? s + "&static=1" : s;
}
function addThumbCard(grid, f) {
  const card = document.createElement("div");
  card.className = "card";
  card.dataset.path = f.path;
  const thumb = document.createElement("div");
  thumb.className = "thumb";
  thumb.dataset.bg = thumbURL(f);
  // 悬浮提示：相对子目录 + 标签
  let rel = f.name;
  if (state && state.folder) {
    const base = state.folder.replace(/[\\/]+$/, "");
    if (f.path.toLowerCase().startsWith(base.toLowerCase())) {
      const rest = f.path.slice(base.length).replace(/^[\\/]+/, "").replace(/\\/g, "/");
      if (rest) rel = rest;
    }
  }
  const tip = (rel + "\n" + (f.tags.length ? f.tags.join(" · ") : "（未打标）")).replace(/"/g, "&quot;");
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.innerHTML = `
    <div class="name" title="${tip}">${rel.replace(/"/g, "&quot;")}</div>
    <div class="tags">${f.tags.join(" · ") || "（未打标）"}</div>`;
  card.appendChild(thumb);
  card.appendChild(meta);
  if (isVideo(f.path)) {
    const vb = document.createElement("span");
    vb.className = "vbadge";
    vb.textContent = "视频";
    card.appendChild(vb);
  }
  if (f.tags && f.tags.length) {
    const cnt = document.createElement("span");
    cnt.className = "tagcount";
    cnt.textContent = f.tags.length + " 标签";
    cnt.title = f.tags.join(" · ");
    card.appendChild(cnt);
  }
  card.onclick = () => openViewer(f.path);
  card.oncontextmenu = (e) => { e.preventDefault(); e.stopPropagation(); showCtxMenu(e, f); };
  grid.appendChild(card);
  imgObserver.observe(thumb);
}

// ---------- 标签分类（后端按语义归入大类，前端只负责展示） ----------
const TAG_CAT_LIST = ["人物", "衣服", "配饰", "身体", "发型发色", "眼睛", "表情",
  "姿势动作", "场景", "构图", "物品", "食物", "生物", "其他"];
// 每个分类一个专属颜色（深色 SaaS 调色板，色相尽量拉开）
const CAT_COLORS = {
  "人物": "#5b8def", "衣服": "#e85d75", "配饰": "#c084fc", "身体": "#f472b6",
  "发型发色": "#fbbf24", "眼睛": "#38bdf8", "表情": "#f97316", "姿势动作": "#34d399",
  "场景": "#2dd4bf", "构图": "#94a3b8", "物品": "#a3e635", "食物": "#fb923c",
  "生物": "#4ade80", "其他": "#64748b",
};
const _catColor = (c) => CAT_COLORS[c] || CAT_COLORS["其他"];
function tagCat(tag) {
  // 兜底：后端未返回分类时（旧服务），按文字粗略判断，避免整列丢进「其他」
  const s = tag.toLowerCase();
  for (const k of ["衣服", "裙", "裤", "袜", "泳", "制服", "内衣", "衬衫", "毛衣", "外套"]) if (s.includes(k)) return "衣服";
  for (const k of ["眼镜", "帽子", "项链", "耳环", "戒指", "蝴蝶结", "围巾", "领带", "鞋", "手套", "包"]) if (s.includes(k)) return "配饰";
  for (const k of ["站", "坐", "跪", "躺", "趴", "蹲", "抱", "姿势"]) if (s.includes(k)) return "姿势动作";
  for (const k of ["微笑", "哭", "泪", "脸红", "生气", "笑", "表情"]) if (s.includes(k)) return "表情";
  for (const k of ["头发", "发", "马尾", "辫", "刘海"]) if (s.includes(k)) return "发型发色";
  for (const k of ["眼睛", "瞳", "眼"]) if (s.includes(k)) return "眼睛";
  for (const k of ["胸", "乳", "臀", "腿", "裸", "身体"]) if (s.includes(k)) return "身体";
  for (const k of ["室内", "室外", "天空", "海", "森林", "城市", "背景", "房间"]) if (s.includes(k)) return "场景";
  return "其他";
}
const _catOf = (t) => t.cat || tagCat(t.tag);
function renderCatBar() {
  const bar = $("catbar");
  if (!bar) return;
  const cnt = {}; TAG_CAT_LIST.forEach(c => cnt[c] = 0);
  for (const t of (state.tags || [])) cnt[_catOf(t)]++;
  const total = (state.tags || []).length;
  bar.innerHTML = "";
  const all = document.createElement("button");
  all.className = "cat" + (catFilter === "all" ? " active" : "");
  all.textContent = `全部 ${total}`;
  all.title = "显示全部标签";
  all.onclick = () => { catFilter = "all"; renderCatBar(); renderTags(); };
  bar.appendChild(all);
  for (const c of TAG_CAT_LIST) {
    if (!cnt[c]) continue;                       // 只显示实际存在标签的分类
    const b = document.createElement("button");
    b.className = "cat" + (catFilter === c ? " active" : "");
    b.style.setProperty("--c", _catColor(c));
    const dot = document.createElement("span");
    dot.className = "dot";
    b.appendChild(dot);
    b.appendChild(document.createTextNode(`${c} ${cnt[c]}`));
    b.title = `只看「${c}」类标签`;
    b.onclick = () => { catFilter = c; renderCatBar(); renderTags(); };
    bar.appendChild(b);
  }
}

// ---------- 标签（多选 AND） ----------
function clearTagsFilter() {
  selTags = [];
  $("foldername").value = "";
}
function setTagFilter(tag) {
  if (quickMode !== "all") { quickMode = "all"; updateStats(); }
  const i = selTags.indexOf(tag);
  if (i >= 0) selTags.splice(i, 1); else selTags.push(tag);
  if (selTags.length) { activeDiff = -1; diffView = false; renderDiffList(); }
  $("foldername").value = selTags.length === 1 ? selTags[0] : "";
  renderTags();
  renderFiles();
}
function renderSelChips() {
  const el = $("selchips");
  if (!selTags.length) {
    el.hidden = true;
    $("move").disabled = true;
    return;
  }
  el.hidden = false;
  el.innerHTML = "";
  selTags.forEach(tag => {
    const b = document.createElement("button");
    b.className = "chip";
    b.title = "点击移除该标签";
    b.textContent = tag;
    b.addEventListener("click", () => setTagFilter(tag));
    el.appendChild(b);
  });
  const x = document.createElement("button");
  x.className = "chip clear";
  x.textContent = "清除全部";
  x.title = "移除所有标签筛选";
  x.addEventListener("click", () => { clearTagsFilter(); renderTags(); renderFiles(); });
  el.appendChild(x);
  $("move").disabled = false;
}
function renderTags() {
  const box = $("taglist");
  box.innerHTML = "";
  const kw = $("tagfilter").value.trim().toLowerCase();
  const tags = (state.tags || []).filter(t => {
    if (kw && !t.tag.toLowerCase().includes(kw)) return false;
    if (catFilter !== "all" && _catOf(t) !== catFilter) return false;
    return true;
  });
  for (const t of tags) {
    const b = document.createElement("button");
    b.className = "tagbtn" + (selTags.includes(t.tag) ? " active" : "");
    const cat = _catOf(t);
    b.style.setProperty("--c", _catColor(cat));
    const dot = document.createElement("span");
    dot.className = "dot";
    b.appendChild(dot);
    b.appendChild(document.createTextNode(`${t.tag} (${t.count})` + (catFilter === "all" ? ` · ${cat}` : "")));
    b.title = selTags.includes(t.tag)
      ? "点击取消该标签（当前筛选包含它）"
      : "点击加入多选（同时包含全部所选标签）";
    b.onclick = () => setTagFilter(t.tag);
    b.oncontextmenu = (e) => { e.preventDefault(); e.stopPropagation(); tagManageMenu(e, t.tag); };
    box.appendChild(b);
  }
  if (!tags.length) {
    box.innerHTML = (kw || catFilter !== "all")
      ? '<div class="tempty">没有匹配的标签</div>'
      : '<div class="tempty">暂无标签：先扫描文件夹并打标</div>';
  }
  renderSelChips();
}

// ---------- 状态计数 / 快捷过滤 / 标签管理 / 通知 / 撤销 ----------
function setQuick(m) {
  if (quickMode === m && m !== "all") {
    quickMode = "all";
  } else {
    quickMode = m;
    clearTagsFilter();
    activeDiff = -1;
    diffView = false;
    renderDiffList();
  }
  renderTags();
  renderFiles();
  updateStats();
}
function updateStats() {
  if (!state || !$("statAllN")) return;
  const fs = state.files;
  const n = fs.length;
  const tagged = fs.filter(f => f.tags && f.tags.length).length;
  const fail = fs.filter(f => (f.tags || []).includes("打标失败")).length;
  $("statAllN").textContent = n;
  $("statUnN").textContent = n - tagged;
  $("statFailN").textContent = fail;
  const map = { "all": "stat-all", untagged: "stat-untagged", failed: "stat-failed" };
  for (const k in map) $(map[k]).classList.toggle("active", k === quickMode);
  $("undobtn").hidden = !state.can_undo;
}
function tagManageMenu(e, tag) {
  makeMenu(e.clientX, e.clientY, [
    {
      label: `✏️ 重命名 / 合并到…`,
      fn: async () => {
        const nv = prompt(`把标签「${tag}」改为（若已存在=合并到它）：`, tag);
        if (!nv || nv.trim() === tag) return;
        await api("/api/rename_tag", { method: "POST", body: JSON.stringify({ old: tag, new: nv.trim() }) });
        const i = selTags.indexOf(tag);
        if (i >= 0) selTags[i] = nv.trim();
        await refresh();
      },
    },
    {
      label: `🗑️ 删除标签「${tag}」`,
      fn: async () => {
        if (!confirm(`确定从所有图片上删除标签「${tag}」？`)) return;
        await api("/api/delete_tag", { method: "POST", body: JSON.stringify({ tag }) });
        selTags = selTags.filter(t => t !== tag);
        await refresh();
      },
    },
  ]);
}
function curViewerFile() {
  return fileByPath(viewerPaths[viewerIndex]);
}
async function reloadKeepViewer() {
  const keep = curViewerFile() ? curViewerFile().path : null;
  await refresh();
  if (keep && !$("viewer").hidden) {
    if (viewerPaths.includes(keep)) viewerIndex = viewerPaths.indexOf(keep);
    else { viewerPaths = [keep]; viewerIndex = 0; }
    showViewer();
  }
}
async function vtAddTag() {
  const f = curViewerFile();
  if (!f) return;
  const input = prompt("给这张图手动添加标签（多个用 、 , ， 分隔）：", "");
  if (!input) return;
  const add = input.split(/[,，、\s]+/).map(s => s.trim()).filter(Boolean);
  if (!add.length) return;
  await api("/api/image/tags", { method: "POST", body: JSON.stringify({ path: f.path, add }) });
  await reloadKeepViewer();
  toast(`已添加 ${add.length} 个标签`);
}
async function vtRemoveTag(tag) {
  const f = curViewerFile();
  if (!f) return;
  await api("/api/image/tags", { method: "POST", body: JSON.stringify({ path: f.path, remove: [tag] }) });
  await reloadKeepViewer();
  toast(`已移除「${tag}」`);
}
function tryNotify(title, body) {
  try {
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification(title, { body });
    }
  } catch (e) { /* ignore */ }
}
async function undoMove() {
  try {
    const r = await api("/api/move/undo", { method: "POST", body: "{}" });
    await refresh();
    alert(`已还原 ${r.restored} 张（连同原标签）`);
  } catch (e) { alert("撤销失败: " + e.message); }
}

function renderProgress() {
  const p = state.progress || {};
  const total = p.total || 0;
  const done = p.done || 0;
  const row = document.querySelector(".progress-row");
  row.classList.toggle("idle", !state.tagging && !total);
  $("barfill").style.width = total ? (done / total * 100) + "%" : "0";
  $("progresstext").textContent = state.tagging
    ? `打标中 ${done}/${total} · ${Math.round(done / Math.max(1, total) * 100)}% ${p.current || ""}`
    : (total ? `完成 ${done} 张` : "");
}

function fmtBytes(n) {
  if (!n) return "";
  if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(0) + " KB";
  return n + " B";
}
let modelTimer = null;
function modelUI(m) {
  if (!m) return;
  const bar = $("modelbar");
  if (m.present) { bar.hidden = true; return; }
  bar.hidden = false;
  const btn = $("mdlbtn"), prog = $("mdlprog");
  if (m.active) {
    btn.disabled = true;
    btn.textContent = "下载中…";
    const pct = m.total ? Math.round(m.done / m.total * 100) + "%" : "";
    prog.textContent = m.total
      ? `${fmtBytes(m.done)} / ${fmtBytes(m.total)} ${pct}`
      : `${fmtBytes(m.done)} 已下载`;
  } else {
    btn.disabled = false;
    btn.textContent = "开始下载模型";
    prog.textContent = m.error ? `下载失败：${m.error}（可重试）` : "";
  }
}
async function startModelWatch() {
  if (modelTimer) clearInterval(modelTimer);
  const tick = async () => {
    try {
      const m = await api("/api/model/status");
      modelUI(m);
      if (m.present) {
        clearInterval(modelTimer);
        modelTimer = null;
        await refresh();
      }
    } catch (e) { /* ignore */ }
  };
  modelTimer = setInterval(tick, 1000);
  tick();
}

function renderAll() {
  if (!state) return;
  renderDiffList();
  renderCatBar();
  renderFiles();
  renderTags();
  renderProgress();
  updateStats();
  modelUI(state.model);
  $("threshold").value = state.threshold;
  if (state.folder) $("folder").value = state.folder;
}

async function refresh() {
  state = await api("/api/state");
  renderAll();
}

let scanBusy = false;          // 防连点：扫描请求进行中忽略再次点击

async function scan() {
  if (scanBusy) return;                          // 连续点击只处理第一次
  if (state && state.tagging) { alert("打标进行中：请先点「停止」再扫描"); return; }
  const folder = $("folder").value.trim();
  if (!folder) return alert("请输入文件夹路径");
  const btn = $("scan");
  scanBusy = true;
  btn.disabled = true;
  btn.textContent = "扫描中…";
  try {
    state = await api("/api/scan", {
      method: "POST",
      body: JSON.stringify({
        folder,
        include_sub: $("subfolders").checked,
        include_video: $("includevideo").checked,
      }),
    });
    diffGroups = [];      // 换了扫描目录，旧差分结果作废
    activeDiff = -1;
    diffView = false;
    clearTagsFilter();
    quickMode = "all";
    fnameKw = "";
    $("fname").value = "";
    renderAll();
    toast(`已扫描 ${state.files.length} 张图片`);
  } catch (e) { alert("扫描失败: " + e.message); }
  finally {
    scanBusy = false;
    btn.disabled = false;
    btn.textContent = "扫描";
  }
}

async function startTag() {
  if (state && state.tagging) return;            // 已在打标则忽略连点
  if (state && !state.eva02_available) {
    alert("本地模型还没就绪，请先在顶部完成模型下载");
    return;
  }
  try {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
    const r = await api("/api/tag/start", {
      method: "POST",
      body: JSON.stringify({
        threshold: parseFloat($("threshold").value) || 0.35,
        force: !!($("forcetag") && $("forcetag").checked),
      }),
    });
    if (r.message) alert(r.message);
    startPolling();
  } catch (e) { alert("开始失败: " + e.message); }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(async () => {
    try {
      state = await api("/api/state");
      const was = prevTagging;
      prevTagging = state.tagging;
      if (state.tagging) {
        // 打标进行中：只刷进度/计数，不整页重建网格，避免大图库掉帧
        renderProgress();
        renderCatBar();
        renderTags();
        updateStats();
        modelUI(state.model);
      } else {
        renderAll();                       // 结束：一次性刷新网格（补上标签）
        if (was) {
          const p = state.progress || {};
          if ((p.total || 0) > 0) {
            toast(`打标完成：${p.done || 0} / ${p.total} 张`);
            tryNotify("图片打标完成", `共处理 ${p.done || 0} / ${p.total} 张`);
          }
          stopPolling();
        }
      }
    } catch (e) { /* ignore */ }
  }, 500);
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function stopTag() { await api("/api/tag/stop", { method: "POST" }); }

// ---------- 差分图（同姿势/近似变体归组，浏览与整组移动） ----------
function renderDiffList() {
  const dl = $("difflist");
  const meta = $("diffmeta");
  const bar = $("diffbar");
  const tg = $("difftoggle");
  dl.innerHTML = "";
  if (!diffGroups.length) {
    meta.textContent = diffBusy ? "检测中，请稍候…（大文件夹要几秒到十几秒）" : "";
    bar.hidden = true;
    tg.hidden = true;
    return;
  }
  tg.hidden = false;
  tg.textContent = diffView ? "切回全部缩略图" : "按分组显示缩略图";
  const total = diffGroups.reduce((s, g) => s + g.length, 0);
  meta.textContent = `${diffGroups.length} 组疑似差分 · 共 ${total} 张（在右侧网格中按 📁 分组）`;
  diffGroups.forEach((g, i) => {
    const b = document.createElement("button");
    b.className = "diffrow" + (i === activeDiff ? " active" : "");
    b.textContent = `第${i + 1}组 · ${g.length} 张`;
    b.onclick = () => setDiffActive(i === activeDiff ? -1 : i);
    dl.appendChild(b);
  });
  if (activeDiff >= 0 && diffGroups[activeDiff]) {
    const g = diffGroups[activeDiff];
    bar.hidden = false;
    $("diffinfo").textContent = `第${activeDiff + 1}组（${g.length} 张）→ 目标：`;
    if (!$("difftarget").value) $("difftarget").value = `差分图组${activeDiff + 1}`;
  } else {
    bar.hidden = true;
  }
}
function setDiffActive(i) {
  activeDiff = i;
  diffView = false;                     // 从分组视图切到“只看这一组”的平铺视图
  if (quickMode !== "all") { quickMode = "all"; }
  if (activeDiff >= 0) { clearTagsFilter(); }
  renderTags();
  updateStats();
  renderDiffList();
  renderFiles();
}
let diffPollTimer = null;
async function detectDiff() {
  if (!state || !state.files.length) return alert("请先扫描文件夹");
  if (diffBusy) return;
  diffBusy = true;
  $("diffbtn").textContent = "检测中…";
  $("diffbtn").disabled = true;
  const prog = $("diffprog");
  prog.hidden = false;
  $("dbarfill").style.width = "0";
  $("dbarpct").textContent = "";
  try {
    const thr = Math.max(1, Math.min(64, parseInt($("diffthreshold").value) || 20));
    await api("/api/diff/detect", { method: "POST", body: JSON.stringify({ threshold: thr }) });
    diffPollTimer = setInterval(async () => {
      let st;
      try { st = await api("/api/diff/status"); } catch (e) { return; }
      const p = st.progress || {};
      const total = p.total || 0, done = p.done || 0;
      if (st.running) {
        $("dbarfill").style.width = total ? (done / total * 100) + "%" : "0";
        $("dbarpct").textContent = total
          ? `${done}/${total} · ${Math.round(done / total * 100)}%`
          : "准备中…";
        return;
      }
      clearInterval(diffPollTimer);
      diffPollTimer = null;
      prog.hidden = true;
      diffGroups = st.list || [];
      activeDiff = -1;
      quickMode = "all";
      clearTagsFilter();
      diffView = true;              // 检测完直接进入“按分组看缩略图”
      $("diffsec").open = true;
      updateStats();
      renderTags();
      renderDiffList();
      renderFiles();
      diffBusy = false;
      $("diffbtn").textContent = "检测差分图";
      $("diffbtn").disabled = false;
    }, 250);
  } catch (e) {
    prog.hidden = true;
    diffBusy = false;
    $("diffbtn").textContent = "检测差分图";
    $("diffbtn").disabled = false;
    alert("差分检测失败: " + e.message);
  }
}
async function clearDiff() {
  if (diffPollTimer) { clearInterval(diffPollTimer); diffPollTimer = null; }
  try { await api("/api/diff/clear", { method: "POST", body: "{}" }); } catch (e) { /* ignore */ }
  $("diffprog").hidden = true;
  $("dbarfill").style.width = "0";
  $("dbarpct").textContent = "";
  diffGroups = [];
  activeDiff = -1;
  diffView = false;
  diffBusy = false;
  $("diffbtn").textContent = "检测差分图";
  $("diffbtn").disabled = false;
  renderDiffList();
  renderFiles();
}
async function moveDiffGroupBy(idx) {
  const g = diffGroups[idx];
  if (!g) return;
  const name = $("difftarget").value.trim() || `差分图组${idx + 1}`;
  try {
    const r = await api("/api/move_files", {
      method: "POST",
      body: JSON.stringify({ paths: g, folder_name: name }),
    });
    if (!r.moved) return alert("没有可移动的文件（可能已被移走）");
    $("difftarget").value = "";
    diffGroups.splice(idx, 1);               // 该组整组已移走，移除出结果
    if (activeDiff === idx) activeDiff = -1;
    if (activeDiff >= diffGroups.length) activeDiff = -1;
    renderDiffList();
    await refresh();
    renderDiffList();
    renderFiles();
    alert(`已创建文件夹「${name}」并移动 ${r.moved} 张 → ${r.target}`);
  } catch (e) { alert("移动失败: " + e.message); }
}
async function moveDiffGroup() {
  if (activeDiff < 0 || !diffGroups[activeDiff]) return;
  await moveDiffGroupBy(activeDiff);
}

// 通用右键/菜单：在 (x,y) 弹出一组菜单项
function makeMenu(x, y, entries) {
  hideCtx();
  const c = $("ctx");
  c.innerHTML = "";
  for (const en of entries) {
    const b = document.createElement("button");
    b.className = "ctx-item";
    b.textContent = en.label;
    b.addEventListener("click", (ev) => { ev.stopPropagation(); hideCtx(); en.fn(); });
    c.appendChild(b);
  }
  c.hidden = false;
  const r = c.getBoundingClientRect();
  c.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 8)) + "px";
  c.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 8)) + "px";
}
// 差分组“文件夹”菜单：本地建夹移动 / 只看这一组
function openGroupMenuAt(x, y, idx, displayName) {
  const g = diffGroups[idx];
  if (!g) return;
  makeMenu(x, y, [
    { label: `📁 本地创建「${displayName}」并移动这 ${g.length} 张`, fn: () => moveDiffGroupBy(idx) },
    { label: "只看这一组", fn: () => setDiffActive(idx) },
  ]);
}
function toggleDiffView() {
  diffView = !diffView;
  if (diffView) {
    activeDiff = -1;
    quickMode = "all";
    clearTagsFilter();
    updateStats();
    renderTags();
  }
  renderDiffList();
  renderFiles();
}

async function moveSelected() {
  if (!selTags.length) return alert("请先点击选择标签");
  const tags = [...selTags];
  const name = $("foldername").value.trim() || tags[0];
  try {
    const r = await api("/api/move", {
      method: "POST",
      body: JSON.stringify({ tag: tags[0], tags, folder_name: name }),
    });
    if (!r.moved) return alert("没有匹配的图片（可能已被移走）");
    clearTagsFilter();
    await refresh();
    renderTags();
    alert(`已移动 ${r.moved} 张到 ${r.target}`);
  } catch (e) { alert("移动失败: " + e.message); }
}

// ---------- 预览（缩放 + 拖拽平移 + 上下张 + GIF 循环播放/进度条） ----------
let gifP = null;                 // GIF 播放器状态 {bmps, dur, cur, playing, timer}
let panX = 0, panY = 0;          // 平移量（配合 scale 的 transform）
let dragSt = null;               // 拖拽平移状态
let suppressClose = false;       // 拖过之后忽略一次“点空白关闭”

function viewEl() {
  return $("viewerimg").hidden ? $("gifcanvas") : $("viewerimg");
}
function applyViewTransform() {
  const el = viewEl();
  el.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  $("viewerzoom").textContent = Math.round(zoom * 100) + "%";
  $("viewerbody").style.cursor = zoom > 1.01 ? "grab" : "default";
}
function clampPan() {
  const el = viewEl();
  const vw = window.innerWidth, vh = window.innerHeight;
  const w = el.offsetWidth || vw, h = el.offsetHeight || vh;
  const limX = Math.max(0, (w * zoom - vw) / 2);
  const limY = Math.max(0, (h * zoom - vh) / 2);
  panX = Math.min(limX, Math.max(-limX, panX));
  panY = Math.min(limY, Math.max(-limY, panY));
}
function setZoom(z) {
  zoom = Math.min(12, Math.max(0.1, z));
  if (zoom <= 1.001) { panX = 0; panY = 0; }
  clampPan();
  applyViewTransform();
}
function resetView() {
  zoom = 1; panX = 0; panY = 0;
  applyViewTransform();
}
function endDrag() {
  if (!dragSt) return;
  if (dragSt.moved > 6) suppressClose = true;   // 拖过就不再当“点空白关闭”
  dragSt = null;
  // 恢复平滑过渡（仅用于缩放/复位动画，拖动期间保持关闭）
  const el = viewEl();
  if (el) el.style.transition = "";
  $("viewerbody").style.cursor = zoom > 1.01 ? "grab" : "default";
}
function isGif(path) {
  return /\.gif$/i.test(path);
}
function isVideo(path) {
  return /\.(mp4|mov|mkv|webm|avi|wmv|m4v|flv)$/i.test(path);
}
// 当前网格里展示的顺序（含分组视图），预览翻页只在这套结果内走
let viewerPaths = [];
function syncViewerPaths() {
  viewerPaths = Array.from(document.querySelectorAll("#grid .card"))
    .map(c => c.dataset.path)
    .filter(Boolean);
}
function fileByPath(p) {
  return state && state.files ? state.files.find(f => f.path === p) : null;
}
function openViewer(path) {
  syncViewerPaths();
  if (!viewerPaths.length) viewerPaths = [path];
  let i = viewerPaths.indexOf(path);
  if (i < 0) { viewerPaths = [path]; i = 0; }
  viewerIndex = i;
  showViewer();
}
function renderViewerTags(f) {
  const wrap = $("viewertags");
  const box = $("viewertaglist");
  box.innerHTML = "";
  const tags = (f && f.tags) || [];
  wrap.hidden = false;
  if (!tags.length) {
    const n = document.createElement("span");
    n.className = "vnone";
    n.textContent = "（暂无标签）";
    box.appendChild(n);
    return;
  }
  tags.forEach(tag => {
    const b = document.createElement("button");
    b.className = "vtag";
    b.textContent = tag;
    b.title = "左键：按该标签筛选；右键：从这张图移除";
    b.addEventListener("click", () => {
      closeViewer();
      clearTagsFilter();
      setTagFilter(tag);
    });
    b.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      makeMenu(e.clientX, e.clientY, [
        { label: `✂️ 从这张图移除「${tag}」`, fn: () => vtRemoveTag(tag) },
      ]);
    });
    box.appendChild(b);
  });
}
function showViewer() {
  const p = viewerPaths[viewerIndex];
  const f = fileByPath(p);
  if (!f) return;
  $("viewertitle").textContent = f.name;
  renderViewerTags(f);
  $("viewer").hidden = false;
  setZoom(1);
  const vid = $("viewervideo");
  vid.pause();
  vid.hidden = true;
  if (isVideo(f.path)) {
    stopGifViewer();
    $("viewerimg").hidden = true;
    const url = "/api/image?path=" + encodeURIComponent(f.path);
    if (vid.src !== url && vid.getAttribute("src") !== url) {
      vid.src = url;                       // 仅当地址变化才重设，避免重复加载
    }
    vid.hidden = false;
    return;
  }
  if (isGif(f.path)) {
    $("viewerimg").hidden = true;
    startGifViewer("/api/image?path=" + encodeURIComponent(f.path));
  } else {
    stopGifViewer();
    $("viewerimg").src = "/api/image?path=" + encodeURIComponent(f.path);
    $("viewerimg").hidden = false;
  }
}
function viewerNav(d) {
  if (!viewerPaths.length) return;
  viewerIndex = (viewerIndex + d + viewerPaths.length) % viewerPaths.length;
  showViewer();
}
function closeViewer() {
  stopGifViewer();
  const vid = $("viewervideo");
  vid.pause();
  vid.hidden = true;        // 保留 src：重开同一视频时直接续播/秒开，不再重新加载
  hideCtx();
  $("viewer").hidden = true;
}

// --- GIF 播放器（预解码全部帧：点开即可任意拖，画面即时跟帧） ---
function drawGifFrame() {
  if (!gifP) return;
  const cv = $("gifcanvas");
  const c = cv.getContext("2d");
  c.clearRect(0, 0, cv.width, cv.height);
  c.drawImage(gifP.bmps[gifP.cur], 0, 0);
  $("gifseek").value = gifP.cur;
  $("giflabel").textContent = (gifP.cur + 1) + "/" + gifP.bmps.length;
}
function scheduleGif() {
  if (!gifP || !gifP.playing) return;
  clearTimeout(gifP.timer);
  const ms = gifP.dur[gifP.cur];
  gifP.timer = setTimeout(() => {
    if (!gifP || !gifP.playing) return;
    gifP.cur++;
    if (gifP.cur >= gifP.bmps.length) gifP.cur = 0;   // 循环播放
    drawGifFrame();
    scheduleGif();
  }, ms);
}
function stopGifViewer() {
  if (gifP) {
    clearTimeout(gifP.timer);
    for (const b of gifP.bmps) b.close();
    gifP = null;
  }
  $("gifbar").hidden = true;
  $("gifcanvas").hidden = true;
  $("gifplay").textContent = "⏸";
}
async function startGifViewer(url) {
  stopGifViewer();
  const cv = $("gifcanvas");
  const bar = $("gifbar");
  bar.hidden = false;
  cv.hidden = false;
  $("gifplay").textContent = "⏸";
  $("gifplay").disabled = false;
  $("giflabel").textContent = "加载中…";
  $("gifseek").value = 0;
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const buf = await res.arrayBuffer();
    if (typeof ImageDecoder === "undefined") throw new Error("no ImageDecoder");
    const dec = new ImageDecoder({ data: buf, type: "image/gif" });
    await dec.tracks.ready;
    const n = dec.tracks.selectedTrack.frameCount || 1;
    const bmps = [], ts = [];
    for (let i = 0; i < n; i++) {
      const { image } = await dec.decode({ frameIndex: i });
      ts.push(image.timestamp);
      bmps.push(await createImageBitmap(image));
      image.close();
    }
    const dur = ts.map((t, i) => {
      if (i + 1 >= n) return 100;                       // 末帧默认 100ms 后回到首帧
      const ms = Math.round((ts[i + 1] - t) / 1000);    // VideoFrame.timestamp 是微秒
      if (ms <= 0) return 100;                          // 延时为 0 的 GIF 按 100ms 处理
      return Math.max(10, ms);
    });
    gifP = { bmps, dur, cur: 0, playing: true, timer: null };
    cv.width = bmps[0].width;
    cv.height = bmps[0].height;
    $("gifseek").max = Math.max(1, n - 1);
    $("gifseek").min = 0;
    $("gifseek").step = 1;
    $("gifseek").disabled = false;
    drawGifFrame();
    scheduleGif();
  } catch (e) {
    // 降级：普通 <img>（浏览器自动播放动图，无进度条）
    stopGifViewer();
    $("viewerimg").src = url;
    $("viewerimg").hidden = false;
  }
}

function gifTogglePlay() {
  if (!gifP) return;
  gifP.playing = !gifP.playing;
  $("gifplay").textContent = gifP.playing ? "⏸" : "⏵";
  if (gifP.playing) scheduleGif();
}

$("scan").onclick = scan;
$("start").onclick = startTag;
$("stop").onclick = stopTag;
$("tagfilter").oninput = renderTags;
$("move").onclick = moveSelected;
$("diffbtn").onclick = detectDiff;
$("diffclr").onclick = clearDiff;
$("diffmove").onclick = moveDiffGroup;
$("difftoggle").onclick = toggleDiffView;
$("stat-all").onclick = () => setQuick("all");
$("stat-untagged").onclick = () => setQuick("untagged");
$("stat-failed").onclick = () => setQuick("failed");
$("undobtn").onclick = undoMove;
$("vtadd").onclick = vtAddTag;
$("folderbtn").onclick = async () => {
  try {
    const r = await api("/api/choose_folder", { method: "POST", body: "{}" });
    if (r.path) {
      $("folder").value = r.path;
      toast("已选择文件夹");
    }
  } catch (e) { alert("选择失败: " + e.message); }
};
$("mdlbtn").onclick = async () => {
  try {
    await api("/api/model/download", { method: "POST", body: "{}" });
    startModelWatch();
  } catch (e) { alert("模型下载启动失败: " + e.message); }
};
$("fname").addEventListener("input", () => {
  fnameKw = $("fname").value.trim().toLowerCase();
  renderFiles();
});
$("gifoff").addEventListener("change", () => renderFiles());
$("close").onclick = closeViewer;
$("fit").onclick = () => setZoom(1);
$("prev").onclick = () => viewerNav(-1);
$("next").onclick = () => viewerNav(1);
$("gifplay").onclick = gifTogglePlay;
// 拖动/点击进度条时自动暂停，松手后若原本在播放则恢复
let scrubWasPlaying = false;
function scrubPause() {
  if (!gifP || !gifP.playing) return;
  scrubWasPlaying = true;
  gifP.playing = false;
  clearTimeout(gifP.timer);           // 立刻停掉待播的下一帧
  $("gifplay").textContent = "⏵";
}
function scrubResume() {
  if (!gifP || !scrubWasPlaying) return;
  scrubWasPlaying = false;
  gifP.playing = true;
  $("gifplay").textContent = "⏸";
  scheduleGif();
}
$("gifseek").addEventListener("pointerdown", scrubPause);
$("gifseek").addEventListener("input", () => {
  if (!gifP) return;
  scrubPause();                       // input 一定触发（拖动、点击轨道、键盘），保证暂停生效
  gifP.cur = Math.min(Math.max(0, +$("gifseek").value), gifP.bmps.length - 1);
  drawGifFrame();                     // 全部帧已预解码，拖到哪帧立即显示
});
window.addEventListener("pointerup", scrubResume);       // 松手（无论在哪）恢复
window.addEventListener("pointercancel", scrubResume);
$("gifseek").addEventListener("change", scrubResume);    // 兜底

// ---------- 图片右键菜单：复制 / 路径 / 另存为 / 打开所在文件夹 / 默认程序打开 ----------
let ctxFile = null;
const CTX_ITEMS = [
  { k: "copyImage", t: "复制图片" },
  { k: "copyPath", t: "复制文件路径" },
  { k: "saveAs", t: "另存为…" },
  null, // 分隔线
  { k: "openFolder", t: "打开所在文件夹" },
  { k: "openFile", t: "用默认程序打开" },
];
function hideCtx() {
  ctxFile = null;
  $("ctx").hidden = true;
}
function showCtxMenu(e, f) {
  ctxFile = f;
  const c = $("ctx");
  c.innerHTML = "";
  for (const it of CTX_ITEMS) {
    if (!it) {
      const d = document.createElement("div");
      d.className = "ctx-sep";
      c.appendChild(d);
      continue;
    }
    const b = document.createElement("button");
    b.className = "ctx-item";
    b.textContent = it.t;
    b.addEventListener("click", (ev) => { ev.stopPropagation(); doCtxAction(it.k); });
    c.appendChild(b);
  }
  c.hidden = false;
  const r = c.getBoundingClientRect();
  let x = Math.max(4, Math.min(e.clientX, window.innerWidth - r.width - 8));
  let y = Math.max(4, Math.min(e.clientY, window.innerHeight - r.height - 8));
  c.style.left = x + "px";
  c.style.top = y + "px";
}
// 轻提示（1.6s 自动消失）
let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    t.classList.remove("show");
    setTimeout(() => { t.hidden = true; }, 200);
  }, 1600);
}

// 剪贴板写入要求页面保持聚焦；失焦时先抢回焦点再重试
async function writeClipboardGuarded(fn) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await fn();
      return;
    } catch (e) {
      if (attempt >= 2) throw e;
      window.focus();
      await new Promise(r => setTimeout(r, 120));
    }
  }
}

async function doCtxAction(k) {
  const f = ctxFile;
  hideCtx();
  if (!f) return;
  const url = "/api/image?path=" + encodeURIComponent(f.path);
  try {
    if (k === "copyPath") {
      await writeClipboardGuarded(() => navigator.clipboard.writeText(f.path));
      toast("已复制文件路径");
    } else if (k === "copyImage") {
      // 先取字节（不依赖焦点），最后一步写入才做聚焦重试
      const raw = await (await fetch(url)).blob();
      const type = raw.type && raw.type.startsWith("image/") ? raw.type : "image/png";
      try {
        await writeClipboardGuarded(() =>
          navigator.clipboard.write([new ClipboardItem({ [type]: raw })]));
      } catch (e1) {
        // 浏览器不接受原格式（如 GIF）时，转成 PNG 首帧再复制
        const img = new Image();
        img.src = URL.createObjectURL(raw);
        await img.decode();
        const cv = document.createElement("canvas");
        cv.width = img.naturalWidth;
        cv.height = img.naturalHeight;
        cv.getContext("2d").drawImage(img, 0, 0);
        const png = await new Promise(r => cv.toBlob(r, "image/png"));
        await writeClipboardGuarded(() =>
          navigator.clipboard.write([new ClipboardItem({ "image/png": png })]));
      }
      toast("已复制图片");
    } else if (k === "saveAs") {
      const blob = await (await fetch(url)).blob();
      if (window.showSaveFilePicker) {
        const h = await window.showSaveFilePicker({ suggestedName: f.name });
        const w = await h.createWritable();
        await w.write(blob);
        await w.close();
      } else {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = f.name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 10000);
      }
    } else if (k === "openFolder" || k === "openFile") {
      const r = await fetch("/api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: f.path, what: k === "openFile" ? "file" : "folder" }),
      });
      if (!r.ok) alert("打开失败：" + (await r.text()));
    }
  } catch (e) {
    if (k === "saveAs" || k === "openFolder" || k === "openFile") {
      /* 保存取消 / 打开类错误已单独提示，不打扰 */
    } else if (k === "copyImage" || k === "copyPath") {
      alert("复制失败：浏览器要求页面保持聚焦。请先点一下页面空白处，再重试复制；图片也可改用「另存为」。");
    } else {
      alert("操作失败：" + e.message);
    }
  }
}
document.addEventListener("click", hideCtx);
document.addEventListener("contextmenu", hideCtx);
window.addEventListener("blur", hideCtx);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideCtx(); }, true);

$("viewerbody").addEventListener("wheel", (e) => {
  const f = curViewerFile();
  if (f && isVideo(f.path)) return;          // 视频用原生播放器，不做缩放
  e.preventDefault();
  setZoom(zoom * (e.deltaY < 0 ? 1.1 : 0.9));
});
$("viewerimg").addEventListener("dblclick", () => setZoom(1));
$("gifcanvas").addEventListener("dblclick", () => setZoom(1));
function ctxOnPreview(e) {
  e.preventDefault();
  e.stopPropagation();
  const f = curViewerFile();
  if (f) showCtxMenu(e, f);
}
$("viewerimg").addEventListener("contextmenu", ctxOnPreview);
$("gifcanvas").addEventListener("contextmenu", ctxOnPreview);
$("viewervideo").addEventListener("contextmenu", ctxOnPreview);

// 放大后的拖拽平移
$("viewerbody").addEventListener("pointerdown", (e) => {
  if (e.button !== 0 || zoom <= 1.01) return;
  e.preventDefault();                       // 阻止图片原生拖拽
  dragSt = { sx: e.clientX, sy: e.clientY, px: panX, py: panY, moved: 0 };
  try { $("viewerbody").setPointerCapture(e.pointerId); } catch (err) { /* 无活动指针时忽略 */ }
  const el = viewEl();
  if (el) el.style.transition = "none";     // 拖动时关掉过渡动画，保证 1:1 跟手
  $("viewerbody").style.cursor = "grabbing";
});
$("viewerbody").addEventListener("pointermove", (e) => {
  if (!dragSt || zoom <= 1.01) return;
  const dx = e.clientX - dragSt.sx, dy = e.clientY - dragSt.sy;
  dragSt.moved = Math.max(dragSt.moved, Math.abs(dx) + Math.abs(dy));
  panX = dragSt.px + dx;                    // translate 在最外层=屏幕像素，1:1 跟随光标
  panY = dragSt.py + dy;
  clampPan();
  applyViewTransform();
});
$("viewerbody").addEventListener("pointerup", endDrag);
$("viewerbody").addEventListener("pointercancel", endDrag);

// 点击图片外空白区域关闭预览（拖过图片的松手不算点击）
$("viewerbody").addEventListener("click", (e) => {
  if (suppressClose) { suppressClose = false; return; }
  if (e.target === $("viewerbody")) closeViewer();
});

document.addEventListener("keydown", (e) => {
  if ($("viewer").hidden) return;
  if (e.key === "Escape") closeViewer();
  if (e.key === "ArrowLeft") viewerNav(-1);
  if (e.key === "ArrowRight") viewerNav(1);
  if (e.code === "Space" && !e.repeat) { e.preventDefault(); gifTogglePlay(); }
});

function setDens(d) {
  dens = d;
  document.body.classList.remove("dens-s", "dens-m", "dens-l");
  document.body.classList.add("dens-" + d);
  document.querySelectorAll(".dens .seg").forEach(b =>
    b.classList.toggle("active", b.dataset.dens === d));
  try { localStorage.setItem("dshDens", d); } catch (e) { /* ignore */ }
  const g = $("grid");
  if (g) g.scrollTop = 0;
  if (state) renderFiles();
}

// 启动时自动回到上次查看的目录
async function autoRestore() {
  if (!state || state.folder || !state.last_folder) return;
  $("folder").value = state.last_folder;
  $("subfolders").checked = !!state.last_sub;
  $("includevideo").checked = state.last_video !== false;
  try {
    state = await api("/api/scan", {
      method: "POST",
      body: JSON.stringify({
        folder: state.last_folder,
        include_sub: !!state.last_sub,
        include_video: state.last_video !== false,
      }),
    });
    renderAll();
  } catch (e) {
    $("folder").value = state.last_folder;   // 目录已不可用时留在输入框供手动修改
  }
}

refresh().then(async () => {
  // 缩略图密度（记住选择）
  let d = "m";
  try { const v = localStorage.getItem("dshDens"); if (v) d = v; } catch (e) { /* ignore */ }
  setDens(d);
  document.querySelectorAll(".seg[data-dens]").forEach(b =>
    b.addEventListener("click", () => setDens(b.dataset.dens)));
  // 回到顶部
  const grid = $("grid");
  grid.addEventListener("scroll", () => {
    $("totop").hidden = grid.scrollTop < 700;
  }, { passive: true });
  $("totop").onclick = () => grid.scrollTo({ top: 0, behavior: "smooth" });
  // 自动回到上次目录
  autoRestore();
  // 模型缺失：自动下载 + 进度监视
  if (state && state.model && !state.model.present) {
    try {
      await api("/api/model/download", { method: "POST", body: "{}" });
    } catch (e) { /* 稍后手动按钮重试 */ }
    startModelWatch();
  }
});
