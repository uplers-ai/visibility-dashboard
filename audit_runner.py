"""Location-aware LLM audit runner.

LLM query and company-extraction logic is copied (intentionally, per spec)
from ../visibility_audit2.0.py so this dashboard is independent.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import defaultdict
from typing import Callable

import requests

try:
    from dotenv import load_dotenv
    # Load .env from project root (parent dir) so existing keys work
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5

ENABLE = {
    "ChatGPT": os.getenv("ENABLE_CHATGPT", "true").lower() == "true",
    "Claude": os.getenv("ENABLE_CLAUDE", "true").lower() == "true",
    "Gemini": os.getenv("ENABLE_GEMINI", "true").lower() == "true",
    "Grok": os.getenv("ENABLE_GROK", "true").lower() == "true",
    "Perplexity": os.getenv("ENABLE_PERPLEXITY", "true").lower() == "true",
}


# ---------------------------------------------------------------------------
# Known platforms (copied from visibility_audit2.0.py)
# ---------------------------------------------------------------------------

PLATFORM_VARIATIONS = {
    "Uplers": ["uplers", "uplers.com", "uplers ai hiring platform", "uplers ai", "uplers platform", "uplers talent"],
    "Toptal": ["toptal", "toptal.com"],
    "Turing": ["turing", "turing.com"],
    "Andela": ["andela", "andela.com"],
    "Arc": ["arc.dev", "arc dev"],
    "CloudDevs": ["clouddevs", "cloud devs", "clouddevs.com"],
    "Terminal": ["terminal.io", "terminal io"],
    "Gun.io": ["gun.io", "gun io", "gunio"],
    "Lemon.io": ["lemon.io", "lemon io", "lemonpicker"],
    "BairesDev": ["bairesdev", "baires dev", "bairesdev.com"],
    "Revelo": ["revelo", "revelo.com"],
    "Supersourcing": ["supersourcing", "super sourcing"],
    "Gigster": ["gigster", "gigster.com"],
    "Multiplier": ["multiplier", "multiplier.com"],
    "Remote": ["remote.com", "remote.co"],
    "Deel": ["deel", "deel.com"],
    "Oyster": ["oyster", "oysterhr", "oyster hr"],
    "Globalization Partners": ["globalization partners", "g-p.com", "g-p"],
    "Fiverr": ["fiverr", "fiverr.com"],
    "Upwork": ["upwork", "upwork.com"],
    "Freelancer": ["freelancer.com", "freelancer.in"],
    "LinkedIn": ["linkedin", "linkedin.com"],
    "Indeed": ["indeed", "indeed.com"],
    "Hired": ["hired.com", "hired platform"],
    "Triplebyte": ["triplebyte"],
    "Vettery": ["vettery"],
    "Crossover": ["crossover", "crossover.com"],
    "X-Team": ["x-team", "xteam"],
    "Scalable Path": ["scalable path", "scalablepath"],
    "Codementor": ["codementor", "codementorx"],
    "RemoteOK": ["remoteok", "remote ok"],
    "We Work Remotely": ["we work remotely", "weworkremotely"],
    "AngelList": ["angellist", "angel list", "wellfound"],
    "Stack Overflow Jobs": ["stack overflow jobs", "stackoverflow jobs"],
    "GitHub Jobs": ["github jobs"],
    "Dice": ["dice.com"],
    "Naukri": ["naukri", "naukri.com"],
    "TalentScale": ["talentscale", "talent scale"],
    "Flexiple": ["flexiple"],
    "RemotePanda": ["remotepanda", "remote panda"],
    "HackerRank": ["hackerrank", "hacker rank"],
    "CodeSignal": ["codesignal", "code signal"],
    "Karat": ["karat"],
    "Talent500": ["talent500", "talent 500"],
    "Pesto": ["pesto.tech", "pesto tech"],
    "GeeksforGeeks": ["geeksforgeeks", "gfg jobs"],
    "Instahyre": ["instahyre"],
    "Hirect": ["hirect"],
    "Cutshort": ["cutshort"],
    "Hirist": ["hirist"],
    "iimjobs": ["iimjobs"],
    "Glassdoor": ["glassdoor"],
    "ZipRecruiter": ["ziprecruiter", "zip recruiter"],
    "SimplyHired": ["simplyhired", "simply hired"],
    "Workable": ["workable"],
    "Lever": ["lever.co", "lever hiring"],
    "Greenhouse": ["greenhouse.io", "greenhouse"],
}

COMMON_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "they", "have", "will",
    "can", "how", "what", "when", "where", "which", "best", "top", "good", "great",
    "here", "some", "many", "most", "also", "other", "more", "very", "just", "only",
    "even", "such", "like", "well", "back", "been", "being", "both", "each", "find",
    "first", "get", "give", "go", "look", "make", "need", "new", "now", "over",
    "see", "take", "time", "want", "way", "work", "year", "know", "could", "into",
    "than", "then", "them", "these", "think", "through", "would", "about", "after",
    "before", "between", "come", "down", "during", "high", "long", "made", "part",
    "people", "place", "same", "should", "still", "under", "while", "again",
    "against", "below", "different", "does", "doing", "done", "enough", "every",
    "example", "following", "found", "further", "given", "going", "higher",
    "however", "important", "including", "large", "later", "less", "little",
    "local", "looking", "lower", "major", "making", "must", "never", "number",
    "often", "open", "possible", "present", "rather", "recent", "right", "second",
    "several", "since", "small", "social", "something", "special", "state",
    "states", "sure", "system", "things", "those", "three", "today", "together",
    "trying", "using", "various", "ways", "within", "without", "working", "world",
    "years", "young", "software", "developer", "developers", "engineer",
    "engineers", "platform", "platforms", "hiring", "hire", "talent", "remote",
    "india", "indian", "company", "companies", "based", "services", "service",
}


def extract_companies(text: str) -> dict:
    """Extract company/platform mentions from LLM text response."""
    if not text:
        return {}

    mentions: dict[str, int] = {}
    text_lower = text.lower()

    for platform, patterns in PLATFORM_VARIATIONS.items():
        count = 0
        for pattern in patterns:
            p_lower = pattern.lower()
            if len(p_lower) <= 4:
                count += len(re.findall(r"\b" + re.escape(p_lower) + r"\b", text_lower))
            else:
                count += text_lower.count(p_lower)
        if count > 0:
            mentions[platform] = count

    # URL/domain extraction
    for url in re.findall(
        r"\b([a-zA-Z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9]+)*\.(?:io|com|dev|co|tech|ai))\b",
        text,
        re.IGNORECASE,
    ):
        platform_name = url.split(".")[0].capitalize()
        if platform_name in mentions or len(platform_name) <= 2:
            continue
        if any(platform_name.lower() in k.lower() or k.lower() in platform_name.lower() for k in mentions):
            continue
        mentions[url] = 1

    # Numbered list / bullet items
    for item in re.findall(
        r"(?:^|\n)\s*(?:\d+[\.\)]\s*|[-•*]\s*)([A-Z][a-zA-Z0-9\.\-]+(?:\s+[A-Z][a-zA-Z0-9\.\-]+)?)",
        text,
    ):
        item_clean = item.strip()
        if len(item_clean) <= 2 or item_clean.lower() in COMMON_WORDS:
            continue
        if any(item_clean.lower() == k.lower() for k in mentions):
            continue
        mentions.setdefault(item_clean, 1)

    return mentions


# ---------------------------------------------------------------------------
# Mention vs Citation classification + link extraction
# ---------------------------------------------------------------------------

_SOURCES_MARKER = re.compile(
    r"\n\s*(?:sources?|references?|citations?|further reading|bibliography)\s*[:：]*\s*\n",
    re.IGNORECASE,
)

_URL_REGEX = re.compile(r"https?://[^\s<>\"'\)\]]+", re.IGNORECASE)

_URL_TLDS = r"(?:com|io|dev|co|tech|ai|org|net|in|uk|app|us|me)"


def _split_body_sources(text: str) -> tuple[str, str]:
    """Split text into (body, sources_section) at explicit Sources: / References:
    markers. We deliberately do NOT treat bare numbered lists as sources — LLMs
    often answer with `1. Foo 2. Bar` which is content, not citations."""
    m = _SOURCES_MARKER.search(text or "")
    if m:
        return text[: m.start()], text[m.start() :]
    return text or "", ""


def classify_occurrences(text: str, brand: str) -> tuple[int, int]:
    """Return (mentions, citations) for a brand in a response.

    - mention = bare brand word in the body (prose recommendation)
    - citation = brand in URL form (brand.com / .io / ...), OR any occurrence
      inside a Sources/References section
    """
    if not text or not brand:
        return 0, 0

    body, sources = _split_body_sources(text)
    brand_lower = brand.lower()
    brand_esc = re.escape(brand_lower)

    url_pattern = re.compile(r"\b" + brand_esc + r"\." + _URL_TLDS + r"\b", re.IGNORECASE)
    word_pattern = re.compile(r"\b" + brand_esc + r"\b", re.IGNORECASE)

    # All occurrences inside Sources section count as citations
    sources_citations = len(word_pattern.findall(sources))

    # URL-form occurrences in body = citations
    body_url_citations = len(url_pattern.findall(body))

    # Bare-word mentions in body (exclude positions inside URLs)
    body_without_brand_urls = url_pattern.sub("___URL___", body)
    body_mentions = len(word_pattern.findall(body_without_brand_urls))

    return body_mentions, body_url_citations + sources_citations


def classify_all_companies(text: str, companies: list[str]) -> dict:
    """For each company name, return {"mentions": N, "citations": M}."""
    out: dict[str, dict] = {}
    if not text or not companies:
        return out
    for c in companies:
        m, ci = classify_occurrences(text, c)
        if m or ci:
            out[c] = {"mentions": m, "citations": ci}
    return out


def extract_links(text: str, api_citations: list | None = None) -> list[dict]:
    """Extract every URL from the response text. Returns list of
    {url, in_sources, title?}. `api_citations` is extra URLs returned by
    Perplexity's API (always treated as source-section)."""
    body, _ = _split_body_sources(text or "")
    body_end = len(body)

    def clean(u: str) -> str:
        return u.rstrip(".,;:!?)]}'\"")

    seen: set[str] = set()
    out: list[dict] = []

    for m in _URL_REGEX.finditer(text or ""):
        url = clean(m.group(0))
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "in_sources": m.start() >= body_end})

    if api_citations:
        for c in api_citations:
            if isinstance(c, str):
                url = clean(c)
                if url and url not in seen:
                    seen.add(url)
                    out.append({"url": url, "in_sources": True})
            elif isinstance(c, dict):
                url = clean(c.get("url") or "")
                if url and url not in seen:
                    seen.add(url)
                    entry = {"url": url, "in_sources": True}
                    if c.get("title"):
                        entry["title"] = c["title"]
                    out.append(entry)

    return out


# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------

_clients: dict = {}


def _init_clients() -> dict:
    if _clients:
        return _clients

    if os.getenv("OPENAI_API_KEY") and ENABLE["ChatGPT"]:
        try:
            from openai import OpenAI
            _clients["ChatGPT"] = OpenAI()
        except Exception as e:
            logger.warning(f"OpenAI init failed: {e}")

    if os.getenv("ANTHROPIC_API_KEY") and ENABLE["Claude"]:
        try:
            import anthropic
            _clients["Claude"] = anthropic.Anthropic()
        except Exception as e:
            logger.warning(f"Anthropic init failed: {e}")

    if os.getenv("GOOGLE_API_KEY") and ENABLE["Gemini"]:
        try:
            import google.generativeai as genai
            from google.generativeai.types import HarmBlockThreshold, HarmCategory

            genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
            safety = {
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            }
            _clients["Gemini"] = genai.GenerativeModel(
                model_name="gemini-2.5-flash",
                safety_settings=safety,
            )
        except Exception as e:
            logger.warning(f"Gemini init failed: {e}")

    if os.getenv("XAI_API_KEY") and ENABLE["Grok"]:
        _clients["Grok"] = os.getenv("XAI_API_KEY")

    if os.getenv("PERPLEXITY_API_KEY") and ENABLE["Perplexity"]:
        _clients["Perplexity"] = os.getenv("PERPLEXITY_API_KEY")

    return _clients


