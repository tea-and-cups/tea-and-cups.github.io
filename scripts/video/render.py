"""書き出しの段（render）と仕上げの段（finalize）。試作の hf.py の render を移したもの。
render: 実行環境の HyperFrames CLI を node で呼ぶ（--workers 1 --player-ready-timeout 180000）。env は data/video-runtime.json の hyperframes.env。
  lint の中身を見られるよう --lint-verbose を付け、CLI の出力は work/render.log に残す。所要秒と履歴（home の history）の増加量を返す。
finalize: faststart（moov を先頭へ）だけを行う。映像と音は写すだけ（-c copy）。音の載せ直しとメタデータの書き込みはしない。
  写したあと、moov が mdat より前にあること・映像と音のパケットが元と同じこと（streamhash）を確かめる。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tree_size(path):
    total, files = 0, 0
    for base, _, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(base, n))
                files += 1
            except OSError:
                pass
    return total, files


def history(rt):
    """書き出しの履歴（home/.cache/hyperframes/history）の UUID 形のフォルダを、更新の新しい順に返す。[(名前, bytes, files, mtime)]"""
    root = rt.hf_history
    out = []
    if os.path.isdir(root):
        for n in os.listdir(root):
            p = os.path.join(root, n)
            if os.path.isdir(p) and UUID.match(n):
                b, f = tree_size(p)
                out.append((n, b, f, os.path.getmtime(p)))
    return sorted(out, key=lambda x: -x[3])


def lint_from_log(text):
    """--lint-verbose の出力から lint の指摘を拾う（⚠ が warning・✖ が error。1件1行の「[ファイル] 名前: 説明」）"""
    found = re.findall(r"^\s*([⚠✖]) \[([^\]]+)\] ([a-z_]+):", text, re.M)
    return {"warnings": sum(k == "⚠" for k, _, _ in found), "errors": sum(k == "✖" for k, _, _ in found),
            "items": [f"{f} {name}" for _, f, name in found]}


def render(comp, rt, out, log):
    """composition を全編書き出す。返り値: 記録（秒・終了コード・出力の bytes と sha256・履歴の前後）"""
    before = tree_size(rt.hf_history)
    t0 = time.time()
    r = subprocess.run(["node", rt.hf_cli, "render", str(comp), "-o", str(out), "--workers", "1",
                        "--player-ready-timeout", "180000", "--lint-verbose"],
                       env=rt.env("hyperframes"), capture_output=True, text=True, encoding="utf-8", errors="replace")
    sec = time.time() - t0
    log.write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    after = tree_size(rt.hf_history)
    rec = {"seconds": round(sec, 1), "exit": r.returncode, "log": str(log.name),
           "history_before": {"bytes": before[0], "files": before[1]}, "history_after": {"bytes": after[0], "files": after[1]},
           "history_added_bytes": after[0] - before[0], "history_added_files": after[1] - before[1]}
    rec["lint"] = lint_from_log(r.stdout + r.stderr)
    if r.returncode == 0 and out.exists():
        rec["bytes"] = out.stat().st_size
        rec["sha256"] = sha256(out)
    return rec


def top_atoms(p):
    """MP4 の最上位の箱の並び（名前の列）"""
    names = []
    size = os.path.getsize(p)
    with open(p, "rb") as f:
        pos = 0
        while pos + 8 <= size:
            f.seek(pos)
            h = f.read(16)
            n = int.from_bytes(h[:4], "big")
            kind = h[4:8].decode("latin-1")
            if n == 1:
                n = int.from_bytes(h[8:16], "big")
            elif n == 0:
                n = size - pos
            names.append(kind)
            if n < 8:
                break
            pos += n
    return names


def streamhash(rt, p):
    r = subprocess.run([rt.ffmpeg, "-v", "error", "-i", str(p), "-map", "0", "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip().splitlines()


def compare(rt, a, b):
    """2本の中身の差: 映像の PSNR（平均。同じなら inf）と、音の差の最大（dB。同じなら -inf か無音の床）"""
    v = subprocess.run([rt.ffmpeg, "-hide_banner", "-nostats", "-i", str(a), "-i", str(b), "-lavfi", "[0:v][1:v]psnr", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    s = subprocess.run([rt.ffmpeg, "-hide_banner", "-nostats", "-i", str(a), "-i", str(b), "-filter_complex",
                        "[0:a][1:a]amerge=inputs=2,pan=stereo|c0=c0-c2|c1=c1-c3,volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    psnr = re.search(r"average:(\S+)", v)
    vol = re.search(r"max_volume: (\S+) dB", s)
    return {"psnr_average": psnr.group(1) if psnr else None, "audio_diff_max_db": vol.group(1) if vol else None}


BRAND_TAGS = ("major_brand", "minor_version", "compatible_brands")


def tags(rt, p):
    """形式のタグ（ftyp から来る3つは除く。ftyp の値そのものは finalize で変えない）"""
    r = subprocess.run([rt.ffprobe, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(p)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    t = json.loads(r.stdout).get("format", {}).get("tags", {})
    return {k: v for k, v in t.items() if k not in BRAND_TAGS}


def finalize(rt, raw, out):
    """faststart だけ。返り値: 記録（moov と mdat の順・streamhash が元と同じか・PSNR と音の差・タグが元と同じか・sha256）"""
    tmp = out.with_name(out.stem + ".tmp.mp4")
    t0 = time.time()
    # use_metadata_tags: HyperFrames が書いた独自のタグ（hyperframes_version など）を落とさない。
    # この指定は ftyp の値（major_brand など）もタグとして写し直して重ねるので、その3つは空にする（ftyp そのものは残る）
    subprocess.run([rt.ffmpeg, "-y", "-v", "error", "-i", str(raw), "-map", "0", "-c", "copy",
                    "-metadata", "major_brand=", "-metadata", "minor_version=", "-metadata", "compatible_brands=",
                    "-movflags", "+faststart+use_metadata_tags", str(tmp)], check=True)
    shutil.move(str(tmp), str(out))
    atoms = top_atoms(out)
    same = streamhash(rt, raw) == streamhash(rt, out)
    return {"seconds": round(time.time() - t0, 1), "atoms": atoms,
            "moov_before_mdat": "moov" in atoms and "mdat" in atoms and atoms.index("moov") < atoms.index("mdat"),
            "atoms_raw": top_atoms(raw), "streams_same_as_raw": same, "tags_same_as_raw": tags(rt, raw) == tags(rt, out),
            **compare(rt, raw, out),
            "bytes": out.stat().st_size, "sha256": sha256(out)}


def clean_history(rt, keep=1):
    """history の下の UUID 形のフォルダのうち、新しい keep 件より古いものを消す（shutil.rmtree）。
    消さないもの: history/.last-prune・home/.hyperframes/（config.json など）・.cache/fontconfig。返り値: 記録"""
    root = rt.hf_history
    home = os.path.dirname(os.path.dirname(os.path.dirname(root)))
    before = tree_size(home)
    items = history(rt)
    removed = []
    for n, b, f, _ in items[keep:]:
        target = os.path.join(root, n)
        if os.path.dirname(os.path.abspath(target)) != os.path.abspath(root) or not UUID.match(n):
            raise SystemExit(f"消す対象の形が違う: {target}")
        shutil.rmtree(target)
        removed.append({"id": n, "bytes": b, "files": f})
    after = tree_size(home)
    return {"home": home, "before": {"bytes": before[0], "files": before[1]}, "after": {"bytes": after[0], "files": after[1]},
            "kept": [n for n, *_ in items[:keep]], "removed": removed}
