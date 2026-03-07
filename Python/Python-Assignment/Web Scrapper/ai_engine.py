"""
ai_engine.py
------------
AI answer-generation engine for the Doubt Resolution System.

Responsibilities:
  1. Accept scraped content from scraper.py
  2. Extract keywords and classify topic
  3. Summarise key concepts using HuggingFace Inference API (flan-t5-base)
  4. Generate a clear, readable answer
  5. Compute an AI confidence score

HOW IT FITS IN:
  student_portal.py and app.py both call generate_answer() here.
  This module calls scraper.py internally to get web content.

TWO MODES OF OPERATION:
  • With HF_TOKEN set  → Uses HuggingFace's flan-t5-base AI model for summarization
                         and answer generation (higher quality)
  • Without HF_TOKEN   → Uses a local extractive algorithm that picks the most
                         relevant sentences from the scraped text (works offline,
                         no API key needed)
"""

import os
import re
import logging
import textwrap
from collections import Counter   # Counter counts occurrences of items in a list

import requests

from scraper import scrape_answer   # Our web scraper module

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HuggingFace configuration
# ---------------------------------------------------------------------------

# The free AI model we use for summarization and answer generation.
# flan-t5-base is a Google model good at instruction-following tasks.
HUGGINGFACE_API_URL = (
    "https://router.huggingface.co/hf-inference/models/google/flan-t5-base"
)

# Read the HuggingFace API token from the environment.
# Set it with: export HF_TOKEN=your_token  (Mac/Linux)
#           or: set HF_TOKEN=your_token     (Windows)
# If not set, the system falls back to the local summarizer.
HF_TOKEN = os.environ.get("HF_TOKEN", "")

HF_HEADERS = {"Content-Type": "application/json"}
if HF_TOKEN:
    # Add the Bearer token header only if a token is actually available
    HF_HEADERS["Authorization"] = f"Bearer {HF_TOKEN}"

HF_TIMEOUT = 30  # seconds — HuggingFace can be slow when the model is cold-starting


# ---------------------------------------------------------------------------
# Public API — the only function other modules should call
# ---------------------------------------------------------------------------

def generate_answer(question: str, subject: str = "") -> dict:
    """
    End-to-end pipeline: scrape → summarise → answer.

    Steps:
      1. Call scraper.py to search the web and get raw paragraphs
      2. Extract keywords from the question + scraped text
      3. Classify the sub-topic (e.g., "Calculus", "Machine Learning")
      4. Summarize the scraped content (HuggingFace or local)
      5. Generate a final polished answer (HuggingFace only, or use summary)
      6. Attach source URLs to the answer
      7. Compute a confidence score

    Returns a dictionary:
      {
        "answer":      str,    The readable answer text (with sources appended)
        "confidence":  float,  0.0 – 1.0 (shown as % in the UI)
        "keywords":    str,    Comma-separated important terms
        "topic":       str,    Detected sub-topic
        "sources":     [str],  URLs used to build the answer
        "success":     bool,   False if something went wrong
        "error":       str,    Description of the error (empty on success)
      }
    """
    result = {
        "answer": "",
        "confidence": 0.0,
        "keywords": "",
        "topic": "",
        "sources": [],
        "success": False,
        "error": "",
    }

    # --- Step 1: Scrape the web for relevant content ---
    print("    [*] Searching the web for relevant content...")
    scrape_data = scrape_answer(question, subject)

    if not scrape_data["success"]:
        # Scraping failed — try asking the AI model directly without any context
        print("    [!] Web scraping returned no results. Querying AI model directly...")
        direct_answer = _query_huggingface(
            f"Answer this {subject} question in detail: {question}"
        )
        if direct_answer:
            result["answer"] = direct_answer
            result["confidence"] = 0.3   # Low confidence since we have no web sources
            result["keywords"] = _extract_keywords(question)
            result["topic"] = _classify_topic(question, subject)
            result["success"] = True
        else:
            result["error"] = (
                scrape_data["error"]
                + " (Tip: set the HF_TOKEN environment variable for AI-powered answers)"
            )
        return result

    raw_paragraphs = scrape_data["raw_paragraphs"]
    result["sources"] = scrape_data["sources"]

    # --- Step 2: Extract keywords ---
    # Combine the question + first 500 chars of scraped text, then find top 8 words
    combined_text = " ".join(raw_paragraphs[:5])
    result["keywords"] = _extract_keywords(question + " " + combined_text[:500])

    # --- Step 3: Classify the sub-topic ---
    result["topic"] = _classify_topic(question, subject)

    # --- Step 4: Summarize the scraped content ---
    # Limit to first 5 paragraphs and 3000 characters to stay within API token limits
    context_block = "\n".join(raw_paragraphs[:5])[:3000]

    summary = ""
    if HF_TOKEN:
        print("    [*] Summarising scraped content with AI model...")
        summary = _summarise_content(context_block, question)
    else:
        print("    [*] Summarising scraped content locally (no HF_TOKEN set)...")

    # If HuggingFace failed or no token was set, use the local extractive summarizer
    if not summary:
        summary = _local_summarise(raw_paragraphs, question)

    # --- Step 5: Generate a polished final answer (only if HuggingFace is available) ---
    if summary and HF_TOKEN:
        print("    [*] Generating final answer via AI model...")
        answer = _generate_final_answer(question, summary, subject)
        if answer:
            result["answer"] = _format_answer(answer, result["sources"])
            result["confidence"] = _compute_confidence(raw_paragraphs, answer)
            result["success"] = True
            return result

    # --- Step 6: Fallback — use the summary (local or HuggingFace) as the answer ---
    if summary:
        result["answer"] = _format_answer(summary, result["sources"])
        result["confidence"] = _compute_confidence(raw_paragraphs, summary)
        result["success"] = True
    elif raw_paragraphs:
        # Last resort: return the single best scraped paragraph
        result["answer"] = _format_answer(raw_paragraphs[0], result["sources"])
        result["confidence"] = 0.3
        result["success"] = True
    else:
        result["error"] = "AI engine could not generate an answer."

    return result


