#!/bin/bash
# 最近ダウンロードしたファイルを新しい順に5件表示する（hero画像の取り込み元確認用）
set -euo pipefail
ls -lt ~/Downloads | head -5
