"""
scraper.py
----------
Web-scraping engine for the Doubt Resolution System.

Workflow:
1. Search DuckDuckGo for the question.
2. Fetch the top relevant links.
3. Extract educational paragraphs with trafilatura / BeautifulSoup.
4. Filter and return clean text chunks ready for the AI engine.

HOW IT FITS IN:
  ai_engine.py calls scrape_answer() to get raw text from the web.
  The returned paragraphs are then processed into a readable answer.
"""

import re
import logging
from urllib.parse import urlparse

import requests                # For downloading web pages (HTTP requests)
from bs4 import BeautifulSoup  # For parsing HTML and extracting text

# trafilatura: a smarter text extractor that focuses on the "main content"
# of a page and ignores ads, menus, footers, etc.
# Imported inside a try/except so the app still works if it's not installed.
try:
    import trafilatura
except ImportError:
    trafilatura = None   # Will fall back to BeautifulSoup if not available

# duckduckgo_search: lets us programmatically search DuckDuckGo (no API key needed)
# Two package names are tried because the package was renamed at some point.
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None   # Will fall back to hardcoded Wikipedia/GFG URLs

logger = logging.getLogger(__name__)   # Module-level logger for warnings/errors

# ---------------------------------------------------------------------------
# Configuration constants
# These control scraping behaviour. Adjust them here to affect the whole module.
# ---------------------------------------------------------------------------

# Domains considered trustworthy for educational content.
# Currently informational — could be used to boost scores of results from these sites.
TRUSTED_DOMAINS = [
    "wikipedia.org",
    "stackoverflow.com",
    "geeksforgeeks.org",
    "britannica.com",
    "khanacademy.org",
    "tutorialspoint.com",
    "w3schools.com",
    "mathsisfun.com",
    "sciencedirect.com",
]

REQUEST_TIMEOUT = 12   # How many seconds to wait for a web page to respond
MAX_LINKS = 5          # Maximum number of URLs to scrape per question

# Pretend to be a real browser so websites don't block us
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT}


# ---------------------------------------------------------------------------
# Public API — the only function other modules should call
# ---------------------------------------------------------------------------

def scrape_answer(query: str, subject: str = "") -> dict:
    """
    Main entry point for the scraper.

    Takes a question (and optional subject) and returns a dictionary:
      {
        "raw_paragraphs": [str, ...],  # List of relevant text paragraphs from the web
        "sources":        [str, ...],  # List of URLs that were successfully scraped
        "success":        bool,        # True if at least one paragraph was found
        "error":          str          # Description of what went wrong (empty on success)
      }

    The steps are:
      1. Search DuckDuckGo for the question
      2. For each result URL, download the page and extract text paragraphs
      3. Score paragraphs by how many words overlap with the question
      4. Return the top 10 most relevant paragraphs
    """
    result = {
        "raw_paragraphs": [],
        "sources": [],
        "success": False,
        "error": "",
    }

    # Prepend subject to the query for more targeted results
    # e.g., "Physics What is Newton's first law" instead of just "What is Newton's first law"
    search_query = f"{subject} {query}" if subject else query
    urls = _search_duckduckgo(search_query)

    if not urls:
        result["error"] = "No search results found."
        return result

    all_paragraphs: list[str] = []
    used_sources: list[str] = []

    # Visit each URL and collect text paragraphs
    for url in urls[:MAX_LINKS]:
        try:
            paragraphs = _extract_content(url)
            if paragraphs:
                all_paragraphs.extend(paragraphs)
                used_sources.append(url)
        except Exception as exc:
            # Don't crash if one URL fails — just skip it and log the problem
            logger.warning("Failed to scrape %s: %s", url, exc)

    if not all_paragraphs:
        result["error"] = "Could not extract content from any source."
        return result

    # Score and filter paragraphs by how relevant they are to the question
    relevant = _filter_relevant(all_paragraphs, query)

    # Use the filtered list, or fall back to the first 10 unfiltered paragraphs
    result["raw_paragraphs"] = relevant if relevant else all_paragraphs[:10]
    result["sources"] = used_sources
    result["success"] = True
    return result


# ---------------------------------------------------------------------------
# Search — find URLs to scrape
# ---------------------------------------------------------------------------

