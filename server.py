# -*- coding: utf-8 -*-
"""图片分类器后端（FastAPI）：扫描、EVA02 打标（含差分检测）、标签、缩略图、移动。"""
import hashlib
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image, ImageOps

import core

app = FastAPI(title="图片分类器 API")


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response

_BASE = Path(__file__).parent
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    # 打成 EXE：模型放安装目录；静态/词典在 _internal（sys._MEIPASS）；数据走 AppData
    _APP = Path(sys.executable).resolve().parent
    EVA02_DIR = _APP / "eva02"
    STATIC_DIR = Path(sys._MEIPASS) / "static"
else:
    # 开发运行：沿用仓库结构
    _APP = _BASE
    EVA02_DIR = _BASE.parent / "eva02"
    STATIC_DIR = _BASE / "static"

DATA_BASE = core.app_home()   # 开发=image-tagger；EXE=AppData\ImageTagger

STATE = {
    "folder": None,
    "files": [],
    "tags": {},
    "raw_outputs": {},
    "tagging": False,
    "progress": {"done": 0, "total": 0, "current": ""},
    "threshold": 0.35,
    "diff_groups": [],
    "diff_running": False,
    "diff_progress": {"done": 0, "total": 0, "phase": "idle"},
    "diff_gen": 0,
}
STOP = threading.Event()
_eva02 = None
_hashes = {}
_raw_cn = {}
_danbooru_zh = {}
_cn2en = {}           # 中文名 → 英文名（用于英文 token 分类）
_thumb_cache = {}
_gif_meta_cache = {}
_strip_cache = {}     # 视频预览胶片条：{(path,n): (mtime, png_bytes)}
_lock = threading.Lock()
MOVE_LOG = []        # 最近一次移动记录（撤销用）

# 版本与自动更新检查（启动时后台查 GitHub 最新 Release，仅提示、不自动装）
APP_VERSION = "1.3"
UPDATE_REPO = "kiropoi/-image-storage-Setup"
_update_info = {"checked": False, "latest": None, "has_update": False, "url": ""}
_update_lock = threading.Lock()


def _parse_version(s):
    nums = []
    for part in re.split(r"[^0-9]+", (s or "").strip().lstrip("vV")):
        if part.isdigit():
            nums.append(int(part))
    return tuple(nums) if nums else (0,)


