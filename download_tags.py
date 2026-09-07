# -*- coding: utf-8 -*-
"""下载并解析 EhTagTranslation/Database 的 tag 数据，生成本地词典 eht_tags.json。

数据源：https://github.com/EhTagTranslation/Database
输出：eht_tags.json，结构 {"namespaces": {ns: 中文分类名}, "tags": {中文名: {ns, ns_name, raw}}}
"""
import json
import re
import sys

import requests

BASE = "https://raw.githubusercontent.com/EhTagTranslation/Database/master/database/"

NAMESPACES = ["rows", "reclass", "language", "parody", "character", "group",
              "artist", "cosplayer", "male", "female", "mixed", "other", "location"]


def parse_ns_name(text: str, ns: str) -> str:
    m = re.search(r"^name:\s*(.+)$", text, re.M)
    if m:
        return m.group(1).strip()
    return ns


def parse_tags(text: str):
    tags = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and "---" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] and cells[1]:
                raw = cells[0]
                zh = cells[1]
                # 跳过表头
                if raw.startswith("原始") or raw.startswith("标签") or raw == "raw":
                    continue
                tags.append((raw, zh))
    return tags


def main():
    result = {"namespaces": {}, "tags": {}}
    for i, ns in enumerate(NAMESPACES):
        url = BASE + ns + ".md"
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            text = r.text
        except Exception as e:
            print(f"[跳过] {ns}: {e}", file=sys.stderr)
            continue
        ns_name = parse_ns_name(text, ns)
        result["namespaces"][ns] = ns_name
        for raw, zh in parse_tags(text):
            result["tags"][zh] = {"ns": ns, "ns_name": ns_name, "raw": raw}
        print(f"[{i+1}/{len(NAMESPACES)}] {ns}({ns_name}) 已解析，累计标签 {len(result['tags'])}")

    out = "eht_tags.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"\n完成：{len(result['namespaces'])} 个分类，{len(result['tags'])} 个中文标签 -> {out}")


if __name__ == "__main__":
    main()