def available_llms() -> list[str]:
    return list(_init_clients().keys())


def _retry(func: Callable, name: str) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            return func()
        except Exception as e:
            err = str(e).lower()
            wait = (30 if any(k in err for k in ("429", "rate", "quota", "exhausted")) else RETRY_DELAY) * (2 ** attempt)
            logger.warning(f"{name} attempt {attempt + 1}/{MAX_RETRIES} failed ({e}); waiting {wait}s")
            time.sleep(wait)
    return ""


def _location_phrase(country: str | None, state: str | None, city: str | None) -> str:
    parts = [p for p in (city, state, country) if p]
    return ", ".join(parts) if parts else "USA"


def _system_prompt(location: str) -> str:
    return (
        f"You are a helpful assistant. The user is based in {location}. "
        "When recommending platforms or companies, please be specific and name them. "
        "Prioritize platforms and services that operate in or are relevant to the user's location."
    )


# ---------------------------------------------------------------------------
# Per-LLM query functions
# ---------------------------------------------------------------------------

def query_openai(prompt: str, location: str) -> tuple[str, list]:
    client = _clients.get("ChatGPT")
    if not client:
        return "", []

    def _call():
        resp = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": _system_prompt(location)},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1500,
            temperature=0.7,
        )
        return resp.choices[0].message.content or ""

    return _retry(_call, "OpenAI"), []