# ---------------------------------------------------------------------------
# HuggingFace API helpers
# ---------------------------------------------------------------------------

def _query_huggingface(prompt: str, max_length: int = 250) -> str:
    """Send a prompt to HuggingFace flan-t5-base and return the generated text.

    The model receives a text prompt and generates a continuation/answer.
    Returns an empty string if the request fails for any reason.

    Common failure reasons:
      - 503: Model is still loading (cold start) — wait ~20s and retry
      - No HF_TOKEN set — request will be unauthenticated and may be rate-limited
    """
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_length": max_length,   # Maximum length of the generated response
            "temperature": 0.7,         # Controls randomness (0=deterministic, 1=creative)
            "do_sample": False,         # False = use greedy/beam search (more consistent)
        },
    }
    try:
        resp = requests.post(
            HUGGINGFACE_API_URL, headers=HF_HEADERS, json=payload, timeout=HF_TIMEOUT
        )
        if resp.status_code == 200:
            data = resp.json()
            # HuggingFace returns either a list or a dict depending on the model
            if isinstance(data, list) and data:
                return data[0].get("generated_text", "").strip()
            if isinstance(data, dict):
                return data.get("generated_text", "").strip()
        elif resp.status_code == 503:
            logger.warning("HuggingFace model is loading. Try again shortly.")
        else:
            logger.warning("HuggingFace API error %s: %s", resp.status_code, resp.text[:200])
    except requests.exceptions.RequestException as exc:
        logger.warning("HuggingFace request failed: %s", exc)
    return ""


def _local_summarise(paragraphs: list[str], question: str) -> str:
    """Extractive summarizer — picks the most relevant sentences from scraped
    paragraphs without calling any external API.

    HOW IT WORKS:
      1. Split all paragraphs into individual sentences
      2. Score each sentence by how many question keywords it contains
      3. Add a small bonus for longer, more information-rich sentences
      4. Return the top-scoring sentences up to ~1500 characters total

    This is "extractive" because we're selecting existing sentences rather
    than generating new text (which would be "abstractive" summarization).
    """
    import re as _re

    # Words from the question that we'll look for in each sentence
    query_words = set(_re.findall(r"[a-zA-Z]{3,}", question.lower()))

    # Remove common filler words that appear everywhere and would inflate scores
    stop = {
        "the", "and", "for", "that", "this", "with", "from", "are",
        "was", "were", "has", "have", "been", "will", "can", "not",
        "but", "its", "also", "more", "such", "than", "what",
    }
    query_words -= stop   # Remove stop words from the set we're matching against

    sentences: list[tuple[float, str]] = []

    for para in paragraphs:
        # Split each paragraph into sentences at punctuation boundaries
        for sent in _re.split(r'(?<=[.!?])\s+', para):
            sent = sent.strip()
            if len(sent) < 40:
                continue   # Skip very short fragments

            words = set(_re.findall(r"[a-zA-Z]{3,}", sent.lower())) - stop
            if not words:
                continue

            # Jaccard-like overlap: how many question keywords does this sentence contain?
            overlap = len(query_words & words)
            score = overlap / max(len(query_words), 1)

            # Bonus for longer, more informative sentences
            if len(sent) > 100:
                score += 0.1

            sentences.append((score, sent))

    # Sort by score, best first
    sentences.sort(key=lambda x: x[0], reverse=True)

    # Build output string, stopping before we exceed 1500 characters
    selected: list[str] = []
    total_len = 0
    for _, sent in sentences:
        if total_len + len(sent) > 1500:
            break
        selected.append(sent)
        total_len += len(sent)

    return " ".join(selected) if selected else ""


