"""
Step 2: Build video script from facts.

Reads facts_raw.csv, selects N facts not in used_facts.json,
and generates a structured script JSON file in output/.

Usage:
    python pipeline/02_build_script.py
    python pipeline/02_build_script.py --type short
    python pipeline/02_build_script.py --topic manipulation
    python pipeline/02_build_script.py --dry-run   # preview only, no files written
"""

import argparse
import csv
import json
import logging
import os
import random
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.channel import (
    FACTS_APPROVED_CSV,
    FACTS_RAW_CSV,
    FACTS_PER_SHORT,
    FACTS_PER_VIDEO,
    LOGS_DIR,
    OUTPUT_DIR,
    USED_FACTS_JSON,
)

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"02_build_script_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── title templates ───────────────────────────────────────────────────────────

MAIN_TITLE_TEMPLATES = [
    "{n} Psychological Facts That Will Change How You See People",
    "{n} Psychology Tricks Your Brain Plays On You Every Day",
    "{n} Mind-Blowing Facts About Human Behavior (Backed by Science)",
    "{n} Psychological Facts Most People Don't Know About Themselves",
    "{n} Disturbing Psychology Facts That Explain Human Behavior",
    "{n} Dark Psychology Facts That Will Make You Think Twice",
    "{n} Incredible Psychology Facts About the Human Mind",
    "{n} Psychological Secrets Rich and Successful People Know",
    "{n} Shocking Psychology Facts Science Has Proven",
    "{n} Hidden Psychology Facts That Explain Why You Do What You Do",
]

SHORT_TITLE_TEMPLATES = [
    "This Psychology Fact Will Shock You 🧠 #psychology #mindset",
    "Your Brain Is Lying To You Right Now #cognitivebias #psychology",
    "The {fact_title} Explained In 60 Seconds #psychology #facts",
    "Science Proved This About Your Brain #neuroscience #psychology",
    "Why Your Brain Sabotages You (Psychology Explained) #mindset",
]

HOOK_TEMPLATES = [
    "Did you know that {hook_fact}? Stay until the end — because fact #{hook_n} will completely change how you see people.",
    "Scientists have discovered something shocking about the human mind. {hook_fact} And that's just the beginning.",
    "Your brain is lying to you right now. {hook_fact} In this video, we reveal {n} psychology facts that will change everything.",
    "What if everything you believed about yourself was shaped by hidden mental forces? {hook_fact} Let's dive in.",
    "The human brain is the most complex object in the known universe — and it's full of secrets. {hook_fact} Here are {n} facts you need to know.",
]

OUTRO_TEMPLATES = [
    "Which fact surprised you the most? Let me know in the comments below. And if you found this fascinating, subscribe — we post new psychology facts every week.",
    "So which of these {n} facts hit the hardest? Drop it in the comments. Subscribe to Brainboda for more mind-expanding psychology content every week.",
    "Now you know {n} psychology secrets that most people never discover. Share this with someone who needs to hear it — and subscribe for more every week.",
    "The human mind is endlessly fascinating. Which fact are you going to think about today? Comment below, and hit subscribe so you never miss an episode.",
]

TRANSITION_PHRASES = [
    "This means that",
    "In practice, this means",
    "What this tells us is",
    "For you, this means",
    "In real life, this translates to",
    "The practical takeaway here is",
    "What's remarkable about this is",
]

# ── helpers ───────────────────────────────────────────────────────────────────

def load_used_ids() -> set[str]:
    if not os.path.exists(USED_FACTS_JSON):
        return set()
    try:
        with open(USED_FACTS_JSON) as f:
            data = json.load(f)
        return set(data.get("used_ids", []))
    except Exception:
        return set()


def save_used_ids(ids: set[str]) -> None:
    existing = load_used_ids()
    merged = existing | ids
    with open(USED_FACTS_JSON, "w") as f:
        json.dump({"used_ids": sorted(merged)}, f, indent=2)


REJECT_KEYWORDS = [
    "anthropology", "ghost job", "animal studies", "black-american",
    "phantom job", "fake job", "field within", "recently recognised field"
]

def is_psychology_relevant(fact: dict) -> bool:
    text = (fact.get("title", "") + " " + fact.get("body", "")).lower()
    return not any(kw in text for kw in REJECT_KEYWORDS)


