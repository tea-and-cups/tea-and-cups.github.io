"""写真の段: prompts/<名前>.txt → codex-gateway.py --purpose image-gen → images/<名前>.png → 1440×2160 の work/img/<名前>.jpg。
試作の gen_images.py・prep_images.py を移したもの。images/<名前>.png が既にある写真は作り直さない（消せば作り直す）。"""
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

from PIL import Image, ImageFilter

from video.runtime import GATEWAY

W, H = 1440, 2160


def generate(d, names, prefix):
    """無い写真だけを gateway で1枚ずつ作る。記録は images/gen.log。返り値: 作った名前"""
    (d / "images").mkdir(parents=True, exist_ok=True)
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
