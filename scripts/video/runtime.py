"""動画の実行環境（data/video-runtime.json・D-0299）の場所を引く。道具と素材のパスはすべて json の root から組み立てる。"""
import json
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPTS_DIR))
CONFIG = os.path.join(PROJECT_ROOT, "data", "video-runtime.json")
CHECKER = os.path.join(SCRIPTS_DIR, "check-video-runtime.py")
GATEWAY = os.path.join(SCRIPTS_DIR, "codex-gateway.py")


def check():
    """check-video-runtime.py を呼ぶ。返り値: (RUNTIME_OK か, 出力の全文)"""
    r = subprocess.run([sys.executable, CHECKER], capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0 and out.startswith("RUNTIME_OK"), out


class Runtime:
    def __init__(self, path=CONFIG):
        with open(path, encoding="utf-8") as fp:
            self.cfg = json.load(fp)
        self.root = self.cfg["root"]

    def path(self, rel):
        return os.path.normpath(os.path.join(self.root, rel))

    @property
    def ffmpeg(self):
        return self.path(self.cfg["ffmpeg"]["ffmpeg"]["path"])

    @property
    def ffprobe(self):
        return self.path(self.cfg["ffmpeg"]["ffprobe"]["path"])

    def asset(self, name):
        return self.path(self.cfg["assets"][name]["path"])

    def asset_sha256(self, name):
        return self.cfg["assets"][name]["sha256"]

    @property
    def hf_cli(self):
        return self.path(self.cfg["hyperframes"]["cli"]["path"])

    @property
    def hf_history(self):
        return os.path.join(self.path(self.cfg["hyperframes"]["home"]), ".cache", "hyperframes", "history")

    @property
    def tts_python(self):
        return self.path(self.cfg["tts"]["venv"]["python"])

    @property
    def tts_repo(self):
        return self.path(self.cfg["tts"]["repo"]["path"])

    @property
    def tts_runner(self):
        return self.path(self.cfg["tts"]["runner"]["path"])

    def env(self, section):
        """os.environ に json の env（{root} を置き換えたもの）を重ねる。section は tts か hyperframes。"""
        env = dict(os.environ)
        for k, v in self.cfg[section]["env"].items():
            env[k] = v.replace("{root}", self.root)
        return env