def query_anthropic(prompt: str, location: str) -> tuple[str, list]:
    client = _clients.get("Claude")
    if not client:
        return "", []

    def _call():
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=_system_prompt(location),
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    return _retry(_call, "Anthropic"), []


def query_gemini(prompt: str, location: str) -> tuple[str, list]:
    model = _clients.get("Gemini")
    if not model:
        return "", []

    full_prompt = f"{_system_prompt(location)}\n\nUser question: {prompt}"

    def _call():
        time.sleep(2)
        resp = model.generate_content(full_prompt)
        if not resp.candidates:
            return ""
        if resp.candidates[0].finish_reason != 1:
            return ""
        if resp.candidates[0].content.parts:
            return resp.text or ""
        return ""

    return _retry(_call, "Gemini"), []


def query_grok(prompt: str, location: str) -> tuple[str, list]:
    api_key = _clients.get("Grok")
    if not api_key:
        return "", []

    def _call():
        resp = requests.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "grok-3-latest",
                "messages": [
                    {"role": "system", "content": _system_prompt(location)},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1500,
                "temperature": 0.7,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return _retry(_call, "Grok"), []


def query_perplexity(prompt: str, location: str) -> tuple[str, list]:
    api_key = _clients.get("Perplexity")
    if not api_key:
        return "", []

    # Perplexity returns citations in a separate field — capture via closure
    captured_citations: list = []

    def _call():
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "sonar-pro",
                "messages": [
                    {"role": "system", "content": _system_prompt(location)},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1500,
                "temperature": 0.7,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()

        # Collect citations — Perplexity's schema has varied; handle both
        # `citations: [url, ...]` and newer `search_results: [{url, title}, ...]`
        captured_citations.clear()
        for c in data.get("citations") or []:
            if isinstance(c, str):
                captured_citations.append(c)
            elif isinstance(c, dict) and c.get("url"):
                captured_citations.append(c)
        for sr in data.get("search_results") or []:
            if isinstance(sr, dict) and sr.get("url"):
                captured_citations.append({"url": sr["url"], "title": sr.get("title")})

        return data["choices"][0]["message"]["content"]

    text = _retry(_call, "Perplexity")
    return text, list(captured_citations)


QUERY_FUNCS = {
    "ChatGPT": query_openai,
    "Claude": query_anthropic,
    "Gemini": query_gemini,
    "Grok": query_grok,
    "Perplexity": query_perplexity,
}


# ---------------------------------------------------------------------------
# Audit orchestration
# ---------------------------------------------------------------------------

def run_audit(
    *,
    queries: list[dict],
    llms: list[str],
    runs_per_prompt: int,
    target_company: str,
    country: str | None,
    state: str | None,
    city: str | None,
    on_result: Callable[[dict], None],
    on_progress: Callable[[int, int, str], None],
) -> None:
    """Execute the audit. Each result is delivered via on_result; progress via on_progress."""
    _init_clients()
    location = _location_phrase(country, state, city)

    total = len(queries) * len(llms) * runs_per_prompt
    completed = 0

    for q in queries:
        for llm in llms:
            func = QUERY_FUNCS.get(llm)
            if not func or llm not in _clients:
                # LLM not configured - record empty results so totals stay consistent
                for run_num in range(1, runs_per_prompt + 1):
                    completed += 1
                    on_result({
                        "query_id": q["id"],
                        "llm": llm,
                        "run_number": run_num,
                        "response": "",
                        "companies_mentioned": {},
                        "companies_classified": {},
                        "target_mentioned": False,
                        "target_mention_count": 0,
                        "target_citation_count": 0,
                        "links": [],
                    })
                    on_progress(completed, total, f"{llm} unavailable - skipping")
                continue

            for run_num in range(1, runs_per_prompt + 1):
                response, api_citations = func(q["text"], location)
                companies = extract_companies(response)
                classified = classify_all_companies(response, list(companies.keys()))
                t_mentions, t_citations = classify_occurrences(response, target_company)
                # If the target isn't in our detected list but we found occurrences,
                # make sure it shows up in classified for rankings
                if (t_mentions or t_citations) and target_company not in classified:
                    classified[target_company] = {"mentions": t_mentions, "citations": t_citations}
                target_mentioned = bool(t_mentions or t_citations)
                links = extract_links(response, api_citations)

                on_result({
                    "query_id": q["id"],
                    "llm": llm,
                    "run_number": run_num,
                    "response": response,
                    "companies_mentioned": companies,
                    "companies_classified": classified,
                    "target_mentioned": target_mentioned,
                    "target_mention_count": t_mentions,
                    "target_citation_count": t_citations,
                    "links": links,
                })
                completed += 1
                on_progress(
                    completed, total,
                    f"{llm} | run {run_num}/{runs_per_prompt} | {q['text'][:60]}"
                )
                time.sleep(1)


# ---------------------------------------------------------------------------
# Analysis (computed after audit completes from stored results)
# ---------------------------------------------------------------------------

def _rank_companies(
    results: list[dict],
    key: str,  # "mentions" or "citations"
) -> list[dict]:
    """Sum per-company `key` counts across results and return ranked list."""
    totals: dict[str, int] = defaultdict(int)
    for r in results:
        classified = r.get("companies_classified") or {}
        for company, counts in classified.items():
            totals[company] += counts.get(key, 0)
    totals = {c: n for c, n in totals.items() if n > 0}
    return [
        {"company": c, key: n, "rank": i + 1}
        for i, (c, n) in enumerate(sorted(totals.items(), key=lambda x: x[1], reverse=True))
    ]


def analyze(results: list[dict], target_company: str) -> dict:
    """Compute analytics from a list of result dicts (from db.get_results)."""
    if not results:
        return {}

    analysis: dict = {
        "meta": {
            "target_company": target_company,
            "total_queries": len(results),
            "llms_tested": sorted({r["llm"] for r in results}),
        },
        "overall": {},
        "by_llm": {},
        "by_intent": {},
        "company_rankings": {},          # legacy: any-occurrence counts
        "rankings_recommended": {},      # NEW: ranked by mention count
        "rankings_cited": {},            # NEW: ranked by citation count
        "weak_spots": [],
    }

    n = len(results)
    target_any = sum(1 for r in results if r["target_mentioned"])
    target_recommended = sum(1 for r in results if r.get("target_mention_count", 0) > 0)
    target_cited = sum(1 for r in results if r.get("target_citation_count", 0) > 0)
    target_cited_only = sum(
        1 for r in results
        if r.get("target_citation_count", 0) > 0 and r.get("target_mention_count", 0) == 0
    )
    analysis["overall"]["visibility_score"] = round(target_any / n * 100, 1)
    analysis["overall"]["recommendation_score"] = round(target_recommended / n * 100, 1)
    analysis["overall"]["citation_score"] = round(target_cited / n * 100, 1)
    analysis["overall"]["cited_only_score"] = round(target_cited_only / n * 100, 1)
    analysis["overall"]["target_mentions"] = target_any
    analysis["overall"]["target_recommended_in"] = target_recommended
    analysis["overall"]["target_cited_in"] = target_cited
    analysis["overall"]["total_mention_occurrences"] = sum(r.get("target_mention_count", 0) for r in results)
    analysis["overall"]["total_citation_occurrences"] = sum(r.get("target_citation_count", 0) for r in results)
    analysis["overall"]["total_queries"] = n

    for llm in analysis["meta"]["llms_tested"]:
        rows = [r for r in results if r["llm"] == llm]
        any_ = sum(1 for r in rows if r["target_mentioned"])
        rec = sum(1 for r in rows if r.get("target_mention_count", 0) > 0)
        cit = sum(1 for r in rows if r.get("target_citation_count", 0) > 0)
        analysis["by_llm"][llm] = {
            "visibility_score": round(any_ / len(rows) * 100, 1) if rows else 0,
            "recommendation_score": round(rec / len(rows) * 100, 1) if rows else 0,
            "citation_score": round(cit / len(rows) * 100, 1) if rows else 0,
            "mentions": any_,
            "recommended_in": rec,
            "cited_in": cit,
            "mention_occurrences": sum(r.get("target_mention_count", 0) for r in rows),
            "citation_occurrences": sum(r.get("target_citation_count", 0) for r in rows),
            "queries": len(rows),
        }

    intents = {r.get("query_intent") or "General" for r in results}
    for intent in intents:
        rows = [r for r in results if (r.get("query_intent") or "General") == intent]
        any_ = sum(1 for r in rows if r["target_mentioned"])
        rec = sum(1 for r in rows if r.get("target_mention_count", 0) > 0)
        score = round(any_ / len(rows) * 100, 1) if rows else 0
        analysis["by_intent"][intent] = {
            "visibility_score": score,
            "recommendation_score": round(rec / len(rows) * 100, 1) if rows else 0,
            "mentions": any_,
            "queries": len(rows),
        }
        if score < 20:
            analysis["weak_spots"].append({
                "intent": intent,
                "visibility": score,
                "sample_prompts": list({r["query_text"] for r in rows})[:3],
            })

    # Legacy rankings (any occurrence) — kept for backward compat
    counts: dict[str, int] = defaultdict(int)
    for r in results:
        for c, cnt in r["companies_mentioned"].items():
            counts[c] += cnt
    sorted_overall = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    analysis["company_rankings"]["overall"] = [
        {"company": c, "mentions": m, "rank": i + 1} for i, (c, m) in enumerate(sorted_overall)
    ]
    target_rank = next(
        (i + 1 for i, (c, _) in enumerate(sorted_overall) if c.lower() == target_company.lower()),
        len(sorted_overall) + 1,
    )
    analysis["overall"]["target_rank"] = target_rank
    analysis["overall"]["total_companies_mentioned"] = len(sorted_overall)

    for llm in analysis["meta"]["llms_tested"]:
        per: dict[str, int] = defaultdict(int)
        for r in [x for x in results if x["llm"] == llm]:
            for c, cnt in r["companies_mentioned"].items():
                per[c] += cnt
        analysis["company_rankings"][llm] = [
            {"company": c, "mentions": m, "rank": i + 1}
            for i, (c, m) in enumerate(sorted(per.items(), key=lambda x: x[1], reverse=True))
        ]

    # NEW: split rankings — recommended vs cited
    analysis["rankings_recommended"]["overall"] = _rank_companies(results, "mentions")
    analysis["rankings_cited"]["overall"] = _rank_companies(results, "citations")
    for llm in analysis["meta"]["llms_tested"]:
        llm_rows = [r for r in results if r["llm"] == llm]
        analysis["rankings_recommended"][llm] = _rank_companies(llm_rows, "mentions")
        analysis["rankings_cited"][llm] = _rank_companies(llm_rows, "citations")

    # Target rank in recommended list
    rec_overall = analysis["rankings_recommended"]["overall"]
    target_rec_rank = next(
        (x["rank"] for x in rec_overall if x["company"].lower() == target_company.lower()),
        None,
    )
    analysis["overall"]["target_recommended_rank"] = target_rec_rank

    return analysis