def _search_duckduckgo(query: str) -> list[str]:
    """Search DuckDuckGo and return a list of result URLs.

    Uses the duckduckgo_search library (no API key required).
    Falls back to hardcoded URLs if the library is missing or the search fails.
    """
    if DDGS is None:
        logger.error("duckduckgo_search is not installed.")
        return _fallback_search(query)
    try:
        ddgs = DDGS()
        results = ddgs.text(query, max_results=MAX_LINKS)
        # Extract just the URL from each result dictionary
        return [r["href"] for r in results if "href" in r]
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s. Using fallback.", exc)
        return _fallback_search(query)


def _fallback_search(query: str) -> list[str]:
    """Build direct Wikipedia / GeeksforGeeks URLs when DDGS is unavailable.

    Converts the query to a URL-friendly slug:
      "What is Python" → "What_is_Python" for Wikipedia
                       → "what-is-python" for GeeksForGeeks
    """
    slug = query.strip().replace(" ", "_")       # Wikipedia-style slug
    encoded = requests.utils.quote(query)        # URL-safe encoding for search query
    return [
        f"https://en.wikipedia.org/wiki/{slug}",
        f"https://www.geeksforgeeks.org/{slug.lower().replace('_', '-')}/",
        f"https://www.britannica.com/search?query={encoded}",
    ]


# ---------------------------------------------------------------------------
# Content extraction — download a page and pull out clean text
# ---------------------------------------------------------------------------

def _extract_content(url: str) -> list[str]:
    """Download a page and extract meaningful paragraphs.

    Tries trafilatura first (better quality extraction) and falls back
    to BeautifulSoup if trafilatura fails or isn't installed.
    """
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()   # Raises an exception if the HTTP status is 4xx/5xx
    html = resp.text

    # Try trafilatura first (best quality — designed for article extraction)
    paragraphs = _extract_with_trafilatura(html, url)
    if paragraphs:
        return paragraphs

    # Fallback to BeautifulSoup (less precise but always available)
    return _extract_with_bs4(html)


def _extract_with_trafilatura(html: str, url: str) -> list[str]:
    """Use trafilatura to extract the main article text from an HTML page.

    trafilatura is specifically designed to detect and extract the "main"
    content of a web page (the article body), discarding navigation,
    ads, comments, footers, etc.
    """
    if trafilatura is None:
        return []    # Library not installed, skip silently
    try:
        # extract() returns a plain text string or None
        text = trafilatura.extract(html, url=url, include_comments=False,
                                   include_tables=False, favor_recall=True)
        if text:
            return _split_into_paragraphs(text)
    except Exception as exc:
        logger.warning("trafilatura failed: %s", exc)
    return []


def _extract_with_bs4(html: str) -> list[str]:
    """Use BeautifulSoup to parse HTML and extract <p> tag text.

    Strategy:
      1. Remove non-content tags (scripts, styles, navigation, etc.)
      2. Find all <p> (paragraph) tags
      3. Keep only paragraphs longer than 60 characters (filters out short
         labels, button text, and other noise)
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove all tags that are unlikely to contain educational content
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()   # Completely removes the tag and its content from the tree

    paragraphs: list[str] = []
    for p in soup.find_all("p"):
        # get_text() extracts all text inside the tag, joining child elements with a space
        text = p.get_text(separator=" ", strip=True)
        if len(text) > 60:   # Only keep paragraphs that are at least a sentence long
            paragraphs.append(text)
    return paragraphs


# ---------------------------------------------------------------------------
# Filtering & helpers
# ---------------------------------------------------------------------------

def _filter_relevant(paragraphs: list[str], query: str) -> list[str]:
    """Keep only paragraphs that share keywords with the original query.

    Each paragraph is scored by counting how many words from the query
    appear in that paragraph. Higher score = more relevant.

    Returns the top 10 highest-scoring paragraphs.
    """
    # Extract all words from the query that are 3+ characters long
    query_words = set(re.findall(r"[a-zA-Z]{3,}", query.lower()))

    scored: list[tuple[int, str]] = []
    for para in paragraphs:
        para_lower = para.lower()
        # Count how many query words appear in this paragraph
        score = sum(1 for w in query_words if w in para_lower)
        if score > 0:   # Only include paragraphs that match at least one query word
            scored.append((score, para))

    # Sort by score descending (most relevant first)
    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:10]]   # Return just the text, top 10


def _split_into_paragraphs(text: str) -> list[str]:
    """Split a block of text (from trafilatura) into non-trivial paragraphs.

    trafilatura returns a single string with newlines between sections.
    This function splits on newlines and discards very short chunks.
    """
    parts = text.split("\n")
    return [p.strip() for p in parts if len(p.strip()) > 60]
