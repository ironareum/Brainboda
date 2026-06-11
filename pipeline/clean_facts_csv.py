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

PSYCHOLOGY_KEYWORDS = [
    "psychology", "psychological", "psycholog",
    "behavior", "behaviour", "cognitive", "cognition",
    "brain", "neuroscience", "neural", "mental",
    "bias", "effect", "heuristic", "emotion",
    "memory", "perception", "personality", "motivation",
    "anxiety", "depression", "stress", "trauma",
    "social", "interpersonal", "self-esteem", "consciousness",
    "decision", "judgment", "attention", "learning",
    "therapy", "therapist", "psychiatry", "psychoanalysis",
]

REJECT_KEYWORDS = [
    "anthropology", "ghost job", "animal studies", "black-american",
    "phantom job", "fake job", "field within", "recently recognised field",
    "university of", "public-private partnership", "partnership",
    "nonprofit", "non-profit", "foundation", "organization",
    "program", "initiative", "hosted at",
]


def is_psychology_relevant(row: dict) -> bool:
    text = (row.get("title", "") + " " + row.get("body", "")).lower()
    if any(kw in text for kw in REJECT_KEYWORDS):
        return False
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
