"""写真の段: prompts/<名前>.txt → codex-gateway.py --purpose image-gen → images/<名前>.png → 1440×2160 の work/img/<名前>.jpg。
試作の gen_images.py・prep_images.py を移したもの。images/<名前>.png が既にある写真は作り直さない（消せば作り直す）。

画像生成の上限（日次の画像生成と利用上限を分け合うため・D-0308）。作る前に、作る枚数ぶんが次のすべてに収まるかを見て、超えるなら1枚も作らずに止める。
  1本で VIDEO_GEN_MAX 回まで／直近 WEEK_DAYS 日の動画の写真の合計で WEEK_GEN_MAX 回まで（試み1回を1回と数える・テストと本番を合わせる）／
  日次の画像生成（tmp/codex-gateway/ の image-gen のログのうち、動画の写真の記録に当たらないもの）から DAILY_GAP_HOURS 時間以内は作らない
記録: 試みるたびに video-N.build.json の image_gens に {at, name} を足す。この仕組みの前の動画は、images の段の記録の generated の数を
  その段の時刻で数える（image_gens_logged の無い記録だけ）。"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageFilter

from video.runtime import GATEWAY, PROJECT_ROOT

W, H = 1440, 2160
VIDEO_GEN_MAX = 6
WEEK_GEN_MAX = 12
WEEK_DAYS = 7
DAILY_GAP_HOURS = 5
GATEWAY_LOGS = Path(PROJECT_ROOT) / "tmp" / "codex-gateway"
GATEWAY_LOG_RE = re.compile(r"^(\d{8}-\d{6})-image-gen\.jsonl$")
MATCH_BEFORE, MATCH_AFTER = timedelta(seconds=2), timedelta(seconds=120)   # 動画の記録の時刻と gateway のログの名前の時刻の突き合わせの幅


def gen_events(videos_dir):
    """動画の写真の生成の記録: [(時刻, 動画のフォルダ名, gateway のログと突き合わせる始め, 終わり)]"""
    out = []
    for p in sorted(Path(videos_dir).glob("video-*/video-*.build.json")):
        try:
            log = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        name = p.parent.name
        for g in log.get("image_gens", []):
            t = datetime.fromisoformat(g["at"])
            out.append((t, name, t - MATCH_BEFORE, t + MATCH_AFTER))
        for r in log.get("runs", []):
            if r.get("stage") == "images" and r.get("generated") and not r.get("image_gens_logged"):
                t = datetime.fromisoformat(r["at"])
                start = t - timedelta(seconds=float(r.get("stage_seconds") or 0)) - MATCH_BEFORE
                out += [(t, name, start, t)] * len(r["generated"])
    return out


def daily_gens(events, now, log_dir=GATEWAY_LOGS):
    """直近 DAILY_GAP_HOURS 時間の gateway の image-gen のうち、動画の写真の記録に当たらないもの（日次の画像生成）の時刻"""
    found = []
    for p in Path(log_dir).glob("*-image-gen.jsonl"):
        m = GATEWAY_LOG_RE.match(p.name)
        if not m:
            continue
        t = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
        if now - timedelta(hours=DAILY_GAP_HOURS) < t <= now and not any(s <= t <= e for _, _, s, e in events):
            found.append(t)
    return sorted(found)


def budget(d, videos_dir, want, now=None, log_dir=GATEWAY_LOGS):
    """want 回作れるか。返り値: (作れるか, 表示の行。止めるときは理由の行を足す)"""
    now = now or datetime.now()
    events = gen_events(videos_dir)
    mine = sum(1 for e in events if e[1] == d.name)
    week = sum(1 for e in events if now - timedelta(days=WEEK_DAYS) < e[0] <= now)
    daily = daily_gens(events, now, log_dir)
    lines = [f"画像生成の上限: この動画 {mine}+{want}/{VIDEO_GEN_MAX}回・直近{WEEK_DAYS}日の動画の写真 {week}+{want}/{WEEK_GEN_MAX}回・"
             f"直近{DAILY_GAP_HOURS}時間の日次の画像生成 {len(daily)}回（基準 {now:%Y-%m-%d %H:%M}）"]
    ng = []
    if mine + want > VIDEO_GEN_MAX:
        ng.append(f"1本の上限を超える（{mine}+{want} > {VIDEO_GEN_MAX}回）")
    if week + want > WEEK_GEN_MAX:
        ng.append(f"直近{WEEK_DAYS}日の動画の写真の上限を超える（{week}+{want} > {WEEK_GEN_MAX}回）")
    if want and daily:
        ng.append(f"日次の画像生成（{daily[-1]:%m-%d %H:%M}）から{DAILY_GAP_HOURS}時間たっていない（{daily[-1] + timedelta(hours=DAILY_GAP_HOURS):%m-%d %H:%M} 以降に作る）")
    return not ng, lines + ng


def log_gen(log_path, name):
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else {"runs": []}
    log.setdefault("image_gens", []).append({"at": datetime.now().isoformat(timespec="seconds"), "name": name})
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def generate(d, names, prefix, log_path, videos_dir, now=None):
    """無い写真だけを gateway で1枚ずつ作る（作る前に上限を見る）。記録は images/gen.log と build.json の image_gens。返り値: 作った名前"""
    (d / "images").mkdir(parents=True, exist_ok=True)
    want = [n for n in names if not (d / "images" / f"{n}.png").exists()]
    if want:
        ok, lines = budget(d, videos_dir, len(want), now)
        for line in lines:
            print(f"images: {line}")
        if not ok:
            raise SystemExit(f"画像生成の上限で止めた（{'・'.join(lines[1:])}）。この動画の写真の生成はここでやめる（rules/video-production.md 3節）")
    log = d / "images" / "gen.log"
    made = []

    def w(s):
        with log.open("a", encoding="utf-8") as f:
            f.write(s + "\n")
        print(s, flush=True)

    for n in names:
        if (d / "images" / f"{n}.png").exists():
            continue
        t0 = time.time()
        log_gen(log_path, n)
        w(f"[{datetime.now():%H:%M:%S}] start {n}")
        out = f"{prefix}-{n}.png"
        r = subprocess.run([sys.executable, GATEWAY, "--purpose", "image-gen", "--prompt-file", str(d / "prompts" / f"{n}.txt"),
                            "--out-name", out], capture_output=True, text=True, encoding="utf-8", errors="replace")
        w("STDOUT: " + r.stdout.strip())
        w("STDERR(tail): " + r.stderr.strip()[-1500:])
        src = os.path.join(os.environ["USERPROFILE"], "Downloads", out)
        if os.path.exists(src):
            shutil.copy2(src, d / "images" / f"{n}.png")
            made.append(n)
        w(f"[{datetime.now():%H:%M:%S}] end {n} exit={r.returncode} sec={time.time() - t0:.0f} copied={os.path.exists(src)}")
        if not os.path.exists(src):
            raise SystemExit(f"写真を作れなかった: {n}（images/gen.log）")
    return made


def prep(d, names):
    """縦の写真を寄り・流しの余白つきの 1440×2160 に Lanczos で広げ、弱いアンシャープをかけて work/img/<名前>.jpg（品質 93）に書く。
    縦横比が 2:3 でない画像は中央で 2:3 に切る。"""
    out = d / "work" / "img"
    out.mkdir(parents=True, exist_ok=True)
    for n in names:
        im = Image.open(d / "images" / f"{n}.png").convert("RGB")
        w, h = im.size
        if abs(w / h - 2 / 3) > 0.01:
            if w / h > 2 / 3:
                nw = int(h * 2 / 3)
                im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
            else:
                nh = int(w * 3 / 2)
                im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        im = im.resize((W, H), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.6, percent=45, threshold=2))
        im.save(out / f"{n}.jpg", quality=93, subsampling=0)