def _summarise_content(context: str, question: str) -> str:
    """Ask the HuggingFace model to summarize scraped context focused on the question.

    The prompt is carefully structured to give the model both the context
    (scraped web text) and the question, so it produces a focused summary.
    """
    prompt = textwrap.dedent(f"""\
        Summarize the following information to answer the question.
        Question: {question}
        Information: {context[:2000]}
        Summary:""")
    return _query_huggingface(prompt, max_length=300)


def _generate_final_answer(question: str, summary: str, subject: str) -> str:
    """Use the summary to produce a polished, well-structured answer.

    This is a second API call — first we summarized the scraped content,
    now we ask the model to write a proper answer using that summary.
    Using two steps (summarize → answer) produces much better results than
    directly asking the model to answer from raw scraped text.
    """
    prompt = textwrap.dedent(f"""\
        You are an expert in {subject or 'academics'}.
        Using the summary below, write a clear and detailed answer to the question.
        Question: {question}
        Summary: {summary}
        Answer:""")
    return _query_huggingface(prompt, max_length=300)


# ---------------------------------------------------------------------------
# Intelligence utilities
# ---------------------------------------------------------------------------

def _extract_keywords(text: str) -> str:
    """Extract the most frequent meaningful words from the text as keywords.

    Steps:
      1. Find all words that are 4+ characters long (avoids tiny noise words)
      2. Remove common stop words
      3. Count occurrences with Counter
      4. Return the 8 most common words as a comma-separated string
    """
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())

    # Stop words — ignored because they appear in almost every sentence
    stop = {
        "this", "that", "with", "from", "what", "which", "where", "when",
        "were", "been", "have", "does", "will", "would", "could", "should",
        "about", "their", "there", "these", "those", "also", "more", "some",
        "than", "other", "into", "very", "just", "your", "they", "them",
        "then", "each", "only", "such", "like", "over", "after", "before",
        "between", "under", "during", "without", "however", "because",
    }
    filtered = [w for w in words if w not in stop]

    # Counter({'python': 5, 'variable': 3, ...}).most_common(8) → top 8 words
    common = Counter(filtered).most_common(8)
    return ", ".join(word for word, _ in common)


def _classify_topic(question: str, subject: str) -> str:
    """Simple rule-based topic classifier.

    Scans the question for domain-specific keywords and returns a
    descriptive topic label. Falls back to the subject name (or "General")
    if no keyword matches.

    This is rule-based (no ML) — fast, deterministic, works offline.
    """
    q = question.lower()

    # Map keyword → topic label
    topic_map = {
        "algorithm": "Algorithms & Data Structures",
        "data structure": "Algorithms & Data Structures",
        "programming": "Programming",
        "python": "Programming – Python",
        "java": "Programming – Java",
        "machine learning": "Machine Learning",
        "neural network": "Deep Learning",
        "calculus": "Calculus",
        "integral": "Calculus",
        "derivative": "Calculus",
        "matrix": "Linear Algebra",
        "quantum": "Quantum Physics",
        "thermodynamic": "Thermodynamics",
        "newton": "Classical Mechanics",
        "election": "Political Science",
        "democracy": "Political Science",
        "history": "History",
        "war": "History / Military",
        "evolution": "Biology – Evolution",
        "cell": "Biology – Cell Biology",
        "chemical": "Chemistry",
        "reaction": "Chemistry",
        "economy": "Economics",
        "inflation": "Economics",
    }
    for keyword, topic in topic_map.items():
        if keyword in q:
            return topic

    # No keyword matched — use the subject name or a generic label
    return subject if subject else "General"


def _compute_confidence(paragraphs: list[str], answer: str) -> float:
    """Heuristic confidence score based on content richness.

    Starts at 0.5 (baseline) and adds points for:
      - Having more scraped paragraphs (more sources = more confident)
      - Having a longer answer (more detail = more confident)

    Capped at 1.0 (100%).
    """
    score = 0.5
    if len(paragraphs) >= 3:
        score += 0.1   # Found content on at least 3 different sources
    if len(paragraphs) >= 5:
        score += 0.1   # Found content on 5+ sources
    if len(answer) > 200:
        score += 0.1   # Answer has a reasonable amount of detail
    if len(answer) > 500:
        score += 0.1   # Answer is comprehensive
    return min(score, 1.0)


def _format_answer(answer: str, sources: list[str]) -> str:
    """Append numbered source references to the end of the answer text.

    Example output:
      ... answer text ...

      --- Sources ---
      [1] https://en.wikipedia.org/wiki/...
      [2] https://www.geeksforgeeks.org/...
    """
    text = answer.strip()
    if sources:
        text += "\n\n--- Sources ---"
        for i, url in enumerate(sources, 1):
            text += f"\n[{i}] {url}"
    return text
