"""
Step 1: Fetch psychology facts from Wikipedia English API.

Saves results to data/facts_raw.csv.
Skips pages already in used_facts.json to avoid duplicates.

Usage:
    python pipeline/01_fetch_facts.py
    python pipeline/01_fetch_facts.py --topic manipulation
    python pipeline/01_fetch_facts.py --limit 50
    python pipeline/01_fetch_facts.py --offline   # use built-in seed facts only
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.channel import (
    DATA_DIR,
    FACTS_RAW_CSV,
    LOGS_DIR,
    USED_FACTS_JSON,
    WIKIPEDIA_CATEGORIES,
    WIKIPEDIA_SEED_PAGES,
)

# ── logging ───────────────────────────────────────────────────────────────────

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

log_file = os.path.join(LOGS_DIR, f"01_fetch_facts_{datetime.now():%Y%m%d_%H%M%S}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ── quality filter ───────────────────────────────────────────────────────────

REJECT_KEYWORDS = [
    "anthropology", "ghost job", "animal studies", "black-american",
    "phantom job", "fake job", "field within", "recently recognised field"
]

def is_psychology_relevant(fact: dict) -> bool:
    text = (fact.get("title", "") + " " + fact.get("body", "")).lower()
    return not any(kw in text for kw in REJECT_KEYWORDS)


# ── built-in seed facts (fallback when Wikipedia is unreachable) ──────────────

SEED_FACTS = [
    {
        "id": "cognitive_bias",
        "title": "Cognitive Bias",
        "body": "A cognitive bias is a systematic pattern of deviation from rationality in judgment. People create their own subjective reality from their perception of the input, which can dictate their behavior in the world. The most common cognitive bias is confirmation bias — the tendency to search for information that confirms one's preexisting beliefs.",
        "source_page": "Cognitive bias",
        "source_url": "https://en.wikipedia.org/wiki/Cognitive_bias",
        "category": "psychology",
    },
    {
        "id": "dunning_kruger_effect",
        "title": "Dunning–Kruger Effect",
        "body": "The Dunning–Kruger effect is a cognitive bias in which people with limited competence in a particular domain overestimate their abilities. People with low ability at a task overestimate their own ability, whereas people with high ability at a task underestimate their own ability. This means that incompetence prevents self-recognition of incompetence.",
        "source_page": "Dunning–Kruger effect",
        "source_url": "https://en.wikipedia.org/wiki/Dunning%E2%80%93Kruger_effect",
        "category": "psychology",
    },
    {
        "id": "bystander_effect",
        "title": "Bystander Effect",
        "body": "The bystander effect is a social psychological theory that states that individuals are less likely to offer help in an emergency situation when other people are present. The greater the number of bystanders, the less likely it is that any one of them will help. Responsibility diffuses through the crowd — everyone assumes someone else will act.",
        "source_page": "Bystander effect",
        "source_url": "https://en.wikipedia.org/wiki/Bystander_effect",
        "category": "psychology",
    },
    {
        "id": "halo_effect",
        "title": "Halo Effect",
        "body": "The halo effect is a cognitive bias in which an observer's overall impression of a person influences the observer's feelings and thoughts about that person's character or properties. If you find someone physically attractive, you are more likely to also assume they are intelligent, kind, and competent — even with no evidence.",
        "source_page": "Halo effect",
        "source_url": "https://en.wikipedia.org/wiki/Halo_effect",
        "category": "psychology",
    },
    {
        "id": "confirmation_bias",
        "title": "Confirmation Bias",
        "body": "Confirmation bias is the tendency to search for, interpret, favor, and recall information in a way that confirms or supports one's prior beliefs or values. People display this bias most strongly for emotionally significant issues and for established beliefs. This means that once we believe something, we unconsciously filter reality to support it.",
        "source_page": "Confirmation bias",
        "source_url": "https://en.wikipedia.org/wiki/Confirmation_bias",
        "category": "psychology",
    },
    {
        "id": "cognitive_dissonance",
        "title": "Cognitive Dissonance",
        "body": "Cognitive dissonance is the mental discomfort experienced by a person who holds two or more contradictory beliefs, values, or ideas simultaneously. People tend to seek consistency among their cognitions and will change their attitudes or behaviors to reduce the discomfort. This is why people rationalize bad decisions rather than admit they were wrong.",
        "source_page": "Cognitive dissonance",
        "source_url": "https://en.wikipedia.org/wiki/Cognitive_dissonance",
        "category": "psychology",
    },
    {
        "id": "placebo_effect",
        "title": "Placebo Effect",
        "body": "The placebo effect is a beneficial effect produced by a treatment that cannot be attributed to the properties of the placebo itself but must be due to the patient's belief in that treatment. Studies show that even when patients know they are taking a placebo, they still experience real physical improvements. This proves the extraordinary power of belief over biology.",
        "source_page": "Placebo effect",
        "source_url": "https://en.wikipedia.org/wiki/Placebo",
        "category": "psychology",
    },
    {
        "id": "loss_aversion",
        "title": "Loss Aversion",
        "body": "Loss aversion is the psychological principle that people prefer to avoid losses over acquiring equivalent gains. Research by Kahneman and Tversky found that losses are psychologically twice as powerful as gains. This means losing $100 feels roughly as bad as gaining $200 feels good — which is why fear of failure keeps people from taking smart risks.",
        "source_page": "Loss aversion",
        "source_url": "https://en.wikipedia.org/wiki/Loss_aversion",
        "category": "psychology",
    },
    {
        "id": "anchoring_bias",
        "title": "Anchoring Bias",
        "body": "Anchoring is a cognitive bias where people rely too heavily on the first piece of information they receive. Once an anchor is set, all subsequent judgments are made in relation to it. For example, if you see a jacket 'marked down' from $500 to $250, you feel it's a deal — even if $250 is still too expensive for that jacket.",
        "source_page": "Anchoring (cognitive bias)",
        "source_url": "https://en.wikipedia.org/wiki/Anchoring_(cognitive_bias)",
        "category": "psychology",
    },
    {
        "id": "self_fulfilling_prophecy",
        "title": "Self-Fulfilling Prophecy",
        "body": "A self-fulfilling prophecy is a prediction that directly or indirectly causes itself to become true. If you believe you will fail a test, you may study less, leading to actual failure. Robert Merton, who coined the term, showed that expectations shape reality — which means the stories we tell ourselves about ourselves become our destiny.",
        "source_page": "Self-fulfilling prophecy",
        "source_url": "https://en.wikipedia.org/wiki/Self-fulfilling_prophecy",
        "category": "psychology",
    },
    {
        "id": "social_proof",
        "title": "Social Proof",
        "body": "Social proof is a psychological phenomenon where people assume the actions of others in an attempt to reflect correct behavior in a given situation. If a restaurant is empty, we assume it's bad; if it's packed, we assume it's good. This is why reviews, testimonials, and follower counts are so persuasive — we look to others to tell us what to value.",
        "source_page": "Social proof",
        "source_url": "https://en.wikipedia.org/wiki/Social_proof",
        "category": "psychology",
    },
    {
        "id": "priming_psychology",
        "title": "Priming (Psychology)",
        "body": "Priming is an implicit memory effect in which exposure to a stimulus influences a response to a later stimulus. For example, if you hear the word 'yellow,' you will recognize the word 'banana' faster than 'doctor' because yellow and banana are closely associated. Advertisers and politicians use priming constantly to influence how you feel about their message.",
        "source_page": "Priming (psychology)",
        "source_url": "https://en.wikipedia.org/wiki/Priming_(psychology)",
        "category": "psychology",
    },
    {
        "id": "impostor_syndrome",
        "title": "Impostor Syndrome",
        "body": "Impostor syndrome is a psychological pattern in which an individual doubts their skills, talents, or accomplishments and has a persistent internalized fear of being exposed as a fraud. Despite external evidence of their competence, those experiencing this phenomenon remain convinced that they do not deserve their success. Studies suggest up to 70% of people experience this at some point in their lives.",
        "source_page": "Impostor syndrome",
        "source_url": "https://en.wikipedia.org/wiki/Impostor_syndrome",
        "category": "psychology",
    },
    {
        "id": "fundamental_attribution_error",
        "title": "Fundamental Attribution Error",
        "body": "The fundamental attribution error is the tendency for people to over-emphasize dispositional explanations for behaviors observed in others while under-emphasizing situational explanations. When someone cuts you off in traffic, you think they're a bad person — not that they're rushing to the hospital. Yet when we make the same mistake, we blame circumstances.",
        "source_page": "Fundamental attribution error",
        "source_url": "https://en.wikipedia.org/wiki/Fundamental_attribution_error",
        "category": "psychology",
    },
    {
        "id": "availability_heuristic",
        "title": "Availability Heuristic",
        "body": "The availability heuristic is a mental shortcut that relies on immediate examples that come to a given person's mind when evaluating a specific topic, concept, method, or decision. After seeing news stories about plane crashes, people overestimate the danger of flying — even though driving is statistically far more deadly. Vivid memories distort our sense of probability.",
        "source_page": "Availability heuristic",
        "source_url": "https://en.wikipedia.org/wiki/Availability_heuristic",
        "category": "psychology",
    },
    {
        "id": "hawthorne_effect",
        "title": "Hawthorne Effect",
        "body": "The Hawthorne effect is a type of reactivity in which individuals modify an aspect of their behavior in response to their awareness of being observed. Workers at a factory increased their productivity simply because they knew researchers were watching — not because of any actual change in working conditions. People perform differently when they know they are being evaluated.",
        "source_page": "Hawthorne effect",
        "source_url": "https://en.wikipedia.org/wiki/Hawthorne_effect",
        "category": "psychology",
    },
    {
        "id": "psychological_manipulation",
        "title": "Psychological Manipulation",
        "body": "Psychological manipulation involves influencing a person using deceptive or underhanded tactics that benefit the manipulator at the expense of the victim. Common techniques include gaslighting, love bombing, guilt-tripping, and silent treatment. Understanding these tactics is the first step to protecting yourself from toxic relationships and environments.",
        "source_page": "Psychological manipulation",
        "source_url": "https://en.wikipedia.org/wiki/Psychological_manipulation",
        "category": "psychology",
    },
    {
        "id": "reciprocity_social_psychology",
        "title": "Reciprocity (Social Psychology)",
        "body": "Reciprocity in social psychology is the concept that in response to friendly actions, people are frequently much nicer and more cooperative than predicted by the model of self-interest. When someone gives you a gift — even an unwanted one — you feel an obligation to give something back. Salespeople exploit this constantly by offering free samples.",
        "source_page": "Reciprocity (social psychology)",
        "source_url": "https://en.wikipedia.org/wiki/Reciprocity_(social_psychology)",
        "category": "psychology",
    },
    {
        "id": "sunk_cost_fallacy",
        "title": "Sunk Cost Fallacy",
        "body": "The sunk cost fallacy is the tendency to continue an endeavor because of previously invested resources — time, money, or effort — even when it no longer makes rational sense to do so. We stay in bad movies, bad relationships, and bad jobs because we've already 'invested' so much. A rational decision should be based only on future costs and benefits.",
        "source_page": "Sunk cost",
        "source_url": "https://en.wikipedia.org/wiki/Sunk_cost",
        "category": "psychology",
    },
    {
        "id": "framing_effect",
        "title": "Framing Effect",
        "body": "The framing effect is a cognitive bias where people decide on options based on whether the options are presented with positive or negative connotations. A medical treatment described as having a '90% survival rate' is judged far more favorably than one described as having a '10% mortality rate' — even though they are statistically identical. The way information is packaged changes our choices.",
        "source_page": "Framing effect (psychology)",
        "source_url": "https://en.wikipedia.org/wiki/Framing_effect_(psychology)",
        "category": "psychology",
    },
    {
        "id": "peak_end_rule",
        "title": "Peak–End Rule",
        "body": "The peak–end rule is a psychological heuristic in which people judge an experience based on how they felt at its most intense point and at its end, rather than based on the sum or average of every moment. A painful medical procedure followed by a brief period of mild discomfort is remembered as less terrible than a shorter procedure that ends at peak pain.",
        "source_page": "Peak–end rule",
        "source_url": "https://en.wikipedia.org/wiki/Peak%E2%80%93end_rule",
        "category": "psychology",
    },
    {
        "id": "habit_psychology",
        "title": "Habit Formation",
        "body": "A habit is a routine of behavior that is repeated regularly and tends to occur subconsciously. Neuroscience research shows that habits are stored in the basal ganglia, freeing up the prefrontal cortex for new decisions. The habit loop — cue, routine, reward — means that changing behavior requires identifying and replacing routines while keeping the same cue and reward.",
        "source_page": "Habit",
        "source_url": "https://en.wikipedia.org/wiki/Habit",
        "category": "psychology",
    },
    {
        "id": "growth_mindset",
        "title": "Growth Mindset",
        "body": "A growth mindset, coined by Carol Dweck, is the belief that one's abilities and intelligence can be developed through dedication and hard work. People with a growth mindset embrace challenges, persist through obstacles, and see effort as a path to mastery. Research shows students taught growth mindset principles achieve significantly higher academic outcomes.",
        "source_page": "Mindset",
        "source_url": "https://en.wikipedia.org/wiki/Mindset#Fixed_and_growth",
        "category": "psychology",
    },
    {
        "id": "emotional_intelligence",
        "title": "Emotional Intelligence",
        "body": "Emotional intelligence is the ability to perceive, use, understand, manage, and handle emotions. People with high emotional intelligence recognize their own emotions and those of others, distinguish between different feelings, and use emotional information to guide thinking and behavior. Studies consistently show EQ predicts professional success better than IQ in most careers.",
        "source_page": "Emotional intelligence",
        "source_url": "https://en.wikipedia.org/wiki/Emotional_intelligence",
        "category": "psychology",
    },
    {
        "id": "body_language",
        "title": "Body Language",
        "body": "Body language is a type of nonverbal communication in which physical behaviors, as opposed to words, are used to express or convey information. Albert Mehrabian's research suggested that communication is 7% verbal, 38% vocal tone, and 55% body language. Confident postures — taking up space, maintaining eye contact, and standing tall — are read by others as signals of authority and trustworthiness.",
        "source_page": "Body language",
        "source_url": "https://en.wikipedia.org/wiki/Body_language",
        "category": "psychology",
    },
    {
        "id": "scarcity_psychology",
        "title": "Scarcity (Psychology)",
        "body": "Scarcity is a principle of influence where people assign more value to opportunities when they are less available. 'Only 3 left in stock' triggers a sense of urgency that bypasses rational thinking. Robert Cialdini identified scarcity as one of the six universal principles of persuasion — and it explains why limited-edition products and countdown timers are so effective at driving purchases.",
        "source_page": "Scarcity (social psychology)",
        "source_url": "https://en.wikipedia.org/wiki/Scarcity_(social_psychology)",
        "category": "psychology",
    },
    {
        "id": "social_influence",
        "title": "Social Influence",
        "body": "Social influence occurs when one's emotions, opinions, or behaviors are affected by others. It takes many forms and can be seen in conformity, socialization, peer pressure, obedience, leadership, persuasion, sales, and marketing. Solomon Asch's conformity experiments showed that people will deny the evidence of their own eyes to agree with a group — the desire to belong is that powerful.",
        "source_page": "Social influence",
        "source_url": "https://en.wikipedia.org/wiki/Social_influence",
        "category": "psychology",
    },
    {
        "id": "commitment_consistency",
        "title": "Commitment and Consistency",
        "body": "The principle of commitment and consistency states that once we make a commitment — especially a public one — we feel psychological pressure to behave consistently with that commitment. This is why car salespeople first get you to agree to small requests before asking for the big sale. Once you say 'yes' once, your brain pushes you to keep saying yes.",
        "source_page": "Foot-in-the-door technique",
        "source_url": "https://en.wikipedia.org/wiki/Foot-in-the-door_technique",
        "category": "psychology",
    },
    {
        "id": "liking_social_psychology",
        "title": "Liking (Social Psychology)",
        "body": "The principle of liking states that people are more easily persuaded by people they like. We like people who are similar to us, who compliment us, and who we associate with good things. This explains why celebrities endorse products — we like them, so we trust their recommendations. Sales training consistently teaches rapport-building because liking drives buying decisions.",
        "source_page": "Liking",
        "source_url": "https://en.wikipedia.org/wiki/Liking",
        "category": "psychology",
    },
    {
        "id": "overthinking",
        "title": "Overthinking and Rumination",
        "body": "Overthinking, or rumination, is the habit of thinking about something too much or for too long, often dwelling on problems or negative experiences. Research shows that chronic overthinking is linked to depression and anxiety. Paradoxically, our brain tries to 'solve' emotional problems by thinking, but emotional pain is processed through action, connection, and acceptance — not analysis.",
        "source_page": "Rumination (psychology)",
        "source_url": "https://en.wikipedia.org/wiki/Rumination_(psychology)",
        "category": "psychology",
    },
    {
        "id": "neuroplasticity",
        "title": "Neuroplasticity",
        "body": "Neuroplasticity is the ability of the nervous system to change its activity in response to intrinsic or extrinsic stimuli by reorganizing its structure, functions, or connections. This means the brain physically rewires itself based on what we repeatedly think and do. Every new habit, skill, or thought pattern literally reshapes your neural architecture — you are never stuck.",
        "source_page": "Neuroplasticity",
        "source_url": "https://en.wikipedia.org/wiki/Neuroplasticity",
        "category": "psychology",
    },
]


# ── Wikipedia REST API helpers ────────────────────────────────────────────────

WIKI_REST = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "Brainboda/1.0 (youtube automation; contact@example.com)"}


def get_page_summary_rest(title: str) -> str | None:
    """Fetch page intro via Wikipedia REST summary endpoint."""
    url = WIKI_REST.format(title=title.replace(" ", "_"))
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                extract = data.get("extract", "")
                if extract and len(extract) > 80:
                    return extract.strip()
            return None
        except Exception as exc:
            log.warning("REST attempt %d failed for '%s': %s", attempt + 1, title, exc)
            time.sleep(2 ** attempt)
    return None


def get_page_extract_action(title: str) -> str | None:
    """Fetch page intro via Wikipedia action API (fallback)."""
    params = {
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "exintro": True,
        "explaintext": True,
        "redirects": True,
        "format": "json",
    }
    for attempt in range(3):
        try:
            resp = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                pages = resp.json().get("query", {}).get("pages", {})
                for page in pages.values():
                    extract = page.get("extract", "")
                    if extract and len(extract) > 80:
                        return extract.strip()
            return None
        except Exception as exc:
            log.warning("Action API attempt %d failed for '%s': %s", attempt + 1, title, exc)
            time.sleep(2 ** attempt)
    return None


def get_page_extract(title: str) -> str | None:
    """Try REST API first, then action API."""
    result = get_page_summary_rest(title)
    if result:
        return result
    return get_page_extract_action(title)


def get_category_members(category: str, limit: int = 50) -> list[str]:
    """Return page titles in a Wikipedia category (action API)."""
    titles: list[str] = []
    cmcontinue = None
    while len(titles) < limit:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmtype": "page",
            "cmlimit": min(50, limit - len(titles)),
            "format": "json",
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        try:
            resp = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                break
            data = resp.json()
            members = data.get("query", {}).get("categorymembers", [])
            titles.extend(m["title"] for m in members)
            if "continue" not in data:
                break
            cmcontinue = data["continue"].get("cmcontinue")
        except Exception as exc:
            log.warning("Category '%s' failed: %s", category, exc)
            break
    return titles


# ── fact extraction ───────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    text = re.sub(r"\[\d+\]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_sentences(text: str, min_len: int = 60, max_len: int = 350) -> list[str]:
    raw = re.split(r"(?<=[.!?])\s+", text)
    return [
        clean_text(s)
        for s in raw
        if min_len <= len(clean_text(s)) <= max_len and clean_text(s)[0:1].isupper()
    ]


def build_fact_from_extract(title: str, extract: str) -> dict | None:
    sentences = extract_sentences(extract)
    if not sentences:
        return None
    body = " ".join(sentences[:3])
    if len(body) < 80:
        return None
    hook = re.sub(r"\s*\(.*?\)\s*", " ", title).strip()
    return {
        "id": re.sub(r"[^a-z0-9_]", "_", title.lower()),
        "title": hook,
        "body": body,
        "source_page": title,
        "source_url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
        "category": "psychology",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


# ── deduplication ─────────────────────────────────────────────────────────────

def load_used_ids() -> set[str]:
    if not os.path.exists(USED_FACTS_JSON):
        return set()
    try:
        with open(USED_FACTS_JSON) as f:
            data = json.load(f)
        return set(data.get("used_ids", []))
    except Exception:
        return set()


def load_existing_raw_ids() -> set[str]:
    if not os.path.exists(FACTS_RAW_CSV):
        return set()
    ids: set[str] = set()
    try:
        with open(FACTS_RAW_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ids.add(row.get("id", ""))
    except Exception:
        pass
    return ids


# ── CSV writer ────────────────────────────────────────────────────────────────

CSV_FIELDS = ["id", "title", "body", "source_page", "source_url", "category", "fetched_at"]


def append_facts_to_csv(facts: list[dict]) -> None:
    file_exists = os.path.exists(FACTS_RAW_CSV) and os.path.getsize(FACTS_RAW_CSV) > 0
    with open(FACTS_RAW_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        now = datetime.now().isoformat(timespec="seconds")
        for fact in facts:
            row = {k: fact.get(k, "") for k in CSV_FIELDS}
            if not row.get("fetched_at"):
                row["fetched_at"] = now
            writer.writerow(row)


# ── fetch from Wikipedia ──────────────────────────────────────────────────────

def fetch_from_wikipedia(topic: str | None, limit: int, skip_ids: set[str]) -> list[dict]:
    """Try to fetch facts live from Wikipedia."""
    pages: list[str] = []

    if topic:
        log.info("Searching Wikipedia for topic: %s", topic)
        params = {
            "action": "query",
            "list": "search",
            "srsearch": f"{topic} psychology",
            "srlimit": 30,
            "srnamespace": 0,
            "format": "json",
        }
        try:
            resp = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                results = resp.json().get("query", {}).get("search", [])
                pages = [r["title"] for r in results]
        except Exception as exc:
            log.warning("Wikipedia search failed: %s", exc)
    else:
        pages = list(WIKIPEDIA_SEED_PAGES)
        for cat in WIKIPEDIA_CATEGORIES[:5]:
            try:
                members = get_category_members(cat, limit=20)
                pages.extend(members)
                log.info("Category '%s' → %d pages", cat, len(members))
                time.sleep(0.5)
            except Exception as exc:
                log.warning("Category '%s' failed: %s", cat, exc)

    seen: set[str] = set()
    unique_pages = [p for p in pages if not (p in seen or seen.add(p))]  # type: ignore[func-returns-value]

    facts: list[dict] = []
    for title in unique_pages:
        if len(facts) >= limit:
            break
        fact_id = re.sub(r"[^a-z0-9_]", "_", title.lower())
        if fact_id in skip_ids:
            continue
        try:
            extract = get_page_extract(title)
            if not extract:
                continue
            fact = build_fact_from_extract(title, extract)
            if not fact:
                continue
            facts.append(fact)
            skip_ids.add(fact["id"])
            log.info("[%d] ✓ %s", len(facts), title)
            time.sleep(0.3)
        except Exception as exc:
            log.error("Error processing '%s': %s", title, exc)

    return facts


# ── main ──────────────────────────────────────────────────────────────────────

def fetch_facts(topic: str | None = None, limit: int = 100, offline: bool = False) -> list[dict]:
    used_ids = load_used_ids()
    existing_ids = load_existing_raw_ids()
    skip_ids = used_ids | existing_ids
    log.info("Skipping %d already-known fact IDs", len(skip_ids))

    facts: list[dict] = []

    if not offline:
        log.info("Attempting live Wikipedia fetch…")
        try:
            facts = fetch_from_wikipedia(topic, limit, skip_ids)
            if facts:
                log.info("Wikipedia live fetch: %d facts collected", len(facts))
        except Exception as exc:
            log.warning("Wikipedia fetch failed entirely: %s", exc)

    if not facts:
        log.info("Falling back to built-in seed facts (offline mode)")
        # Filter by topic keyword if given
        seed = SEED_FACTS
        if topic:
            kw = topic.lower()
            seed = [f for f in seed if kw in f["title"].lower() or kw in f["body"].lower()]
            if not seed:
                seed = SEED_FACTS  # topic not found in seeds → use all
        for s in seed:
            if len(facts) >= limit:
                break
            if s["id"] in skip_ids:
                continue
            facts.append(s)
            skip_ids.add(s["id"])

    # Apply quality filter
    facts = [f for f in facts if is_psychology_relevant(f)]
    if facts:
        log.info("After quality filter: %d facts retained", len(facts))

    return facts


def main():
    parser = argparse.ArgumentParser(description="Fetch psychology facts from Wikipedia")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offline", action="store_true", help="Skip Wikipedia, use built-in seeds only")
    args = parser.parse_args()

    log.info("=== 01_fetch_facts.py START ===")
    log.info("Topic: %s | Limit: %d | Offline: %s", args.topic or "general psychology", args.limit, args.offline)

    facts = fetch_facts(topic=args.topic, limit=args.limit, offline=args.offline)

    if not facts:
        log.warning("No new facts fetched. CSV unchanged.")
        return

    append_facts_to_csv(facts)
    log.info("Saved %d new facts to %s", len(facts), FACTS_RAW_CSV)
    log.info("=== 01_fetch_facts.py DONE ===")

    print(f"\n{'='*60}")
    print(f"  Fetched {len(facts)} new facts → {FACTS_RAW_CSV}")
    print(f"{'='*60}")
    for i, f in enumerate(facts[:5], 1):
        print(f"\n[{i}] {f['title']}")
        print(f"    {f['body'][:130]}...")


if __name__ == "__main__":
    main()
