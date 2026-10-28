# -*- coding: utf-8 -*-
r"""動画の実行環境（声・書き出し・ffmpeg・素材）が、data/video-runtime.json の照合値どおりかを確かめる（D-0299）。

背景:
  動画の制作に要る道具と素材は、プロジェクトの外の実行環境（json の root）にまとめてある。
  道具の版や重みが知らないうちに変わると、同じ台本・同じ作品でも声や画が変わる。
  そこで制作の前に、場所と照合値を機械的に確かめる。旧い場所（xx-0007 など）へ自動で戻る道は持たない。

入力:
  data/video-runtime.json   場所と照合値（path は root からの相対。env の {root} は root に置き換える）。
                            値はコピー後の実物から計測したもの。経緯は reports/2026-10-28-2.md。

毎回確かめること:
  各パスの存在 / 小さいファイル（SMALL_BYTES 以下）の sha256 / 大きいファイル（重み・exe）の bytes /
  uv・python・ffmpeg・ffprobe の版（--version の出力）/ hyperframes の版（package.json）/ node の版の下限 /
  Irodori-TTS の commit（.git を読む）/ .venv の home・版・torch と transformers の dist-info /
  env の必須値（通信を止める項目と、ブラウザ・ffprobe・ffmpeg のパスが json の実物と同じか）

使い方:
  python site/scripts/check-video-runtime.py
  python site/scripts/check-video-runtime.py --verify-full      大きいファイルの sha256 も確かめる（重み 3GB を含む）
  python site/scripts/check-video-runtime.py --config <json>    別の json で確かめる

出力と終了コード:
  0  RUNTIME_OK …
  1  RUNTIME_MISMATCH <項目> expected=… got=…   （1項目につき1行）
  2  RUNTIME_CONFIG_ERROR …   json が無い・壊れている・必須の項目が無い
読み取りのみ。何も書き換えない。
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CONFIG = os.path.join(PROJECT_ROOT, "data", "video-runtime.json")
SMALL_BYTES = 64 * 1024 * 1024  # これ以下は毎回 sha256、超えるものは bytes のみ（--verify-full で sha256 も）
REQUIRED_ENV = {
    "tts": {"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "UV_NO_CONFIG": "1",
            "UV_PYTHON_PREFERENCE": "only-managed"},
    "hyperframes": {"HYPERFRAMES_NO_UPDATE_CHECK": "1", "HYPERFRAMES_NO_AUTO_INSTALL": "1",
                    "HYPERFRAMES_NO_TELEMETRY": "1"},
}

MARK_OK = "RUNTIME_OK"
MARK_MISMATCH = "RUNTIME_MISMATCH"
MARK_CONFIG = "RUNTIME_CONFIG_ERROR"


class Checker:
    def __init__(self, cfg, verify_full):
        self.root = cfg["root"]
        self.verify_full = verify_full
        self.mismatches = []
        self.count = 0

    def mismatch(self, item, expected, got):
        self.mismatches.append(f"{MARK_MISMATCH} {item} expected={expected} got={got}")

    def same(self, item, expected, got):
        self.count += 1
        if expected != got:
            self.mismatch(item, expected, got)

    def path(self, rel):
        return os.path.join(self.root, rel)

    def exists(self, item, rel):
        self.count += 1
        if not os.path.exists(self.path(rel)):
            self.mismatch(item, "exists:" + rel, "missing")
            return False
        return True

    def file(self, item, ent):
        """path の存在・小さいファイルの sha256・大きいファイルの bytes（--verify-full で sha256 も）"""
        rel = ent["path"]
        if not self.exists(item + ".path", rel):
            return
        size = os.path.getsize(self.path(rel))
        if "bytes" in ent:
            self.same(item + ".bytes", ent["bytes"], size)
        if size <= SMALL_BYTES or self.verify_full:
            self.same(item + ".sha256", ent["sha256"], sha256(self.path(rel)))

    def version(self, item, ent, args, pick):
        if not os.path.exists(self.path(ent["path"])):
            return
        self.same(item + ".version", ent["version"], pick(first_line([self.path(ent["path"])] + args)))


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def first_line(args):
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return f"error:{type(e).__name__}"
    lines = (r.stdout or r.stderr).strip().splitlines()
    return lines[0] if lines else "empty"


def token(i):
    def pick(line):
        parts = line.split()
        return parts[i] if len(parts) > i else line
    return pick


def git_commit(repo):
    git = os.path.join(repo, ".git")
    try:
        head = open(os.path.join(git, "HEAD"), encoding="utf-8").read().strip()
    except OSError:
        return None, "missing"
    if not head.startswith("ref: "):
        return None, head
    ref = head[5:]
    loose = os.path.join(git, ref)
    if os.path.exists(loose):
        return ref, open(loose, encoding="utf-8").read().strip()
    packed = os.path.join(git, "packed-refs")
    if os.path.exists(packed):
        for line in open(packed, encoding="utf-8"):
            if line.rstrip().endswith(" " + ref):
                return ref, line.split()[0]
    return ref, "missing"


def resolve_env(value, root):
    return value.replace("{root}", root)


def check_tts(c, t):
    c.file("tts.uv", t["uv"])
    c.version("tts.uv", t["uv"], ["--version"], token(1))
    c.file("tts.python", t["python"])
    c.version("tts.python", t["python"], ["--version"], token(1))

    repo = t["repo"]
    if c.exists("tts.repo.path", repo["path"]):
        ref, commit = git_commit(c.path(repo["path"]))
        c.same("tts.repo.ref", repo["ref"], ref)
        c.same("tts.repo.commit", repo["commit"], commit)
        if c.exists("tts.repo.uv_lock", repo["path"] + "/uv.lock"):
            c.same("tts.repo.uv_lock_sha256", repo["uv_lock_sha256"], sha256(c.path(repo["path"] + "/uv.lock")))

    venv = t["venv"]
    if c.exists("tts.venv.python", venv["python"]):
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(c.path(venv["python"]))), "pyvenv.cfg")
        cfg = {}
        if os.path.exists(cfg_path):
            for line in open(cfg_path, encoding="utf-8"):
                if " = " in line:
                    k, v = line.rstrip("\n").split(" = ", 1)
                    cfg[k] = v
        c.same("tts.venv.home", os.path.normcase(os.path.normpath(c.path(venv["home"]))),
               os.path.normcase(os.path.normpath(cfg.get("home", "missing"))))
        c.same("tts.venv.version_info", venv["version_info"], cfg.get("version_info", "missing"))
        site = os.path.join(os.path.dirname(os.path.dirname(c.path(venv["python"]))), "Lib", "site-packages")
        for pkg in ("torch", "transformers"):
            found = sorted(re.match(rf"{pkg}-(.+)\.dist-info$", os.path.basename(p)).group(1)
                           for p in glob.glob(os.path.join(site, f"{pkg}-*.dist-info")))
            c.same(f"tts.venv.{pkg}", venv[pkg], ",".join(found) or "missing")
        c.same("tts.venv.dist_info_count", venv["dist_info_count"], len(glob.glob(os.path.join(site, "*.dist-info"))))

    c.file("tts.runner", t["runner"])
    c.file("tts.env_ps1", t["env_ps1"])
    c.exists("tts.hf_home", t["hf_home"])
    for m in t["models"]:
        name = "tts.models." + m["repo"]
        base = f'{t["hf_home"]}/hub/models--{m["repo"].replace("/", "--")}'
        if c.exists(name + ".refs_main", base + "/refs/main"):
            c.same(name + ".revision", m["revision"], open(c.path(base + "/refs/main"), encoding="utf-8").read().strip())
        for f in m["files"]:
            c.file(name + "." + f["path"].split("/snapshots/", 1)[-1].split("/", 1)[-1], f)

    for k, v in REQUIRED_ENV["tts"].items():
        c.same("tts.env." + k, v, t["env"].get(k, "missing"))
    c.same("tts.env.HF_HOME", c.path(t["hf_home"]).replace("\\", "/"),
           resolve_env(t["env"].get("HF_HOME", "missing"), c.root))


def check_hyperframes(c, h):
    c.file("hyperframes.package_json", h["package_json"])
    c.file("hyperframes.lock", h["lock"])
    c.file("hyperframes.cli", h["cli"])
    pkg = os.path.join(os.path.dirname(os.path.dirname(c.path(h["cli"]["path"]))), "package.json")
    if os.path.exists(pkg):
        c.same("hyperframes.version", h["version"], json.load(open(pkg, encoding="utf-8")).get("version"))
    for n in h["native"]:
        c.file("hyperframes.native." + os.path.basename(n["path"]), n)
    c.file("hyperframes.browser", h["browser"])
    c.exists("hyperframes.home", h["home"])

    node = shutil.which("node")
    c.count += 1
    if not node:
        c.mismatch("hyperframes.node", f">={h['node_min']}", "missing")
    else:
        v = first_line([node, "-v"])
        m = re.match(r"v(\d+)", v)
        if not m or int(m.group(1)) < h["node_min"]:
            c.mismatch("hyperframes.node", f">={h['node_min']}", v)

    env = h["env"]
    for k, v in REQUIRED_ENV["hyperframes"].items():
        c.same("hyperframes.env." + k, v, env.get(k, "missing"))
    c.same("hyperframes.env.HYPERFRAMES_BROWSER_PATH", c.path(h["browser"]["path"]).replace("\\", "/"),
           resolve_env(env.get("HYPERFRAMES_BROWSER_PATH", "missing"), c.root))


def check_ffmpeg(c, f):
    for name in ("ffmpeg", "ffprobe"):
        c.file("ffmpeg." + name, f[name])
        c.version("ffmpeg." + name, f[name], ["-version"], token(2))


def check_assets(c, a):
    for name, ent in a.items():
        c.file("assets." + name, ent)


def main():
    ap = argparse.ArgumentParser(description="動画の実行環境を data/video-runtime.json の照合値と比べる")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--verify-full", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    try:
        with open(args.config, encoding="utf-8") as fp:
            cfg = json.load(fp)
    except FileNotFoundError:
        print(f"{MARK_CONFIG} json が無い: {args.config}")
        return 2
    except (OSError, ValueError) as e:
        print(f"{MARK_CONFIG} json が読めない: {args.config} ({e})")
        return 2

    try:
        c = Checker(cfg, args.verify_full)
        if not c.exists("root", ""):
            print("\n".join(c.mismatches))
            return 1
        check_tts(c, cfg["tts"])
        check_hyperframes(c, cfg["hyperframes"])
        check_ffmpeg(c, cfg["ffmpeg"])
        check_assets(c, cfg["assets"])
        for key, name in (("HYPERFRAMES_FFPROBE_PATH", "ffprobe"), ("HYPERFRAMES_FFMPEG_PATH", "ffmpeg")):
            got = resolve_env(cfg["hyperframes"]["env"].get(key, "missing"), c.root)
            c.same("hyperframes.env." + key, c.path(cfg["ffmpeg"][name]["path"]).replace("\\", "/"), got)
    except (KeyError, TypeError, AttributeError) as e:
        print(f"{MARK_CONFIG} 必須の項目が無い・型が違う: {args.config} ({type(e).__name__}: {e})")
        return 2

    if c.mismatches:
        print("\n".join(c.mismatches))
        return 1
    full = "大きいファイルも sha256 で照合" if args.verify_full else "大きいファイルは bytes で照合（--verify-full で sha256）"
    print(f"{MARK_OK} 照合 {c.count} 項目・{full}・root={c.root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
