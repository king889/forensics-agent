#!/usr/bin/env bash
# 自动驱动：反复 `fcase go` 直到没有待做组，或连续两轮没有进展。
#
#   fcase drive [轮数上限]      # 在 case 目录下执行
#
# 为什么要它：`fcase go` 一次只派一轮，跑完会把未完成的组退回 todo 然后退出。
# 人工反复调用容易忘。这个脚本自己在后台转，日志写 meta/drive.log，
# 进度用 `fcase status` 看。
set -uo pipefail

CASE_DIR="$(pwd)"
[ -d "$CASE_DIR/meta" ] || { echo "drive: 当前目录不是 case（缺 meta/）" >&2; exit 2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FCASE="$(cd "$SCRIPT_DIR/../.." && pwd)/bin/fcase"
DB="$CASE_DIR/meta/evidence.db"
LOG="$CASE_DIR/meta/drive.log"
MAX="${1:-12}"
cd "$CASE_DIR" || exit 1

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "$LOG"; }

todo() {
    python3 - "$DB" <<'PY'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1], timeout=30)
n = db.execute("SELECT count(*) FROM groups WHERE status IN ('todo','doing')").fetchone()[0]
a = db.execute("SELECT count(DISTINCT qid) FROM answers WHERE qid IS NOT NULL").fetchone()[0]
t = db.execute("SELECT count(*) FROM questions").fetchone()[0]
print(f"{n} {a} {t}")
PY
}

prev=-1
for i in $(seq 1 "$MAX"); do
    read -r n a t <<<"$(todo)"
    log "第 $i 轮：待做组 $n，已答 $a/$t"
    if [ "$n" = "0" ]; then log "没有待做组了，结束"; break; fi
    if [ "$a" = "$prev" ] && [ "$i" -gt 1 ]; then
        log "连续两轮无新增答案，停在 $a/$t（剩余组看 meta/blocked.md）"; break
    fi
    prev="$a"
    rm -f meta/.solve-par.pid
    "$FCASE" go >>"$LOG" 2>&1
    sleep 3
done

read -r n a t <<<"$(todo)"
log "驱动结束：待做组 $n，已答 $a/$t"
"$FCASE" status 2>&1 | head -6 >>"$LOG"