def load_available_facts(topic: str | None = None) -> list[dict]:
    """Load facts from approved CSV (preferred) or raw CSV, filtered by used IDs."""
    used_ids = load_used_ids()

    # Prefer approved facts if file exists and has data
    source = FACTS_RAW_CSV
    if os.path.exists(FACTS_APPROVED_CSV) and os.path.getsize(FACTS_APPROVED_CSV) > 10:
        source = FACTS_APPROVED_CSV
        log.info("Using approved facts: %s", source)
    else:
        log.info("Using raw facts: %s", source)

    facts: list[dict] = []
    try:
        with open(source, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["id"] in used_ids:
                    continue
                if topic and topic.lower() not in (row["title"] + row["body"]).lower():
                    continue
                if not is_psychology_relevant(row):
                    log.debug("Quality filter rejected: %s", row.get("title", ""))
                    continue
                facts.append(row)
    except FileNotFoundError:
        log.error("Facts CSV not found: %s — run 01_fetch_facts.py first", source)

    log.info("Available (unused) facts: %d", len(facts))
    return facts


def pick_facts(facts: list[dict], n: int, topic: str | None) -> list[dict]:
    """Pick N facts, shuffled. If topic-filtered pool is too small, fill from all."""
    if len(facts) < n:
        log.warning("Only %d facts available, need %d", len(facts), n)
        n = len(facts)
    shuffled = facts.copy()
    random.shuffle(shuffled)
    return shuffled[:n]


def derive_application(body: str) -> str:
    """Extract or synthesize a 'real-life application' closing sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", body.strip())
    # Look for a sentence that already contains application language
    app_keywords = ["means", "explains", "shows", "tells", "proves", "suggests", "practical"]
    for s in reversed(sentences):
        if any(kw in s.lower() for kw in app_keywords) and len(s) > 40:
            return s
    # Fallback: rephrase the last sentence
    last = sentences[-1] if sentences else body
    transition = random.choice(TRANSITION_PHRASES)
    # Strip leading connector if already present
    last_clean = re.sub(r"^(This means|This shows|This tells us)[^,]*,?\s*", "", last, flags=re.IGNORECASE)
    return f"{transition} {last_clean[0].lower()}{last_clean[1:]}"


def build_narration(fact: dict, n: int) -> str:
    """Build the full spoken narration for one fact."""
    heading = fact["title"]
    body = fact["body"].strip()

    # Remove trailing application sentence from body if we'll derive one separately
    sentences = re.split(r"(?<=[.!?])\s+", body)
    core = " ".join(sentences[:-1]) if len(sentences) > 1 else body
    application = derive_application(body)

    narration = f"Fact {n}: {heading}. {core} {application}"
    return narration.strip()


def estimate_duration(text: str, wpm: int = 150) -> int:
    """Estimate spoken duration in seconds at given words-per-minute."""
    words = len(text.split())
    return max(20, round(words / wpm * 60))


def build_hook(facts: list[dict], n_total: int) -> str:
    """Pick the most striking fact for the hook teaser."""
    # Use fact at index 2 (fact #3) for the hook reference as per spec
    hook_fact_idx = min(2, len(facts) - 1)
    hook_fact = facts[hook_fact_idx]

    # Extract a punchy first sentence from the hook fact
    first_sentence = re.split(r"(?<=[.!?])\s+", hook_fact["body"])[0]

    template = random.choice(HOOK_TEMPLATES)
    hook = template.format(
        hook_fact=first_sentence,
        hook_n=hook_fact_idx + 1,
        n=n_total,
    )
    return hook


def build_script(
    facts: list[dict],
    video_type: str = "main",
) -> dict:
    """Assemble the full script dictionary."""
    n = len(facts)

    # Title
    if video_type == "short":
        title_tpl = random.choice(SHORT_TITLE_TEMPLATES)
        title = title_tpl.format(fact_title=facts[0]["title"], n=n)
    else:
        title_tpl = random.choice(MAIN_TITLE_TEMPLATES)
        title = title_tpl.format(n=n)

    # Hook
    hook = build_hook(facts, n)

    # Fact narrations
    fact_blocks = []
    for i, fact in enumerate(facts, 1):
        narration = build_narration(fact, i)
        fact_blocks.append({
            "n": i,
            "id": fact["id"],
            "heading": fact["title"],
            "source_url": fact.get("source_url", ""),
            "narration": narration,
            "key_insight": build_key_insight(fact["title"], fact["body"]),
            "duration_est": estimate_duration(narration),
            "search_keywords": _visual_keywords(fact),
        })

    # Outro
    outro_tpl = random.choice(OUTRO_TEMPLATES)
    outro = outro_tpl.format(n=n)

    # Total duration estimate
    hook_dur = estimate_duration(hook)
    outro_dur = estimate_duration(outro)
    total_dur = hook_dur + sum(b["duration_est"] for b in fact_blocks) + outro_dur

    # Description
    description = _build_description(title, fact_blocks)

    # Tags
    tags = _build_tags(facts)

    thumbnail_hook = _build_thumbnail_hook(title, hook, facts)

    return {
        "type": video_type,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "title": title,
        "thumbnail_hook": thumbnail_hook,
        "hook": hook,
        "hook_duration_est": hook_dur,
        "facts": fact_blocks,
        "outro": outro,
        "outro_duration_est": outro_dur,
        "total_duration_est": total_dur,
        "description": description,
        "tags": tags,
    }


def build_key_insight(title: str, body: str) -> str:
    """Generate a 5-8 word punchy key insight for on-screen display."""
    import re as _re

    # Prefer sentences with numbers/percentages — most impactful
    sentences = _re.split(r'(?<=[.!?])\s+', body.strip())
    number_pattern = _re.compile(r'\b\d+[\d.,]*\s*(%|x|times|percent|fold|people|out of|seconds?|minutes?|hours?|days?|years?)\b', _re.IGNORECASE)

    best = None
    for s in sentences:
        if number_pattern.search(s) and 30 <= len(s) <= 200:
            best = s
            break

    if not best:
        # Fall back to the second sentence (usually the core claim)
        for s in sentences[1:]:
            if len(s) > 30:
                best = s
                break
    if not best:
        best = sentences[0] if sentences else title

    # Extract a short clause: split on comma/dash/colon and pick the punchiest part
    parts = _re.split(r'[,;—–]', best)
    parts = [p.strip() for p in parts if len(p.strip()) > 15]

    # Score parts: prefer ones with numbers or strong psychology words
    power_words = ["effect", "bias", "paradox", "fact", "people", "times", "more", "less", "never", "always", "actually", "proven", "shows", "found"]
    def score(p):
        p_low = p.lower()
        return sum(1 for w in power_words if w in p_low) + (3 if number_pattern.search(p) else 0)

    parts_sorted = sorted(parts, key=score, reverse=True)
    chosen = parts_sorted[0] if parts_sorted else best

    # Trim to 5-8 words
    words = chosen.split()
    if len(words) > 8:
        # Try to find a natural cut point within 5-8 words
        short = " ".join(words[:7])
        # Remove trailing preposition/conjunction
        short = _re.sub(r'\s+(a|an|the|and|or|but|in|on|of|to|is|are|was|were|that|which)\s*$', '', short, flags=_re.IGNORECASE)
        chosen = short.strip()
    elif len(words) < 4:
        # Pad with title if too short
        chosen = title

    # Capitalize first letter
    if chosen:
        chosen = chosen[0].upper() + chosen[1:]

    return chosen


def _build_thumbnail_hook(title: str, hook: str, facts: list) -> str:
    """Generate a short 5-7 word punchy hook line for the thumbnail."""
    import re as _re

    # Patterns: "Your Brain...", "You Actually...", "Science Proved...", "Most People..."
    STARTERS = [
        "Your Brain Does This Daily",
        "You Do This Without Knowing",
        "Science Proved This About You",
        "Most People Never Know This",
        "Your Mind Lies To You Daily",
    ]

    # Extract a strong keyword from the title
    stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "of", "to",
                  "that", "this", "is", "are", "was", "were", "be", "been",
                  "facts", "fact", "psychological", "psychology", "hidden", "dark",
                  "incredible", "shocking", "mind-blowing", "disturbing"}
    title_words = [w.strip(".,!?\"'") for w in title.split() if w.lower().strip(".,!?\"'") not in stop_words and len(w) > 3]

    # Try to build a hook around the best topic word
    power_phrases = [
        ("bias", "Your Brain Has a Hidden Bias"),
        ("manipul", "People Are Being Manipulated"),
        ("fear", "Fear Controls Your Decisions"),
        ("memory", "Your Memories Are Fabricated"),
        ("success", "Success Rewires Your Brain"),
        ("decision", "You Make Decisions Unconsciously"),
        ("social", "Social Pressure Shapes Your Mind"),
        ("emotion", "Emotions Override Your Logic"),
        ("habit", "Habits Control Your Every Move"),
        ("trust", "Your Brain Decides Who To Trust"),
        ("stress", "Stress Changes Your Brain Daily"),
        ("sleep", "Sleep Deprivation Warps Reality"),
        ("conform", "You Conform Without Realizing It"),
        ("reward", "Your Brain Craves Instant Rewards"),
        ("dark", "The Dark Side of Human Psychology"),
        ("lie", "Your Brain Lies To You Constantly"),
    ]

    title_lower = title.lower()
    hook_lower = hook.lower()
    combined = title_lower + " " + hook_lower

    for keyword, phrase in power_phrases:
        if keyword in combined:
            return phrase

    # Fallback: use first fact title to build a hook
    if facts:
        fact_title = facts[0].get("title", "")
        words = [w for w in fact_title.split() if len(w) > 3][:3]
        if words:
            return f"The Hidden Truth About {' '.join(words[:2])}"

    # Last resort: use a random starter
    import random
    return random.choice(STARTERS)


def _visual_keywords(fact: dict) -> list[str]:
    """Keywords for image search (Pixabay/Pexels) for this fact."""
    base = ["brain", "psychology", "mind", "human behavior"]
    title_words = [w.lower() for w in fact["title"].split() if len(w) > 4]
    return (title_words + base)[:5]


def _build_description(title: str, facts: list[dict]) -> str:
    lines = [
        title,
        "",
        "In this video, we explore fascinating psychology facts backed by science that reveal how the human mind really works.",
        "",
        "What you'll learn:",
    ]
    for b in facts:
        lines.append(f"  ✦ {b['heading']}")
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🧠 Subscribe to Brainboda for weekly psychology insights.",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "#psychology #humanbehavior #mindset #cognitivebias #brainboda #selfimprovement #mentalhealth #neuroscience",
    ]
    return "\n".join(lines)


def _build_tags(facts: list[dict]) -> list[str]:
    base = [
        "psychology", "human behavior", "mind", "brain", "cognitive bias",
        "self improvement", "neuroscience", "mindset", "mental health",
        "psychology facts", "brainboda",
    ]
    fact_tags = [f["title"].lower() for f in facts]
    all_tags = fact_tags + base
    seen: set[str] = set()
    return [t for t in all_tags if not (t in seen or seen.add(t))][:30]  # type: ignore[func-returns-value]


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build video script from psychology facts")
    parser.add_argument("--type", choices=["main", "short"], default="main")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Preview only, write no files")
    parser.add_argument("--run-dir", type=str, default=None,
                        help="Run output directory. If provided, save script as {run-dir}/script.json")
    args = parser.parse_args()

    log.info("=== 02_build_script.py START ===")
    log.info("Type: %s | Topic: %s | Dry-run: %s", args.type, args.topic or "any", args.dry_run)

    n_needed = FACTS_PER_SHORT if args.type == "short" else FACTS_PER_VIDEO

    available = load_available_facts(topic=args.topic)
    if not available:
        log.error("No available facts. Run 01_fetch_facts.py first.")
        sys.exit(1)

    selected = pick_facts(available, n_needed, args.topic)
    if not selected:
        log.error("Could not select enough facts.")
        sys.exit(1)

    log.info("Selected %d facts for %s video", len(selected), args.type)

    script = build_script(selected, video_type=args.type)

    # ── output ────────────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.run_dir:
        os.makedirs(args.run_dir, exist_ok=True)
        script_path = os.path.join(args.run_dir, "script.json")
    else:
        script_path = os.path.join(OUTPUT_DIR, f"script_{args.type}_{timestamp}.json")

    if not args.dry_run:
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, indent=2, ensure_ascii=False)
        log.info("Script saved → %s", script_path)

        # Mark facts as used
        used_ids = {f["id"] for f in selected}
        save_used_ids(used_ids)
        log.info("Marked %d fact IDs as used in %s", len(used_ids), USED_FACTS_JSON)
    else:
        log.info("[DRY RUN] Script NOT saved. No IDs marked as used.")
        script_path = "(dry-run, not saved)"

    log.info("=== 02_build_script.py DONE ===")

    # ── preview ───────────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  VIDEO TYPE : {script['type'].upper()}")
    print(f"  TITLE      : {script['title']}")
    print(f"  DURATION   : ~{script['total_duration_est']}s ({script['total_duration_est']//60}m{script['total_duration_est']%60}s)")
    print(f"  FACTS      : {len(script['facts'])}")
    print(f"  OUTPUT     : {script_path}")
    print(f"{'='*65}")
    print(f"\n[HOOK]\n  {script['hook']}\n")
    for b in script["facts"]:
        print(f"[FACT {b['n']}] {b['heading']} (~{b['duration_est']}s)")
        print(f"  {b['narration'][:120]}...")
        print()
    print(f"[OUTRO]\n  {script['outro']}\n")
    print(f"[TAGS] {', '.join(script['tags'][:8])} ...")

    return script_path


if __name__ == "__main__":
    main()