def _check_for_update():
    """后台查询 GitHub 最新版本；失败静默（无网络时不影响启动）。"""
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
            headers={"User-Agent": "image-storage-updater",
                     "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        latest = (data.get("tag_name") or "").lstrip("vV")
        url = data.get("html_url") or ""
        with _update_lock:
            _update_info.update({
                "checked": True, "latest": latest,
                "has_update": _parse_version(latest) > _parse_version(APP_VERSION),
                "url": url,
            })
    except Exception:
        with _update_lock:
            _update_info.update({"checked": True, "latest": None,
                                 "has_update": False, "url": ""})

# 模型下载管理（安装包只装主体，首次运行自动下载模型）
_MODEL_URLS = [
    os.environ.get(
        "IMG_TAGGER_MODEL_URL",
        "https://hf-mirror.com/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/model.onnx"),
    "https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/model.onnx",
]
_MODEL_CSV_URLS = [
    os.environ.get(
        "IMG_TAGGER_MODEL_CSV_URL",
        "https://hf-mirror.com/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/selected_tags.csv"),
    "https://huggingface.co/SmilingWolf/wd-eva02-large-tagger-v3/resolve/main/selected_tags.csv",
]
MODEL_DOWNLOAD = {"active": False, "done": 0, "total": 0, "error": None, "url": _MODEL_URLS[0]}


def _model_present():
    return (EVA02_DIR / "model.onnx").exists() and (EVA02_DIR / "selected_tags.csv").exists()


def _download_file(url, dest):
    MODEL_DOWNLOAD["url"] = url
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        MODEL_DOWNLOAD["total"] = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            MODEL_DOWNLOAD["done"] = done
    tmp.replace(dest)


def _download_any(urls, dest):
    last_err = None
    for u in urls:
        try:
            _download_file(u, dest)
            return
        except Exception as e:
            last_err = e
            if dest.exists():
                dest.unlink(missing_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            tmp.unlink(missing_ok=True)
    raise last_err or RuntimeError("download failed")


def _model_worker():
    MODEL_DOWNLOAD["active"] = True
    MODEL_DOWNLOAD["error"] = None
    MODEL_DOWNLOAD["done"] = 0
    MODEL_DOWNLOAD["total"] = 0
    try:
        EVA02_DIR.mkdir(parents=True, exist_ok=True)
        if not (EVA02_DIR / "model.onnx").exists():
            _download_any(_MODEL_URLS, EVA02_DIR / "model.onnx")
        if not (EVA02_DIR / "selected_tags.csv").exists():
            _download_any(_MODEL_CSV_URLS, EVA02_DIR / "selected_tags.csv")
    except Exception as e:
        MODEL_DOWNLOAD["error"] = str(e)
    finally:
        MODEL_DOWNLOAD["active"] = False


def ensure_model_download():
    if _model_present() or MODEL_DOWNLOAD["active"]:
        return
    threading.Thread(target=_model_worker, daemon=True).start()


def model_status():
    return {
        "present": _model_present(),
        "active": MODEL_DOWNLOAD["active"],
        "done": MODEL_DOWNLOAD["done"],
        "total": MODEL_DOWNLOAD["total"],
        "error": MODEL_DOWNLOAD["error"],
        "url": MODEL_DOWNLOAD["url"],
    }


# ---------- 视频支持（内嵌 ffmpeg：缩略图/预览/按时长等分抽帧打标） ----------

def _ffmpeg_exe():
    for cand in (
        os.environ.get("IMG_TAGGER_FFMPEG"),
        str(_APP / "ffmpeg" / "ffmpeg.exe"),
        shutil.which("ffmpeg"),
    ):
        if cand and os.path.exists(cand):
            return cand
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _video_duration(path):
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        if fps > 0 and n > 0:
            return n / fps
    except Exception:
        pass
    return 0.0


def _video_frame(path, t):
    """取视频第 t 秒处的一帧（优先 ffmpeg，失败回退 cv2）。"""
    ff = _ffmpeg_exe()
    if ff:
        try:
            import tempfile
            fd, out = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            subprocess.run(
                [ff, "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-q:v", "2", "-y", out],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=True)
            img = Image.open(out).convert("RGB")
            img.load()
            os.remove(out)
            return img
        except Exception:
            pass
    try:
        import cv2
        cap = cv2.VideoCapture(path)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        cap.release()
        if ok:
            return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    except Exception:
        pass
    return None


def _video_frames(path, count=5, duration=None):
    dur = duration if duration is not None else _video_duration(path)
    if dur <= 0:
        dur = 1.0
    frames = []
    for i in range(count):
        t = dur * (i + 0.5) / count
        im = _video_frame(path, t)
        if im is not None:
            frames.append(im)
    return frames


def _central_cache_path(folder: str):
    """打标数据统一存到 D:/DSH/image-tagger/tagdata/，按扫描目录哈希分文件。"""
    return DATA_BASE / "tagdata" / (hashlib.sha1(str(folder).encode("utf-8")).hexdigest() + ".json")


def _legacy_tagstore_path(folder: str):
    """早期版本的双保险镜像位置（.tagstore），只读迁移用。"""
    return DATA_BASE / ".tagstore" / (hashlib.sha1(str(folder).encode("utf-8")).hexdigest() + ".json")


def _save_cache():
    if not STATE["folder"]:
        return
    try:
        p = _central_cache_path(STATE["folder"])
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(STATE["tags"], ensure_ascii=False, indent=1),
                     encoding="utf-8")
    except Exception:
        pass


def _scan(folder: str, include_sub: bool = False, include_video: bool = True):
    d = Path(folder)
    files = []

    def _ok(suffix):
        return suffix in core.IMAGE_EXTS or (include_video and suffix in core.VIDEO_EXTS)

    if include_sub:
        for root, _dirs, names in os.walk(d):
            for fn in names:
                if _ok(Path(fn).suffix.lower()):
                    files.append(str(Path(root) / fn))
    else:
        for p in d.iterdir():
            if p.is_file() and _ok(p.suffix.lower()):
                files.append(str(p))
    files.sort()
    # 去重（防符号链接/重叠遍历把同一文件列两次）
    seen = set()
    uniq = []
    for fp in files:
        key = os.path.normcase(os.path.normpath(fp))
        if key not in seen:
            seen.add(key)
            uniq.append(fp)
    files = uniq
    STATE["folder"] = folder
    STATE["files"] = files
    STATE["tags"] = {}
    STATE["raw_outputs"] = {}
    # 读取顺序：① tagdata 中央目录 → ② 图库内旧缓存 → ③ 旧 .tagstore 镜像（迁移）
    sources = []
    cp = _central_cache_path(folder)
    if cp.exists():
        sources.append(cp)
    cache = d / core.CACHE_FILENAME
    if cache.exists():
        sources.append(cache)
    legacy = _legacy_tagstore_path(folder)
    if legacy.exists():
        sources.append(legacy)
    for src in sources:
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            for k, v in data.items():
                if isinstance(v, list) and Path(k).exists() and k not in STATE["tags"]:
                    STATE["tags"][k] = v
        except Exception:
            pass
    global _raw_cn, _danbooru_zh, _cn2en
    eht_tags, _ = core.load_eht_tags()
    _raw_cn = core.build_raw_cn_map(eht_tags)
    _danbooru_zh = core.load_danbooru_zh()
    # 中文名 → 英文名 反查表（danbooru 优先，e-hentai 补充）
    for en, cn in _danbooru_zh.items():
        _cn2en.setdefault(cn, en)
    for en, cn in _raw_cn.items():
        _cn2en.setdefault(cn, en)


def _tag_cat(name: str) -> str:
    """标签 → 分类。优先反查英文名按英文 token 分类（更准），否则直接按显示名分类。
    注意：部分中文别名本身是 ASCII（如 SM→bdsm、3P→threesome），必须同样反查。"""
    if not name:
        return "其他"
    en = _cn2en.get(name)
    if en:
        return core.tag_category_en(en)
    return core.tag_category(name)


def _ensure_eva02():
    global _eva02
    if _eva02 is None:
        _eva02 = core.load_eva02(str(EVA02_DIR / "model.onnx"),
                                 str(EVA02_DIR / "selected_tags.csv"))
    return _eva02


def _tag_one(path: str):
    if core.is_video(path):
        return _tag_video(path)
    sess, inp, general = _ensure_eva02()
    img = Image.open(path).convert("RGB")
    arr = np.array(img)[:, :, ::-1].copy()
    wd = core.eva02_tag_image(sess, inp, general, arr, STATE["threshold"])
    tags = []
    for name in sorted(wd, key=lambda k: -wd[k]):
        cn = _danbooru_zh.get(name) or _raw_cn.get(name) or name
        if cn not in tags:
            tags.append(cn)
    raw = " ".join(f"{k}({v:.2f})" for k, v in
                   sorted(wd.items(), key=lambda kv: -kv[1]))
    return tags, raw


def _tag_video(path: str):
    """视频：按时长等分抽 5 帧，逐帧识别后合并去重。"""
    frames = _video_frames(path, 5)
    if not frames:
        return ["打标失败"], "无法从视频抽帧"
    sess, inp, general = _ensure_eva02()
    merged = []
    raws = []
    for idx, im in enumerate(frames):
        arr = np.array(im)[:, :, ::-1].copy()
        wd = core.eva02_tag_image(sess, inp, general, arr, STATE["threshold"])
        for name in sorted(wd, key=lambda k: -wd[k]):
            cn = _danbooru_zh.get(name) or _raw_cn.get(name) or name
            if cn not in merged:
                merged.append(cn)
        top = sorted(wd.items(), key=lambda kv: -kv[1])[:10]
        raws.append(f"[帧{idx + 1}] " + " ".join(f"{k}({v:.2f})" for k, v in top))
    return merged, " | ".join(raws)


def _find_similar(path: str):
    try:
        h = core.dhash(Image.open(path))
    except Exception:
        return None
    best, best_d = None, None
    for k, h2 in _hashes.items():
        d = core.hamming(h, h2)
        if d <= core.DIFF_THRESHOLD and (best_d is None or d < best_d):
            best_d, best = d, k
    return best


def _dhash_of(path: str):
    try:
        return core.dhash(Image.open(path))
    except Exception:
        return 0


def _tag_worker(todo: list):
    total = len(todo)
    for i, path in enumerate(todo):
        if STOP.is_set():
            break
        STATE["progress"] = {"done": i, "total": total, "current": Path(path).name}
        similar = _find_similar(path)
        if similar is not None and similar in STATE["tags"]:
            tags = list(STATE["tags"][similar])
            raw = f"[差分图] 与 {Path(similar).name} 近似，已复用标签"
        else:
            try:
                tags, raw = _tag_one(path)
            except Exception as e:
                tags, raw = ["打标失败"], str(e)
            if not tags:
                tags = ["未分类"]
        with _lock:
            STATE["tags"][path] = tags
            STATE["raw_outputs"][path] = raw
            _hashes[path] = _dhash_of(path)
        _save_cache()  # 每张后保存，确保随时持久化到本地
    core.merge_all_tags(STATE["tags"])
    STATE["progress"] = {"done": len(STATE["tags"]), "total": total, "current": ""}
    STATE["tagging"] = False
    _save_cache()


# ---------- API ----------

class ScanReq(BaseModel):
    folder: str
    include_sub: bool = False
    include_video: bool = True


class TagStartReq(BaseModel):
    threshold: float = 0.35
    force: bool = False          # True=忽略已有标签，全部重打


class ImageTagsReq(BaseModel):
    path: str
    add: list[str] = []
    remove: list[str] = []


class MoveReq(BaseModel):
    tag: str = ""
    tags: list[str] = []          # 多选：同时包含这些标签的文件才移动
    folder_name: str = ""


class RenameReq(BaseModel):
    old: str
    new: str


class DeleteReq(BaseModel):
    tag: str


def _file_list():
    return [{
        "path": p,
        "name": Path(p).name,
        "tags": STATE["tags"].get(p, []),
        "raw": STATE["raw_outputs"].get(p, ""),
    } for p in STATE["files"]]


def _tag_freq():
    from collections import Counter
    c = Counter()
    for p in STATE["files"]:                     # 只统计当前列表内文件的标签
        c.update(STATE["tags"].get(p, []))
    return [{"tag": k, "count": v, "cat": _tag_cat(k)} for k, v in
            sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]


@app.get("/api/state")
def get_state():
    return {
        "folder": STATE["folder"],
        "files": _file_list(),
        "tags": _tag_freq(),
        "tagging": STATE["tagging"],
        "progress": STATE["progress"],
        "threshold": STATE["threshold"],
        "eva02_available": (EVA02_DIR / "model.onnx").exists(),
        "model": model_status(),
        "last_folder": core.load_settings().get("last_folder"),
        "last_sub": bool(core.load_settings().get("last_sub", False)),
        "last_video": bool(core.load_settings().get("last_video", True)),
        "can_undo": bool(MOVE_LOG),
        "app_version": APP_VERSION,
        "update": dict(_update_info),
    }


@app.post("/api/choose_folder")
def api_choose_folder():
    """弹出系统文件夹选择框，返回所选绝对路径（前端填进路径框）。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="选择图片文件夹")
        root.destroy()
        return {"path": path or ""}
    except Exception as e:
        raise HTTPException(500, f"无法打开文件夹选择框: {e}")


@app.get("/api/model/status")
def api_model_status():
    return model_status()


@app.post("/api/model/download")
def api_model_download():
    ensure_model_download()
    return model_status()


@app.post("/api/scan")
def api_scan(req: ScanReq):
    if not Path(req.folder).is_dir():
        raise HTTPException(400, "文件夹不存在")
    _scan(req.folder, req.include_sub, req.include_video)
    s = core.load_settings()
    s["last_folder"] = req.folder
    s["last_sub"] = bool(req.include_sub)
    s["last_video"] = bool(req.include_video)
    core.save_settings(s)
    return get_state()


# ---------- 差分图检测（同姿势/近似变体归组，dHash + 汉明距离） ----------

class DiffReq(BaseModel):
    # 默认 20：同姿势换穿着（白丝/黑丝等）实测距离 ~4-18；完全不同的图一般 ≥30+
    threshold: int = 20


def _diff_detect(threshold: int, progress_cb=None):
    files = STATE["files"]
    if not files:
        return []
    hashes = []
    ok_files = []
    for idx, p in enumerate(files):
        try:
            h = core.dhash(Image.open(p))
            if h:
                ok_files.append(p)
                hashes.append(h)
        except Exception:
            pass
        if progress_cb:
            progress_cb(idx + 1, len(files), "hash")
    n = len(ok_files)
    if n < 2:
        return []
    arr = np.array(hashes, dtype=np.uint64)

    # 星型聚类：每组以“代表图”为圆心，只允许“距代表图 ≤ 阈值”的图加入，
    # 避免单链接连锁把 A~B~C 一路并成一个大类。
    bc = getattr(np, "bitwise_count", None)
    groups = []          # 每组：[代表图下标, [成员下标...]]
    for i in range(n):
        best = None
        best_d = threshold + 1
        for g in groups:
            rep = g[0]
            d = (int(arr[rep]) ^ int(arr[i])).bit_count()
            if d <= threshold and d < best_d:
                best_d = d
                best = g
        if best is not None:
            best[1].append(i)
        else:
            groups.append([i, [i]])

    out = []
    for rep, members in groups:
        if len(members) >= 2:
            out.append(sorted(ok_files[k] for k in members))
    out.sort(key=len, reverse=True)
    return out


@app.post("/api/diff/detect")
def api_diff_detect(req: DiffReq):
    if STATE["diff_running"]:
        return {"started": False, "running": True}
    STATE["diff_gen"] += 1
    gen = STATE["diff_gen"]
    STATE["diff_running"] = True
    STATE["diff_progress"] = {"done": 0, "total": len(STATE["files"]), "phase": "hash"}
    threshold = max(1, req.threshold)

    class _Cancelled(Exception):
        pass

    def worker():
        try:
            def cb(done, total, phase):
                if STATE["diff_gen"] != gen:
                    raise _Cancelled()
                STATE["diff_progress"] = {"done": done, "total": total, "phase": phase}
            groups = _diff_detect(threshold, cb)
            STATE["diff_groups"] = groups
        except _Cancelled:
            pass
        finally:
            if STATE["diff_gen"] == gen:
                STATE["diff_running"] = False
                STATE["diff_progress"]["phase"] = "done"

    threading.Thread(target=worker, daemon=True).start()
    return {"started": True, "running": True}


@app.get("/api/diff/status")
def api_diff_status():
    running = STATE["diff_running"]
    return {
        "running": running,
        "progress": STATE["diff_progress"],
        "groups": len(STATE["diff_groups"]) if not running else None,
        "images_in_groups": sum(len(g) for g in STATE["diff_groups"]) if not running else None,
        "list": None if running else STATE["diff_groups"],
    }


@app.post("/api/diff/clear")
def api_diff_clear():
    STATE["diff_gen"] += 1              # 作废仍在跑的检测线程
    STATE["diff_running"] = False
    STATE["diff_groups"] = []
    STATE["diff_progress"] = {"done": 0, "total": 0, "phase": "idle"}
    return {"ok": True}


@app.post("/api/tag/start")
def api_tag_start(req: TagStartReq):
    if STATE["tagging"]:
        raise HTTPException(400, "已在打标中")
    STATE["threshold"] = req.threshold
    todo = STATE["files"] if req.force else \
        [p for p in STATE["files"] if p not in STATE["tags"]]
    if not todo:
        return {"ok": True, "message": "没有需要打标的图片"}
    STOP.clear()
    STATE["tagging"] = True
    STATE["progress"] = {"done": 0, "total": len(todo), "current": ""}
    threading.Thread(target=_tag_worker, args=(todo,), daemon=True).start()
    return {"ok": True, "total": len(todo)}


@app.post("/api/tag/stop")
def api_tag_stop():
    STOP.set()
    STATE["tagging"] = False
    return {"ok": True}


@app.get("/api/thumbnail")
def api_thumbnail(path: str, static: bool = False):
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "图片不存在")
    # GIF：默认原样返回动图（缩略图循环播放）；static=1 时返回首帧静态图
    if p.suffix.lower() == ".gif" and not static:
        return FileResponse(p, media_type="image/gif")
    cached = _thumb_cache.get(path)
    if cached and cached[0] == p.stat().st_mtime:
        return Response(content=cached[1], media_type="image/png")
    if core.is_video(path):
        # 视频：取中间帧做缩略图
        dur = _video_duration(path)
        frame = _video_frame(path, (dur or 1.0) * 0.5)
        if frame is None:
            frame = Image.new("RGB", (210, 140), (18, 18, 18))
        img = ImageOps.fit(frame, (210, 140), Image.LANCZOS)
    else:
        img = Image.open(p).convert("RGB")
        img = ImageOps.fit(img, (210, 140), Image.LANCZOS)  # 固定 210x140（3:2）居中裁剪
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    _thumb_cache[path] = (p.stat().st_mtime, data)
    return Response(content=data, media_type="image/png")


@app.get("/api/video/strip")
def api_video_strip(path: str, n: int = 16):
    """视频悬停预览胶片条：一张横向拼图，等分为 n 帧（210x140/帧），供前端悬停拖拽预览。"""
    p = Path(path)
    if not p.exists() or not core.is_video(str(p)):
        raise HTTPException(404, "不是视频")
    n = max(2, min(int(n), 60))
    key = (path, n)
    mtime = int(p.stat().st_mtime)
    cached = _strip_cache.get(key)
    if cached and cached[0] == mtime:
        return Response(content=cached[1], media_type="image/png")
    data = _build_strip(path, n)
    if data is not None:
        _strip_cache[key] = (mtime, data)
        return Response(content=data, media_type="image/png")
    raise HTTPException(500, "无法生成预览")


def _build_strip(path: str, n: int):
    """单次 ffmpeg 抽帧并横向拼接；失败则逐帧抽再拼（慢，但兜底）。"""
    dur = _video_duration(path)
    if dur <= 0:
        dur = 1.0
    ff = _ffmpeg_exe()
    if ff:
        try:
            import tempfile
            fd, out = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            fps = max(0.1, n / dur)
            vf = (f"fps={fps:.6f},"
                  "scale=210:140:force_original_aspect_ratio=increase,"
                  f"crop=210:140,tile={n}x1")
            subprocess.run(
                [ff, "-i", path, "-vf", vf, "-frames:v", "1", "-q:v", "3", "-y", out],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=True)
            img = Image.open(out).convert("RGB")
            img.load()
            os.remove(out)
            # 确保宽度是 210 的整数倍（tile 数量可能与 n 略有出入，前端按实际帧数算）
            w = img.width - (img.width % 210)
            if w < 210:
                w = img.width
            img = img.crop((0, 0, w, min(img.height, 140)))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            pass
    # 兜底：逐帧抽（较慢，但一定能出图）
    frames = _video_frames(path, n, dur)
    if not frames:
        return None
    strip = Image.new("RGB", (210 * len(frames), 140), (18, 18, 18))
    for i, fr in enumerate(frames):
        strip.paste(ImageOps.fit(fr, (210, 140), Image.LANCZOS), (i * 210, 0))
    buf = io.BytesIO()
    strip.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/api/gif/meta")
def api_gif_meta(path: str):
    p = Path(path)
    if not p.exists() or p.suffix.lower() != ".gif":
        raise HTTPException(404, "不是可用的 GIF")
    mtime = p.stat().st_mtime
    if path in _gif_meta_cache and _gif_meta_cache[path][0] == mtime:
        _, frames, delays = _gif_meta_cache[path]
        return {"frames": frames, "delays": delays}
    im = Image.open(p)
    frames = getattr(im, "n_frames", 1)
    delays = []
    for i in range(frames):
        try:
            im.seek(i)
            d = im.info.get("duration", 100) or 100
        except Exception:
            d = 100
        delays.append(max(10, int(d)))
    _gif_meta_cache[path] = (mtime, frames, delays)
    return {"frames": frames, "delays": delays}


@app.get("/api/gif/frame")
def api_gif_frame(path: str, i: int = 0):
    p = Path(path)
    if not p.exists() or p.suffix.lower() != ".gif":
        raise HTTPException(404, "不是可用的 GIF")
    im = Image.open(p)
    n = getattr(im, "n_frames", 1)
    try:
        im.seek(i % n)
    except Exception:
        im.seek(0)
    img = im.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/image")
def api_image(path: str, request: Request):
    p = Path(path)
    if not p.exists():
        raise HTTPException(404, "图片不存在")
    # 视频：支持 Range 请求，浏览器 <video> 才能拖动进度
    if core.is_video(path):
        rng = request.headers.get("range")
        file_size = p.stat().st_size
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            start = int(m.group(1)) if m and m.group(1) else 0
            end = int(m.group(2)) if m and m.group(2) else file_size - 1
            end = min(end, file_size - 1)
            length = end - start + 1
            ctype = mimetypes.guess_type(str(p))[0] or "video/mp4"

            def _chunks():
                CHUNK = 256 * 1024
                with p.open("rb") as f:
                    f.seek(start)
                    left = length
                    while left > 0:
                        buf = f.read(min(CHUNK, left))
                        if not buf:
                            break
                        left -= len(buf)
                        yield buf

            return StreamingResponse(
                _chunks(), status_code=206, media_type=ctype,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                })
    return FileResponse(p)


class OpenReq(BaseModel):
    path: str
    what: str = "folder"   # folder=打开所在文件夹 | file=用默认程序打开


def _open_via_default(p: Path):
    """多级回退打开文件：普通关联 -> ShellExecute -> 经 explorer（可激活商店版看图）。"""
    try:
        os.startfile(str(p))
        return "startfile"
    except OSError:
        pass
    try:
        import ctypes
        rc = ctypes.windll.shell32.ShellExecuteW(None, "open", str(p), None, None, 1)
        if rc > 32:
            return "shell"
    except Exception:
        pass
    try:
        import subprocess
        subprocess.Popen(["explorer.exe", str(p)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "explorer"
    except Exception:
        pass
    return None


@app.post("/api/open")
def api_open(req: OpenReq):
    if req.path not in STATE["files"]:
        raise HTTPException(403, "仅支持当前扫描列表内的文件")
    p = Path(req.path)
    try:
        if req.what == "file":
            m = _open_via_default(p)
            if m is None:
                raise HTTPException(
                    500, "无法用默认程序打开。该扩展名的默认程序可能已损坏或需管理员权限，"
                         "可尝试：右键文件→打开方式→选择看图程序并设为默认。")
            return {"ok": True, "method": m}
        os.startfile(str(p.parent))
        return {"ok": True, "method": "startfile"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"打开失败: {e}")


@app.post("/api/move")
def api_move(req: MoveReq):
    if not STATE["folder"]:
        raise HTTPException(400, "未选择文件夹")
    sel = req.tags if req.tags else ([req.tag] if req.tag else [])
    if not sel:
        return {"moved": 0, "target": ""}
    matches = [p for p in STATE["files"]
               if all(t in STATE["tags"].get(p, []) for t in sel)]
    if not matches:
        return {"moved": 0, "target": ""}
    return _move_paths(matches, req.folder_name or sel[0])


def _move_paths(paths, folder_name):
    """把给定路径列表移动到 扫描根目录/<folder_name>/ 下（重名自动加序号），并记录供撤销。"""
    valid = [p for p in paths if p in STATE["files"]]
    if not valid:
        return {"moved": 0, "target": ""}
    name = re.sub(r'[\\/:*?"<>|]', "_", folder_name or "整理")
    target = Path(STATE["folder"]) / name
    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise HTTPException(
            400,
            f"无法在「{target}」创建目标文件夹：{e}。"
            "若正在使用助手托管的服务器（无法写入图库目录），"
            "请改用你自己启动的 start_server.bat 执行移动。")
    moved = 0
    failed = 0
    log = []
    moved_paths = []
    for p in valid:
        try:
            dst = str(core.unique_path(target / Path(p).name))
            shutil.move(p, dst)
            moved += 1
            moved_paths.append(p)
            tags = STATE["tags"].pop(p, None)
            raw = STATE["raw_outputs"].pop(p, None)
            # 标签跟着文件走：记到新路径，重扫（含子文件夹）后仍能恢复，不再“消失”
            if tags is not None:
                STATE["tags"][dst] = tags
            if raw is not None:
                STATE["raw_outputs"][dst] = raw
            log.append({
                "src": p, "dst": dst,
                "tags": tags,
                "raw": raw,
            })
        except Exception:
            failed += 1
    if moved_paths:
        STATE["files"] = [p for p in STATE["files"] if p not in moved_paths]
    _save_cache()
    if moved:
        global MOVE_LOG
        MOVE_LOG = log           # 只保留最近一次移动，供一键撤销
    return {"moved": moved, "failed": failed, "target": str(target),
            "undoable": bool(log)}


class MoveFilesReq(BaseModel):
    paths: list[str]
    folder_name: str = "整理"


@app.post("/api/move_files")
def api_move_files(req: MoveFilesReq):
    if not STATE["folder"]:
        raise HTTPException(400, "未选择文件夹")
    return _move_paths(req.paths, req.folder_name)


@app.post("/api/move/undo")
def api_move_undo():
    if not MOVE_LOG:
        raise HTTPException(400, "没有可撤销的移动")
    log = MOVE_LOG
    restored = 0
    for item in log:
        try:
            src_dir = Path(item["src"]).parent
            src_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(item["dst"], item["src"])
            STATE["tags"].pop(item["dst"], None)          # 清掉新路径的标签记录
            STATE["raw_outputs"].pop(item["dst"], None)
            STATE["tags"][item["src"]] = item["tags"] or []
            if item["raw"] is not None:
                STATE["raw_outputs"][item["src"]] = item["raw"]
            if item["src"] not in STATE["files"]:
                STATE["files"].append(item["src"])
            restored += 1
        except Exception:
            pass
    STATE["files"].sort()
    _save_cache()
    return {"restored": restored}


@app.post("/api/image/tags")
def api_image_tags(req: ImageTagsReq):
    if req.path not in STATE["files"]:
        raise HTTPException(404, "图片不在当前列表")
    tags = list(STATE["tags"].get(req.path, []))
    for t in req.add:
        t = t.strip()
        if t and t not in tags:
            tags.append(t)
    if req.remove:
        tags = [t for t in tags if t not in req.remove]
    STATE["tags"][req.path] = tags
    _save_cache()
    return {"tags": tags}


@app.post("/api/rename_tag")
def api_rename(req: RenameReq):
    if req.new and req.new != req.old:
        for k, tags in STATE["tags"].items():
            STATE["tags"][k] = [req.new if t == req.old else t for t in tags]
    _save_cache()
    return {"ok": True}


@app.post("/api/delete_tag")
def api_delete(req: DeleteReq):
    for k, tags in STATE["tags"].items():
        STATE["tags"][k] = [t for t in tags if t != req.tag]
    _save_cache()
    return {"ok": True}


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import time
    import webbrowser
    import uvicorn

    ensure_model_download()   # 安装包首次运行：自动下载模型（已存在则跳过）
    threading.Thread(target=_check_for_update, daemon=True).start()   # 后台查更新

    HOST = "127.0.0.1"
    PORT = 8000
    URL = f"http://{HOST}:{PORT}/"

    def _open_app_window():
        # 优先用 Edge/Chrome 的 app 模式开一个独立窗口（WebView2/无地址栏，像原生窗口）
        roots = [
            os.environ.get("ProgramFiles(x86)", ""),
            os.environ.get("ProgramFiles", ""),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        names = [
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
        ]
        profile = core.app_home() / "webview_profile"
        for root in roots:
            for name in names:
                exe = os.path.join(root, name)
                if not os.path.exists(exe):
                    continue
                try:
                    subprocess.Popen([
                        exe, "--app=" + URL,
                        "--window-size=1440,900",
                        "--user-data-dir=" + str(profile),
                    ])
                    return True
                except Exception:
                    continue
        try:
            webbrowser.open(URL)
            return True
        except Exception:
            return False

    def _open_when_ready():
        if os.environ.get("IMG_TAGGER_NO_OPEN") == "1":
            return
        for _ in range(40):
            try:
                urllib.request.urlopen(URL, timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        _open_app_window()

    threading.Thread(target=_open_when_ready, daemon=True).start()
    print(f"图片分类器已启动：{URL}（关闭本窗口即退出）")
    uvicorn.run(app, host=HOST, port=PORT)
