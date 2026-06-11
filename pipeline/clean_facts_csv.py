"""
Utility: Re-filter facts_raw.csv with the current psychology relevance filter.

Removes entries that don't pass is_psychology_relevant() and writes the result
back to the same file (backup saved as facts_raw.csv.bak).

Usage:
    python pipeline/clean_facts_csv.py [--dry-run]
"""

import argparse
import csv
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# IDs that are clearly not psychology content — block by ID (most reliable)
REJECT_IDS = {
    # Non-psychology fields / organizations / journals
    "4or",
    "19_to_zero",
    "animal_studies",
    "anthropology",
    "black_american_anthropology",
    "association_for_behavior_analysis_international",
    "association_for_contextual_behavioral_science",
    "cog_s_ladder",
    "ghost_job",
    "phantom_job",
    "behavioral_science___policy",
    "black_manosphere",
    "attention_inequality",
    "honey_trapping",
    "amity_enmity_complex",
    "blame",
    "blame_in_organizations",
    "sunk_cost",                        # covered by sunk_cost_fallacy
    "aesthetic_usability_effect",       # UX/design, not psychology
    # Duplicates
    "anchoring__cognitive_bias_",       # duplicate of anchoring_bias
    "anchoring_effect",                 # duplicate of anchoring_bias
    "priming__psychology_",             # duplicate of priming_psychology
    "framing_effect__psychology_",      # duplicate of framing_effect
    "habit",                            # duplicate of habit_psychology
    "reciprocity__social_psychology_",  # duplicate of reciprocity_social_psychology
    "scarcity__social_psychology_",     # duplicate of scarcity_psychology
    # Too broad / not a fact
    "list_of_cognitive_biases",         # list page, not a single fact
    "social_psychology",                # field name, too broad
    # Non-psychology topics
    "behavior_imaging",                 # autism diagnostic technique
    "behavior_informatics",             # engineering/informatics field
    "behavioral_urbanism",              # urban design / architecture
    "barriers_to_pro_environmental_behaviour",  # environmental behavior
    "intimidation",                     # primarily a legal term
}

PSYCHOLOGY_KEYWORDS = [
    "psychology", "psychological", "psycholog",
    "behavior", "behaviour", "cognitive", "cognition",
    "brain", "neuroscience", "neural", "mental health",
    "bias", "heuristic", "emotion",
    "memory", "perception", "personality", "motivation",
    "anxiety", "depression", "stress", "trauma",
    "self-esteem", "consciousness",
    "therapy", "therapist", "psychiatry", "psychoanalysis",
    "mindset", "prophecy", "attitude",
    "tendency",
    "belief",
]

REJECT_BODY_PHRASES = [
    "recently recognised field",
    "field within anthropology",
    "operations research",
    "hosted at the university of calgary",
    "nonprofit professional membership organization",
    "nonprofit organization dedicated to promoting",
]


def is_psychology_relevant(row: dict) -> bool:
    row_id = row.get("id", "").lower()
    title = row.get("title", "").lower()
    body = row.get("body", "").lower()

    # Block known non-psychology IDs
    if row_id in REJECT_IDS:
        return False

    # Block by body phrases that indicate non-psychology content
    if any(phrase in body for phrase in REJECT_BODY_PHRASES):
        return False

    # Must contain at least one psychology keyword
    text = title + " " + body
    return any(kw in text for kw in PSYCHOLOGY_KEYWORDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't write")
    parser.add_argument("--csv", type=str, default=None, help="Path to CSV (default: data/facts_raw.csv)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = args.csv or os.path.join(base_dir, "data", "facts_raw.csv")

    if not os.path.exists(csv_path):
        print(f"CSV not found: {csv_path}")
        sys.exit(1)

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    kept, rejected = [], []
    for row in rows:
        if is_psychology_relevant(row):
            kept.append(row)
        else:
            rejected.append(row)

    print(f"\nTotal rows  : {len(rows)}")
    print(f"Keep        : {len(kept)}")
    print(f"Reject      : {len(rejected)}")

    if rejected:
        print("\n── Rejected ─────────────────────────────────────────")
        for r in rejected:
            print(f"  REMOVE  {r['id']:<40} {r['title']}")

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return

    if not rejected:
        print("\nAll rows already pass the filter — nothing to clean.")
        return

    confirm = input(f"\nRemove {len(rejected)} rows from {csv_path}? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    bak_path = csv_path + ".bak"
    shutil.copy2(csv_path, bak_path)
    print(f"Backup saved: {bak_path}")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    print(f"Done — {len(kept)} rows kept, {len(rejected)} removed.")


if __name__ == "__main__":
    main()
