"""
Brainboda pipeline orchestrator.

Connects all 7 pipeline steps end-to-end.

Usage:
    # Wikipedia mode (requires facts_raw.csv)
    python run.py --type main                    # full pipeline
    python run.py --type short                   # shorts pipeline
    python run.py --type main --test             # render only, no upload, first 2 facts
    python run.py --type main --skip-upload      # all steps except upload
    python run.py --type main --topic manipulation  # specific topic

    # AI mode (Claude Haiku — no CSV needed, ~$0.008/video)
    python run.py --type main --ai               # auto-pick theme
    python run.py --type main --ai --skip-upload # AI script, no upload
    python run.py --type main --ai --theme "dark psychology"   # specific theme
    python run.py --type short --ai              # AI shorts, auto-pick theme
    python run.py --type short --ai --theme "cognitive biases" # AI shorts, specific theme
    python run.py --type short --from-main output/20260612_main/script.json  # 메인에서 발췌

    # Use existing script (skip steps 1-2)
    python run.py --script output/20240101_120000_main/script.json

    2026-10-13: 03_tts 실패 시 파이프라인 중단 (기존 continuing anyway 제거)
"""

import argparse
import glob
import json
import logging
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config.channel import (
    DATA_DIR,
    FACTS_PER_VIDEO,
    FACTS_PER_SHORT,
    FACTS_RAW_CSV,
    LOGS_DIR,
    OUTPUT_DIR,
    USED_FACTS_JSON,
)

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"run_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

PIPELINE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline")
PYTHON = sys.executable


