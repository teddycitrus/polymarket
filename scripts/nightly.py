"""Unattended nightly run: resolve settled markets, forecast a fresh batch,
then write a morning digest.

    python scripts/nightly.py --limit 10

Designed to be driven by Windows Task Scheduler. Each stage is isolated so one
failure doesn't abort the rest. Output is logged to data/logs/ and the morning
board is saved to data/digests/<date>.txt so you can just open today's file.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT / "src"))


def _run(label: str, args: list[str], log) -> int:
    """Run a sibling script with the same interpreter, teeing output to log."""
    stamp = datetime.now().strftime("%H:%M:%S")
    header = f"\n===== [{stamp}] {label} =====\n"
    print(header, end="")
    log.write(header)
    log.flush()
    proc = subprocess.run([sys.executable, *args], cwd=str(ROOT), capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out, end="")
    log.write(out)
    log.flush()
    if proc.returncode != 0:
        msg = f"[WARN] {label} exited with code {proc.returncode}\n"
        print(msg, end="")
        log.write(msg)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly resolve + batch + digest.")
    parser.add_argument("--limit", type=int, default=10, help="markets to forecast (default 10)")
    parser.add_argument("--low", type=float, default=0.10)
    parser.add_argument("--high", type=float, default=0.90)
    parser.add_argument("--top", type=int, default=15, help="markets to show in the digest")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    logs_dir = ROOT / "data" / "logs"
    digests_dir = ROOT / "data" / "digests"
    logs_dir.mkdir(parents=True, exist_ok=True)
    digests_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"nightly-{today}.log"

    with open(log_path, "a", encoding="utf-8") as log:
        start = f"\n########## NIGHTLY RUN {datetime.now().isoformat()} ##########\n"
        print(start, end="")
        log.write(start)

        # 1) Record outcomes for anything that settled since last run.
        _run("resolve-markets", [str(SCRIPTS / "resolve-markets.py")], log)

        # 2) Forecast a fresh batch of mid-tier markets.
        _run(
            "batch-forecasts",
            [str(SCRIPTS / "batch-forecasts.py"), "--limit", str(args.limit),
             "--low", str(args.low), "--high", str(args.high)],
            log,
        )

        # 3) Build the morning digest (also printed by morning.py on demand).
        from score import connect  # noqa: E402
        from importlib import import_module
        sys.path.insert(0, str(SCRIPTS))
        morning = import_module("morning")
        conn = connect()
        digest = morning.render(conn, args.top)
        conn.close()

        digest_path = digests_dir / f"{today}.txt"
        digest_path.write_text(digest, encoding="utf-8")
        log.write("\n" + digest + "\n")
        print(f"\nDigest written: {digest_path}")
        log.write(f"\nDigest written: {digest_path}\n")

    print(f"Log: {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