def run_step(name: str, cmd: list, allow_fail: bool = False) -> bool:
    """Run a pipeline step subprocess. Returns True on success."""
    log.info("─" * 60)
    log.info("STEP: %s", name)
    log.info("CMD:  %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, timeout=7200)
        if result.returncode == 0:
            log.info("STEP %s — SUCCESS", name)
            return True
        else:
            log.error("STEP %s — FAILED (exit %d)", name, result.returncode)
            if not allow_fail:
                return False
            return False
    except subprocess.TimeoutExpired:
        log.error("STEP %s — TIMEOUT", name)
        return not allow_fail
    except Exception as exc:
        log.error("STEP %s — EXCEPTION: %s", name, exc)
        return not allow_fail


def count_available_facts(n_needed: int) -> int:
    """Count facts that will pass quality filter and haven't been used yet.

    Imports is_psychology_relevant from 02_build_script to use the same filter,
    so the count matches what build_script will actually find.
    """
    import csv as _csv
    source = FACTS_RAW_CSV

    # Prefer approved CSV if present
    approved = os.path.join(DATA_DIR, "facts_approved.csv")
    if os.path.exists(approved) and os.path.getsize(approved) > 10:
        source = approved

    if not os.path.exists(source):
        return 0

    used_ids: set = set()
    if os.path.exists(USED_FACTS_JSON):
        try:
            with open(USED_FACTS_JSON) as f:
                data = json.load(f)
            used_ids = set(data.get("used_ids", []))
        except Exception:
            pass

    # Import the same quality filter used by build_script
    try:
        sys.path.insert(0, PIPELINE_DIR)
        from importlib import import_module
        bs = import_module("02_build_script".replace("-", "_"))
        quality_filter = bs.is_psychology_relevant
    except Exception:
        quality_filter = None  # fallback: no filter (may overcount)

    try:
        count = 0
        with open(source, newline="", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                if row.get("id", "") in used_ids:
                    continue
                if quality_filter and not quality_filter(row):
                    continue
                count += 1
        return count
    except Exception:
        return 0


def find_latest_script(video_type: str = None, run_dir: str = None) -> str | None:
    if run_dir:
        p = os.path.join(run_dir, "script.json")
        return p if os.path.exists(p) else None
    pattern = os.path.join(OUTPUT_DIR, "script_*.json")
    if video_type:
        pattern = os.path.join(OUTPUT_DIR, f"script_{video_type}_*.json")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def find_latest_video(video_type: str = None, run_dir: str = None) -> str | None:
    if run_dir:
        p = os.path.join(run_dir, "video.mp4")
        return p if os.path.exists(p) else None
    pattern = os.path.join(OUTPUT_DIR, "video_*.mp4")
    if video_type:
        pattern = os.path.join(OUTPUT_DIR, f"video_{video_type}_*.mp4")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def find_latest_thumbnail(run_dir: str = None) -> str | None:
    if run_dir:
        p = os.path.join(run_dir, "thumbnail.jpg")
        return p if os.path.exists(p) else None
    files = glob.glob(os.path.join(OUTPUT_DIR, "thumbnail_*.jpg"))
    return max(files, key=os.path.getmtime) if files else None


def main():
    parser = argparse.ArgumentParser(description="Brainboda full pipeline orchestrator")
    parser.add_argument("--type", choices=["main", "short"], default="main",
                        help="Video type: main (10 facts) or short (3 facts)")
    parser.add_argument("--topic", type=str, default=None,
                        help="(Wikipedia mode) Topic keyword to filter facts")
    parser.add_argument("--ai", action="store_true",
                        help="Use Claude AI to generate script (Method B)")
    parser.add_argument("--theme", type=str, default=None,
                        help="(AI mode) Theme e.g. 'dark psychology'. Auto-picked if omitted.")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: render only 2 facts, no upload")
    parser.add_argument("--skip-upload", action="store_true",
                        help="Skip upload step")
    parser.add_argument("--from-main", type=str, default=None,
                        help="(Shorts) Extract best fact from this main script JSON to make a Short")
    parser.add_argument("--script", type=str, default=None,
                        help="Use existing script JSON, skip steps 1-2")
    args = parser.parse_args()

    do_upload = not args.test and not args.skip_upload

    log.info("=" * 65)
    log.info("BRAINBODA PIPELINE START")
    log.info("Type: %s | Topic: %s | Test: %s | SkipUpload: %s",
             args.type, args.topic or "any", args.test, args.skip_upload)
    log.info("=" * 65)

    start_time = datetime.now()
    results = {
        "script": None,
        "video": None,
        "thumbnail": None,
        "youtube_url": None,
        "steps_ok": [],
        "steps_failed": [],
    }

    # ── Determine run_dir ────────────────────────────────────────────────────
    if args.script:
        # Derive run_dir from the provided script's parent directory
        run_dir = os.path.dirname(os.path.abspath(args.script))
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = os.path.join(OUTPUT_DIR, f"{timestamp}_{args.type}")
        os.makedirs(run_dir, exist_ok=True)

    log.info("Run directory: %s", run_dir)

    def _build_script_cmd():
        cmd = [PYTHON, os.path.join(PIPELINE_DIR, "02_build_script.py"),
               "--type", args.type, "--run-dir", run_dir]
        if getattr(args, "from_main", None):
            cmd += ["--from-main", os.path.abspath(args.from_main)]
        elif args.ai:
            cmd.append("--ai")
            if args.theme:
                cmd += ["--theme", args.theme]
        elif args.topic:
            cmd += ["--topic", args.topic]
        return cmd

    # ── If script provided, skip steps 1-2 ───────────────────────────────────
    if args.script:
        if not os.path.exists(args.script):
            log.error("Script not found: %s", args.script)
            sys.exit(1)
        script_path = args.script
        log.info("Using provided script: %s", script_path)
        results["steps_ok"].extend(["01_fetch_facts (skipped)", "02_build_script (skipped)"])

    elif getattr(args, "from_main", None) or args.ai:
        # ── AI / from-main mode: skip step 1, run step 2 ─────────────────────
        mode_label = "from-main" if getattr(args, "from_main", None) else "AI"
        log.info("%s mode — skipping 01_fetch_facts (not needed)", mode_label)
        results["steps_ok"].append(f"01_fetch_facts (skipped — {mode_label} mode)")

        ok = run_step("02_build_script (AI)", _build_script_cmd())
        if not ok:
            log.error("02_build_script (AI) failed — cannot continue")
            sys.exit(1)
        results["steps_ok"].append("02_build_script")

        script_path = find_latest_script(args.type, run_dir=run_dir)
        if not script_path:
            log.error("Could not find generated script JSON")
            sys.exit(1)

    else:
        # ── Wikipedia mode ────────────────────────────────────────────────────
        # Step 1: Fetch facts if pool is low
        n_needed = FACTS_PER_SHORT if args.type == "short" else FACTS_PER_VIDEO
        available = count_available_facts(n_needed)
        log.info("Available unused facts: %d (need %d)", available, n_needed)

        if available < n_needed:
            log.info("Pool too small — running 01_fetch_facts.py")
            cmd = [PYTHON, os.path.join(PIPELINE_DIR, "01_fetch_facts.py")]
            if args.topic:
                cmd += ["--topic", args.topic]
            ok = run_step("01_fetch_facts", cmd, allow_fail=True)
            if ok:
                results["steps_ok"].append("01_fetch_facts")
            else:
                results["steps_failed"].append("01_fetch_facts")
                log.warning("01_fetch_facts failed — continuing with existing facts")
        else:
            log.info("Fact pool sufficient — skipping 01_fetch_facts.py")
            results["steps_ok"].append("01_fetch_facts (skipped)")

        # Step 2: Build script
        ok = run_step("02_build_script", _build_script_cmd())
        if not ok:
            log.warning("02_build_script failed — fetching fresh facts and retrying once")
            fetch_cmd = [PYTHON, os.path.join(PIPELINE_DIR, "01_fetch_facts.py")]
            if args.topic:
                fetch_cmd += ["--topic", args.topic]
            fetch_ok = run_step("01_fetch_facts (auto-retry)", fetch_cmd, allow_fail=True)
            if fetch_ok:
                results["steps_ok"].append("01_fetch_facts (auto-retry)")
                ok = run_step("02_build_script (retry)", _build_script_cmd())
            if not ok:
                log.error("02_build_script failed after retry — cannot continue")
                sys.exit(1)
        results["steps_ok"].append("02_build_script")

        script_path = find_latest_script(args.type, run_dir=run_dir)
        if not script_path:
            log.error("Could not find generated script JSON")
            sys.exit(1)

    results["script"] = script_path
    log.info("Script: %s", script_path)

    # ── Step 3: TTS ───────────────────────────────────────────────────────────
    cmd = [PYTHON, os.path.join(PIPELINE_DIR, "03_tts.py"),
           "--script", script_path, "--run-dir", run_dir]
    ok = run_step("03_tts", cmd)
    if ok:
        results["steps_ok"].append("03_tts")
    else:
        results["steps_failed"].append("03_tts")
        # 2026-10-13: TTS 실패 시 음성 없는 영상은 무의미 → 중단 (04/05 불필요 실행 방지, 원인 로그 명확화)
        # log.warning("03_tts failed — continuing anyway (may affect video quality)")
        log.error("03_tts FAILED — aborting pipeline")
        sys.exit(1)

    # ── Step 4: Fetch visuals ─────────────────────────────────────────────────
    cmd = [PYTHON, os.path.join(PIPELINE_DIR, "04_fetch_visuals.py"),
           "--script", script_path, "--run-dir", run_dir]
    ok = run_step("04_fetch_visuals", cmd, allow_fail=False)
    if ok:
        results["steps_ok"].append("04_fetch_visuals")
    else:
        results["steps_failed"].append("04_fetch_visuals")
        log.error("04_fetch_visuals FAILED — aborting pipeline")
        sys.exit(1)

    # ── Step 5: Render video ──────────────────────────────────────────────────
    cmd = [PYTHON, os.path.join(PIPELINE_DIR, "05_render_video.py"),
           "--script", script_path, "--run-dir", run_dir]
    if args.test:
        cmd.append("--test")
    ok = run_step("05_render_video", cmd, allow_fail=False)
    if ok:
        results["steps_ok"].append("05_render_video")
        results["video"] = find_latest_video(args.type, run_dir=run_dir)
    else:
        results["steps_failed"].append("05_render_video")
        log.error("05_render_video FAILED — aborting pipeline")
        sys.exit(1)

    # ── Step 6: Thumbnail ─────────────────────────────────────────────────────
    cmd = [PYTHON, os.path.join(PIPELINE_DIR, "06_thumbnail.py"),
           "--script", script_path, "--run-dir", run_dir]
    ok = run_step("06_thumbnail", cmd, allow_fail=True)
    if ok:
        results["steps_ok"].append("06_thumbnail")
        results["thumbnail"] = find_latest_thumbnail(run_dir=run_dir)
    else:
        results["steps_failed"].append("06_thumbnail")
        log.warning("06_thumbnail failed")

    # ── Step 7: Upload ────────────────────────────────────────────────────────
    if do_upload:
        cmd = [PYTHON, os.path.join(PIPELINE_DIR, "07_upload.py"),
               "--script", script_path, "--run-dir", run_dir]
        if results["video"]:
            cmd += ["--video", results["video"]]
        if results["thumbnail"]:
            cmd += ["--thumbnail", results["thumbnail"]]
        if args.test:
            cmd.append("--test")
        ok = run_step("07_upload", cmd, allow_fail=False)
        if ok:
            results["steps_ok"].append("07_upload")
        else:
            results["steps_failed"].append("07_upload")
            log.error("07_upload FAILED — aborting pipeline")
            sys.exit(1)
    else:
        log.info("Upload skipped (--test or --skip-upload)")
        results["steps_ok"].append("07_upload (skipped)")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = (datetime.now() - start_time).total_seconds()
    log.info("=" * 65)
    log.info("PIPELINE COMPLETE in %.0f seconds", elapsed)
    log.info("=" * 65)

    print(f"\n{'='*65}")
    print(f"  BRAINBODA PIPELINE COMPLETE")
    print(f"  Elapsed: {elapsed:.0f}s")
    print(f"{'='*65}")
    print(f"\n  Steps OK:     {', '.join(results['steps_ok'])}")
    if results["steps_failed"]:
        print(f"  Steps FAILED: {', '.join(results['steps_failed'])}")
    print(f"\n  Script:    {results['script']}")
    print(f"  Video:     {results['video'] or '(not generated)'}")
    print(f"  Thumbnail: {results['thumbnail'] or '(not generated)'}")
    if results["youtube_url"]:
        print(f"  YouTube:   {results['youtube_url']}")
    print(f"{'='*65}\n")

    return results


if __name__ == "__main__":
    main()
