# ============================================================
#  SUBJECT-SPECIFIC DOUBT RESOLUTION SYSTEM — GUI VERSION
#
#  This is the main file to run for the desktop window version.
#
#  Run:  python app.py
#
#  This single file contains EVERYTHING needed for the GUI:
#    - Database functions (create/read/write SQLite)
#    - Web scraper (search DuckDuckGo, extract text from pages)
#    - AI engine (summarize scraped text, extract keywords)
#    - The GUI window itself (built with tkinter)
#
#  Why is it all in one file?
#    app.py is a self-contained GUI version — it doesn't import from
#    the other modules (scraper.py, ai_engine.py, etc.) to keep it
#    simple and stand-alone. The CLI version (main.py) uses those
#    separate modules instead.
# ============================================================

import tkinter as tk                          # Python's built-in GUI library
from tkinter import ttk, messagebox, scrolledtext  # tkinter sub-modules
import threading    # Allows running tasks in the background without freezing the GUI
import sqlite3      # Built-in database library (no installation needed)
import os           # File path utilities
import re           # Regular expressions for text processing
import requests     # Third-party: downloads web pages
from bs4 import BeautifulSoup  # Third-party: parses HTML to extract text
from collections import Counter   # Counts occurrences of words

# Try importing optional libraries — the app works without them but they
# improve quality. They're wrapped in try/except so a missing library
# doesn't crash the app.
try:
    import trafilatura   # Better text extraction from web pages
except ImportError:
    trafilatura = None   # Will fall back to BeautifulSoup

try:
    from ddgs import DDGS   # DuckDuckGo search (no API key needed)
except ImportError:
    DDGS = None   # Will fall back to Wikipedia URL construction


# ============================================================
#  SETTINGS
#  All configurable values live here at the top — easy to find and change.
# ============================================================

# List of subjects shown in the dropdown. Add/remove subjects here.
SUBJECTS = [
    "Computer Science", "Mathematics", "Physics",
    "Chemistry", "Biology", "Politics",
    "History", "Economics", "Philosophy",
    "General Knowledge",
]

# Instructor login credentials — username: plain-text password
# NOTE: In a real app, passwords should NEVER be stored in plain text.
# For this demo/assignment, plain text is acceptable.
INSTRUCTORS = {
    "admin": "admin123",
    "prof_smith": "teach2024",
    "dr_jones": "phys1cs",
}

# SQLite database file path — stored in the same folder as this script.
# os.path.abspath(__file__) gets the absolute path of THIS file.
# os.path.dirname(...) gets the folder containing this file.
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doubt_system.db")


# ============================================================
#  DATABASE FUNCTIONS
#  All reading and writing to the SQLite database happens here.
#  SQLite stores everything in the single file DB_FILE.
# ============================================================

def create_database():
    """Create the questions table if it doesn't exist yet.

    Called once when the app starts. Uses IF NOT EXISTS so it's safe
    to call every time — won't overwrite existing data.
    """
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            question_id   INTEGER PRIMARY KEY AUTOINCREMENT,  -- Auto-assigned unique ID
            student_name  TEXT NOT NULL,                      -- Who asked
            subject       TEXT NOT NULL,                      -- Which subject
            question_text TEXT NOT NULL,                      -- The question text
            status        TEXT DEFAULT 'Pending',             -- Current state
            ai_answer     TEXT DEFAULT '',                    -- AI-generated answer
            instructor_answer TEXT DEFAULT '',                -- Human-verified answer
            ai_confidence REAL DEFAULT 0.0,                   -- AI confidence 0.0-1.0
            keywords      TEXT DEFAULT '',                    -- Extracted keywords
            topic         TEXT DEFAULT '',                    -- Detected sub-topic
            timestamp     TEXT DEFAULT (datetime('now','localtime'))  -- When posted
        )
    """)
    conn.commit()
    conn.close()


def save_question(name, subject, question):
    """Save a new question to the database and return its auto-assigned ID.

    Uses parameterized queries (?) to prevent SQL injection.
    cursor.lastrowid gives us the ID that SQLite assigned to the new row.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO questions (student_name, subject, question_text) VALUES (?, ?, ?)",
        (name, subject, question)
    )
    question_id = cursor.lastrowid   # The auto-assigned ID
    conn.commit()
    conn.close()
    return question_id


def save_ai_answer(question_id, answer, confidence, keywords, topic):
    """Update a question row with the AI-generated answer.

    Also changes the status from 'Pending' to 'AI Answer Generated'.
    """
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        """UPDATE questions
           SET ai_answer=?, status='AI Answer Generated',
               ai_confidence=?, keywords=?, topic=?
           WHERE question_id=?""",
        (answer, confidence, keywords, topic, question_id)
    )
    conn.commit()
    conn.close()


def save_instructor_answer(question_id, answer):
    """Update a question row with the instructor's verified answer.

    Changes status from whatever it was to 'Instructor Verified' —
    the final, highest-trust state.
    """
    conn = sqlite3.connect(DB_FILE)
    conn.execute(
        "UPDATE questions SET instructor_answer=?, status='Instructor Verified' WHERE question_id=?",
        (answer, question_id)
    )
    conn.commit()
    conn.close()


def get_all_questions():
    """Get all questions from the database as a list of dictionaries.

    row_factory = sqlite3.Row makes rows behave like dicts so we can
    access columns by name (row["student_name"]) instead of index (row[0]).
    dict(row) converts each Row object to a plain Python dictionary.
    Returns newest questions first (ORDER BY id DESC).
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM questions ORDER BY question_id DESC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_question_by_id(question_id):
    """Get a single question by its ID. Returns None if not found."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM questions WHERE question_id=?", (question_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_pending_questions():
    """Get questions that haven't been verified by an instructor yet.

    Returns both Pending and AI-answered questions — any question that
    still needs a human to review it.
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM questions WHERE status != 'Instructor Verified' ORDER BY question_id"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ============================================================
#  WEB SCRAPER
#  Searches the internet for answers to student questions.
#  Steps: search DuckDuckGo → download pages → extract text
# ============================================================

def search_web(query):
    """Search DuckDuckGo and return a list of result URLs.

    Uses the duckduckgo_search library (no API key needed).
    Falls back to a Wikipedia URL if the library is missing or search fails.
    """
    if DDGS is None:
        # Fallback: build Wikipedia URL directly
        slug = query.strip().replace(" ", "_")
        return [f"https://en.wikipedia.org/wiki/{slug}"]
    try:
        ddgs = DDGS()
        results = ddgs.text(query, max_results=5)
        return [r["href"] for r in results if "href" in r]
    except Exception:
        slug = query.strip().replace(" ", "_")
        return [f"https://en.wikipedia.org/wiki/{slug}"]


def extract_text_from_url(url):
    """Download a webpage and extract the main text paragraphs.

    Two strategies (tried in order):
      1. trafilatura — specifically designed to extract article content,
         ignoring ads, menus, sidebars, etc. (best quality)
      2. BeautifulSoup — parses all HTML <p> tags (good fallback)

    Returns a list of paragraph strings (minimum 60 chars each).
    Returns an empty list if anything goes wrong (network error, etc.).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"
    }
    try:
        response = requests.get(url, headers=headers, timeout=12)
        response.raise_for_status()
        html = response.text
    except Exception:
        return []

    # Method 1: use trafilatura (better quality)
    if trafilatura:
        try:
            text = trafilatura.extract(html, include_comments=False)
            if text:
                # Split into paragraphs, keep only meaningful ones
                return [p.strip() for p in text.split("\n") if len(p.strip()) > 60]
        except Exception:
            pass

    # Method 2: use BeautifulSoup (fallback)
    soup = BeautifulSoup(html, "html.parser")
    # Remove unwanted tags
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    paragraphs = []
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ", strip=True)
        if len(text) > 60:
            paragraphs.append(text)
    return paragraphs


def scrape_answer(question, subject=""):
    """Search the web for the question and return relevant paragraph text.

    Steps:
      1. Search DuckDuckGo for "{subject} {question}"
      2. Visit up to 5 result URLs and extract text from each
      3. Score each paragraph by how many question words it contains
      4. Return top 10 most relevant paragraphs + the source URLs

    Returns: (paragraphs_list, sources_list)
      Both are empty lists if nothing was found.
    """
    search_query = f"{subject} {question}" if subject else question
    urls = search_web(search_query)

    all_paragraphs = []
    sources = []

    for url in urls[:5]:
        paragraphs = extract_text_from_url(url)
        if paragraphs:
            all_paragraphs.extend(paragraphs)
            sources.append(url)

    if not all_paragraphs:
        return [], []

    # Filter: keep paragraphs that mention words from the question
    question_words = set(re.findall(r"[a-zA-Z]{3,}", question.lower()))
    scored = []
    for para in all_paragraphs:
        score = sum(1 for w in question_words if w in para.lower())
        if score > 0:
            scored.append((score, para))
    scored.sort(key=lambda x: x[0], reverse=True)

    best = [text for _, text in scored[:10]] if scored else all_paragraphs[:10]
    return best, sources


# ============================================================
#  AI ENGINE
#  Turns raw scraped paragraphs into a clean, readable answer.
#  Works completely offline — no API key needed.
# ============================================================

def summarize_paragraphs(paragraphs, question):
    """Pick the most relevant sentences from scraped text (extractive summarization).

    This is the core of the AI engine. It does NOT call any external AI API.
    Instead, it uses a scoring algorithm:

    For each sentence in the scraped paragraphs:
      - Count how many words from the question appear in the sentence
      - Score = overlap / total_question_words
      - Bonus +0.1 if the sentence is longer than 100 characters (more informative)

    Then select the top-scoring sentences up to ~1500 total characters.

    This approach is called "extractive summarization" — we select the best
    existing sentences rather than generating new text from scratch.
    """
    # Words from the question (ignoring small common words)
    stop_words = {
        "the", "and", "for", "that", "this", "with", "from", "are",
        "was", "were", "has", "have", "been", "will", "can", "not",
        "but", "its", "also", "more", "such", "than", "what",
    }
    question_words = set(re.findall(r"[a-zA-Z]{3,}", question.lower())) - stop_words

    # Break paragraphs into individual sentences and score each one
    sentences = []
    for para in paragraphs:
        for sent in re.split(r'(?<=[.!?])\s+', para):
            sent = sent.strip()
            if len(sent) < 40:
                continue
            words = set(re.findall(r"[a-zA-Z]{3,}", sent.lower())) - stop_words
            overlap = len(question_words & words)
            score = overlap / max(len(question_words), 1)
            if len(sent) > 100:
                score += 0.1  # bonus for longer informative sentences
            sentences.append((score, sent))

    # Sort by relevance score (highest first)
    sentences.sort(key=lambda x: x[0], reverse=True)

    # Pick top sentences up to ~1500 characters
    selected = []
    total = 0
    for _, sent in sentences:
        if total + len(sent) > 1500:
            break
        selected.append(sent)
        total += len(sent)

    return " ".join(selected)


def extract_keywords(text):
    """Find the 8 most common meaningful words in the text.

    Filters out stop words (very common short words like "the", "and", etc.)
    that appear in every sentence and don't carry unique meaning.
    Counter().most_common(8) returns the 8 words with the highest count.
    """
    stop = {
        "this", "that", "with", "from", "what", "which", "where", "when",
        "were", "been", "have", "does", "will", "would", "could", "should",
        "about", "their", "there", "these", "those", "also", "more", "some",
        "than", "other", "into", "very", "just", "your", "they", "them",
    }
    words = re.findall(r"[a-zA-Z]{4,}", text.lower())
    words = [w for w in words if w not in stop]
    common = Counter(words).most_common(8)
    return ", ".join(word for word, _ in common)


def classify_topic(question, subject):
    """Guess the specific sub-topic from keywords in the question.

    Uses a simple rule-based lookup table:
      if "calculus" is in the question → return "Calculus"
      if "python" is in the question  → return "Python Programming"
      ...and so on.

    Falls back to the subject name if no keyword matches.
    This is purely local — no ML model needed.
    """
    q = question.lower()
    topics = {
        "algorithm": "Algorithms", "python": "Python Programming",
        "java": "Java Programming", "machine learning": "Machine Learning",
        "calculus": "Calculus", "matrix": "Linear Algebra",
        "quantum": "Quantum Physics", "newton": "Classical Mechanics",
        "election": "Political Science", "democracy": "Political Science",
        "evolution": "Biology", "chemical": "Chemistry",
        "economy": "Economics", "history": "History",
    }
    for keyword, topic in topics.items():
        if keyword in q:
            return topic
    return subject if subject else "General"


def compute_confidence(paragraphs, answer):
    """Give a simple confidence score (0.0 – 1.0) based on content richness.

    The more paragraphs we found (more sources) and the longer the answer,
    the higher the confidence. This is a heuristic (educated guess) — not
    a statistically rigorous measure.

    Shown as a percentage in the UI (e.g., 0.8 → 80%).
    """
    score = 0.5
    if len(paragraphs) >= 3:
        score += 0.1
    if len(paragraphs) >= 5:
        score += 0.1
    if len(answer) > 200:
        score += 0.1
    if len(answer) > 500:
        score += 0.1
    return min(score, 1.0)


def generate_answer(question, subject):
    """Main pipeline: scrape the web → summarize → return an answer dict.

    Steps:
      1. Call scrape_answer() to get relevant paragraphs from the web
      2. Call summarize_paragraphs() to pick the best sentences
      3. Append source URLs to the answer text
      4. Extract keywords and classify the topic
      5. Compute a confidence score

    Returns a dictionary with keys:
      answer     - the final answer text
      confidence - float 0.0–1.0
      keywords   - comma-separated key terms
      topic      - detected sub-topic label
      sources    - list of URLs used
      success    - True if an answer was generated
      error      - error message if success is False
    """
    result = {
        "answer": "", "confidence": 0.0,
        "keywords": "", "topic": "",
        "sources": [], "success": False, "error": "",
    }

    # Step 1: Scrape the web
    paragraphs, sources = scrape_answer(question, subject)
    if not paragraphs:
        result["error"] = "Could not find relevant content on the web."
        return result

    result["sources"] = sources

    # Step 2: Summarize into an answer
    summary = summarize_paragraphs(paragraphs, question)
    if not summary:
        result["error"] = "Could not generate a summary."
        return result

    # Step 3: Add source references
    answer_text = summary
    if sources:
        answer_text += "\n\n--- Sources ---"
        for i, url in enumerate(sources, 1):
            answer_text += f"\n[{i}] {url}"

    # Step 4: Extract keywords and classify topic
    result["answer"] = answer_text
    result["keywords"] = extract_keywords(question + " " + " ".join(paragraphs[:3])[:500])
    result["topic"] = classify_topic(question, subject)
    result["confidence"] = compute_confidence(paragraphs, summary)
    result["success"] = True
    return result


# ============================================================
#  GUI — The main desktop window
#
#  Built with tkinter — Python's built-in GUI library.
#  The window has 3 tabs (called "notebook" in tkinter terminology):
#    Tab 1: Student Portal  — post questions
#    Tab 2: View Questions  — browse all Q&A
#    Tab 3: Instructor      — login and post verified answers
#
#  COLOUR SCHEME (dark theme):
# ============================================================

# Colour constants — used throughout all widgets for consistency
BG       = "#1e1e2e"     # Dark navy — main window background
CARD     = "#2a2a3d"     # Slightly lighter — form/card areas
ENTRY_BG = "#33334d"     # Input field background
FG       = "#e0e0e0"     # Light grey — normal text
GREEN    = "#22c55e"     # Success (verified answers, submit buttons)
ORANGE   = "#f59e0b"     # Warning / in-progress (pending status)
RED      = "#ef4444"     # Error / danger (logout, error messages)
BLUE     = "#3b82f6"     # Info / neutral (refresh buttons)
PURPLE   = "#7c3aed"     # Primary accent (main action buttons, selected tab)
WHITE    = "#ffffff"


def set_text(widget, text):
    """Helper: replace all text in a read-only ScrolledText widget.

    ScrolledText widgets are set to state=DISABLED to prevent the user
    from typing in them. To programmatically update their content we must
    temporarily re-enable them, update the text, then disable again.
    """
    widget.config(state=tk.NORMAL)
    widget.delete("1.0", tk.END)
    widget.insert(tk.END, text)
    widget.config(state=tk.DISABLED)


# ---- Build the main window ----
# root is the top-level tkinter window. All other widgets are children of it.
root = tk.Tk()
root.title("Doubt Resolution System")
root.geometry("950x680")    # Initial window size: 950px wide × 680px tall
root.configure(bg=BG)
root.minsize(800, 550)       # Prevent the user from making the window too small

# Create the database tables on startup (safe to call every time)
create_database()

# Configure the visual style using ttk.Style
# "clam" is a built-in theme that allows more colour customization
style = ttk.Style(root)
style.theme_use("clam")
style.configure("TNotebook", background=BG, borderwidth=0)
style.configure("TNotebook.Tab", background=CARD, foreground=FG,
                padding=[16, 7], font=("Segoe UI", 11, "bold"))
# Change tab appearance when selected (active tab is purple)
style.map("TNotebook.Tab",
          background=[("selected", PURPLE)], foreground=[("selected", WHITE)])
style.configure("TFrame", background=BG)
style.configure("Card.TFrame", background=CARD)
style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 10))

# ---- App header bar (shown above the tabs) ----
header = tk.Frame(root, bg=BG)
header.pack(fill=tk.X, padx=20, pady=(12, 4))
tk.Label(header, text="Doubt Resolution System", font=("Segoe UI", 17, "bold"),
         bg=BG, fg=WHITE).pack(side=tk.LEFT)
tk.Label(header, text="AI-Powered Academic Q&A", font=("Segoe UI", 10),
         bg=BG, fg="#aaa").pack(side=tk.LEFT, padx=15)

# ---- Notebook (tabbed container) ----
# Each tab is a ttk.Frame added to the notebook with notebook.add(...)
notebook = ttk.Notebook(root)
notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)


# ============================================================
#  TAB 1  –  STUDENT PORTAL
#  Allows any student to type a question and immediately get
#  an AI-generated answer.  The question is also stored in
#  the database so instructors can review and verify it later.
# ============================================================

# Create the tab frame and register it with the notebook
student_tab = ttk.Frame(notebook)
notebook.add(student_tab, text="  Student Portal  ")

# Card frame: a slightly lighter panel that holds all the input widgets
card1 = tk.Frame(student_tab, bg=CARD)
card1.pack(padx=25, pady=15, fill=tk.BOTH, expand=True)

# Title label spanning both columns of the grid layout
tk.Label(card1, text="Post a New Question", font=("Segoe UI", 13, "bold"),
         bg=CARD, fg=WHITE).grid(row=0, column=0, columnspan=2, pady=(12, 15))

# ── Row 1: Student name input ──
tk.Label(card1, text="Your Name:", bg=CARD, fg=FG, font=("Segoe UI", 10)
         ).grid(row=1, column=0, sticky="e", padx=(15, 8), pady=6)
# Plain text entry, insertbackground sets the cursor colour
name_entry = tk.Entry(card1, width=38, font=("Segoe UI", 10),
                      bg=ENTRY_BG, fg=FG, insertbackground=FG, relief="flat", bd=4)
name_entry.grid(row=1, column=1, padx=(0, 15), pady=6, sticky="w")

# ── Row 2: Subject dropdown ──
tk.Label(card1, text="Subject:", bg=CARD, fg=FG, font=("Segoe UI", 10)
         ).grid(row=2, column=0, sticky="e", padx=(15, 8), pady=6)
# Combobox with state="readonly" so students can only pick from the list
subject_combo = ttk.Combobox(card1, values=SUBJECTS, state="readonly",
                              width=35, font=("Segoe UI", 10))
subject_combo.grid(row=2, column=1, padx=(0, 15), pady=6, sticky="w")
subject_combo.current(0)    # Select the first subject by default

# ── Row 3: Multi-line question input ──
tk.Label(card1, text="Question:", bg=CARD, fg=FG, font=("Segoe UI", 10)
         ).grid(row=3, column=0, sticky="ne", padx=(15, 8), pady=6)
# tk.Text supports multi-line input; height=3 means 3 visible lines
question_text = tk.Text(card1, width=48, height=3, font=("Segoe UI", 10),
                        bg=ENTRY_BG, fg=FG, insertbackground=FG,
                        relief="flat", bd=4, wrap="word")
question_text.grid(row=3, column=1, padx=(0, 15), pady=6, sticky="w")

# ── Row 5: Status message (updated dynamically during answer generation) ──
status_label = tk.Label(card1, text="", bg=CARD, fg=ORANGE, font=("Segoe UI", 9))
status_label.grid(row=5, column=0, columnspan=2, pady=(0, 3))

# ── Row 6–7: Read-only AI answer display ──
tk.Label(card1, text="AI Answer:", bg=CARD, fg=GREEN,
         font=("Segoe UI", 11, "bold")).grid(row=6, column=0, columnspan=2,
                                              padx=15, sticky="w")
# ScrolledText includes a scrollbar; state="disabled" prevents the user from
# typing into it (we update it programmatically with set_text())
answer_box = scrolledtext.ScrolledText(card1, width=78, height=9,
                                        font=("Consolas", 10), bg="#1a1a2e",
                                        fg="#d4d4ff", relief="flat", bd=4,
                                        wrap="word", state="disabled")
answer_box.grid(row=7, column=0, columnspan=2, padx=15, pady=(3, 12), sticky="nsew")

# Allow column 1 and row 7 to expand when the window is resized
card1.grid_columnconfigure(1, weight=1)
card1.grid_rowconfigure(7, weight=1)


def post_question():
    """
    Called when the student clicks 'Post Question'.

    Flow:
      1. Validate inputs (name, subject, question must all be filled).
      2. Save the question to the SQLite database immediately (so it's recorded
         even if AI generation later fails).
      3. Disable the button and show a status message so the user knows
         something is happening.
      4. Spawn a BACKGROUND THREAD to run the slow web-scrape + AI steps.
         --- WHY A THREAD? ---
         tkinter runs on a single thread. If we called generate_answer()
         directly here, the entire window would freeze/hang until it returned.
         By running do_work() in a daemon thread, the GUI stays responsive.
      5. Inside do_work(), use root.after(0, lambda: ...) to safely schedule
         GUI updates back on the main thread — tkinter is NOT thread-safe,
         so you must NEVER update widgets directly from a background thread.
    """
    name = name_entry.get().strip()
    subject = subject_combo.get().strip()
    question = question_text.get("1.0", tk.END).strip()

    if not name or not subject or not question:
        messagebox.showwarning("Input Error", "Please fill all fields.")
        return

    # Step 1: Persist the question first (so it's not lost if AI fails)
    qid = save_question(name, subject, question)

    # Step 2: Disable the button while work is in progress
    post_btn.config(state="disabled", text="Generating AI Answer...")
    status_label.config(text=f"Question #{qid} saved. Generating answer...", fg=ORANGE)
    set_text(answer_box, "")

    def do_work():
        """Runs in a background thread — never update widgets directly from here."""
        try:
            # generate_answer() scrapes the web and summarises results
            result = generate_answer(question, subject)
            if result["success"]:
                # Persist the AI answer alongside the question
                save_ai_answer(qid, result["answer"], result["confidence"],
                               result["keywords"], result["topic"])
                display = (
                    f"AI Answer  (Confidence: {result['confidence']:.0%})\n"
                    f"{'=' * 55}\n\n"
                    f"{result['answer']}\n\n"
                    f"{'=' * 55}\n"
                    f"Keywords : {result['keywords']}\n"
                    f"Topic    : {result['topic']}\n"
                )
                # root.after(0, ...) queues the lambda on the GUI thread safely
                root.after(0, lambda: set_text(answer_box, display))
                root.after(0, lambda: status_label.config(
                    text=f"Question #{qid} — AI answer generated!", fg=GREEN))
            else:
                # AI failed: show the error and inform the user an instructor can help
                root.after(0, lambda: set_text(
                    answer_box, f"Could not generate answer:\n{result['error']}\n\n"
                    f"Question saved (ID: {qid}). An instructor can answer later."
                ))
                root.after(0, lambda: status_label.config(
                    text=f"Question #{qid} saved, awaiting instructor.", fg=ORANGE))
        except Exception as e:
            root.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            # Always re-enable the button when done, regardless of success/failure
            root.after(0, lambda: post_btn.config(state="normal", text="Post Question"))

    # daemon=True means the thread is killed when the main program exits
    threading.Thread(target=do_work, daemon=True).start()
    # Clear the question box immediately after spawning the thread
    question_text.delete("1.0", tk.END)


# ── Row 4: Submit button (placed after the function so it can reference it) ──
post_btn = tk.Button(card1, text="Post Question", font=("Segoe UI", 11, "bold"),
                     bg=PURPLE, fg=WHITE, activebackground="#9b59f0",
                     relief="flat", bd=0, padx=18, pady=7, cursor="hand2",
                     command=post_question)
post_btn.grid(row=4, column=1, pady=(8, 3), sticky="w")


# ============================================================
#  TAB 2  –  VIEW ALL QUESTIONS
#  A read-only view of every question in the database.
#  Students and instructors can browse and filter questions
#  and click any row to see the full detail below the table.
# ============================================================

# Create and register the tab
viewer_tab = ttk.Frame(notebook)
notebook.add(viewer_tab, text="  View Questions  ")

# ── Top bar: title + filter + refresh button ──
top_bar = tk.Frame(viewer_tab, bg=BG)
top_bar.pack(fill=tk.X, padx=18, pady=(12, 4))
tk.Label(top_bar, text="All Questions", font=("Segoe UI", 13, "bold"),
         bg=BG, fg=WHITE).pack(side=tk.LEFT)

# Filter dropdown: narrows the table to a specific status category
tk.Label(top_bar, text="Filter:", bg=BG, fg=FG, font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(20, 5))
filter_combo = ttk.Combobox(top_bar, state="readonly", width=18,
                             values=["All", "Pending", "AI Answer Generated", "Instructor Verified"])
filter_combo.current(0)    # Default: show all questions
filter_combo.pack(side=tk.LEFT)

# ── Question table (Treeview widget) ──
tree_frame = tk.Frame(viewer_tab, bg=BG)
tree_frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=4)

# columns defines the column identifiers and their display labels
columns = ("ID", "Student", "Subject", "Question", "Status")
# show="headings" hides the default empty first column
q_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=7)
# Set the heading text and pixel width for each column
for col, width in zip(columns, [40, 100, 110, 320, 140]):
    q_tree.heading(col, text=col)
    q_tree.column(col, width=width, minwidth=40)

# Attach a vertical scrollbar — yscrollcommand links the bar to the table
scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=q_tree.yview)
q_tree.configure(yscrollcommand=scrollbar.set)
q_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

# ── Detail area: shows the full record when a row is clicked ──
tk.Label(viewer_tab, text="Question Detail", font=("Segoe UI", 11, "bold"),
         bg=BG, fg=WHITE).pack(padx=18, pady=(8, 2), anchor="w")

detail_box = scrolledtext.ScrolledText(viewer_tab, width=95, height=10,
                                        font=("Consolas", 10), bg="#1a1a2e",
                                        fg="#d4d4ff", relief="flat", bd=4,
                                        wrap="word", state="disabled")
detail_box.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))


def refresh_viewer():
    """
    Reload the question table from the database.

    Called on startup and whenever the user clicks 'Refresh' or changes
    the filter dropdown.  Clears all existing rows, fetches questions from
    SQLite, applies the active filter, and inserts fresh rows.
    The iid=str(q["id"]) trick lets us look up the row's DB id later
    directly from the Treeview selection (sel[0]).
    """
    # Remove all existing rows before re-inserting
    for row in q_tree.get_children():
        q_tree.delete(row)

    questions = get_all_questions()
    filt = filter_combo.get()
    # Apply filter unless "All" is selected
    if filt != "All":
        questions = [q for q in questions if q["status"] == filt]

    for q in questions:
        # iid is the Treeview row identifier; we use the DB id so on_select_question
        # can call get_question_by_id(int(sel[0])) directly
        q_tree.insert("", tk.END, iid=str(q["question_id"]),
                      values=(q["question_id"], q["student_name"], q["subject"],
                              q["question_text"][:55], q["status"]))


def on_select_question(event):
    """
    Triggered by <<TreeviewSelect>> when the user clicks a row.

    Fetches the full question record from the database (the table only
    shows a truncated preview) and renders it in the detail_box below.
    """
    sel = q_tree.selection()   # Returns a tuple of selected row iids
    if not sel:
        return
    # sel[0] is the iid string we set above (== the DB id as a string)
    q = get_question_by_id(int(sel[0]))
    if not q:
        return

    # Build the formatted display string line-by-line
    lines = [
        f"  Question #{q['question_id']}",
        f"  {'=' * 50}",
        f"  Student  : {q['student_name']}",
        f"  Subject  : {q['subject']}",
        f"  Status   : {q['status']}",
        f"  Posted   : {q['timestamp']}",
    ]
    if q["keywords"]:
        lines.append(f"  Keywords : {q['keywords']}")
    if q["topic"]:
        lines.append(f"  Topic    : {q['topic']}")

    lines.append(f"\n  Question:\n  {q['question_text']}")
    lines.append(f"\n  {'─' * 50}")

    # Show AI answer if one exists
    if q["ai_answer"]:
        conf = f" (Confidence: {q['ai_confidence']:.0%})" if q["ai_confidence"] else ""
        lines.append(f"  AI Answer{conf}:")
        lines.append(f"  {q['ai_answer']}")
    else:
        lines.append("  AI Answer: (not yet generated)")

    lines.append(f"\n  {'─' * 50}")
    # Show instructor answer if one exists
    if q["instructor_answer"]:
        lines.append(f"  Instructor Answer (VERIFIED):")
        lines.append(f"  {q['instructor_answer']}")
    else:
        lines.append("  Instructor Answer: (awaiting review)")

    set_text(detail_box, "\n".join(lines))


# Bind the selection event to our handler
q_tree.bind("<<TreeviewSelect>>", on_select_question)
# Re-run refresh whenever the filter dropdown value changes
filter_combo.bind("<<ComboboxSelected>>", lambda e: refresh_viewer())

# Refresh button in the top bar (placed last so it appears on the right)
tk.Button(top_bar, text="Refresh", font=("Segoe UI", 10),
          bg=BLUE, fg=WHITE, relief="flat", padx=10, pady=3,
          cursor="hand2", command=refresh_viewer).pack(side=tk.RIGHT)


# ============================================================
#  TAB 3  –  INSTRUCTOR PANEL
#  Protected area for teaching staff to review AI-generated
#  answers and post verified corrections or improvements.
#
#  Layout: the tab contains TWO frames stacked in the same space:
#    • login_frame  — shown by default, hidden after a successful login
#    • dashboard    — hidden initially, shown after login
#  Switching between them is done with pack_forget() / pack().
# ============================================================

# Create and register the tab
instructor_tab = ttk.Frame(notebook)
notebook.add(instructor_tab, text="  Instructor  ")

# ── Login screen ──
# A centred card with username/password fields
login_frame = tk.Frame(instructor_tab, bg=CARD)
login_frame.pack(padx=30, pady=30)

tk.Label(login_frame, text="Instructor Login", font=("Segoe UI", 13, "bold"),
         bg=CARD, fg=WHITE).grid(row=0, column=0, columnspan=2, pady=(12, 15))

# Username field
tk.Label(login_frame, text="Username:", bg=CARD, fg=FG, font=("Segoe UI", 10)
         ).grid(row=1, column=0, sticky="e", padx=(15, 8), pady=6)
user_entry = tk.Entry(login_frame, width=22, font=("Segoe UI", 10),
                      bg=ENTRY_BG, fg=FG, insertbackground=FG, relief="flat", bd=4)
user_entry.grid(row=1, column=1, padx=(0, 15), pady=6)

# Password field — show="*" masks each character as an asterisk
tk.Label(login_frame, text="Password:", bg=CARD, fg=FG, font=("Segoe UI", 10)
         ).grid(row=2, column=0, sticky="e", padx=(15, 8), pady=6)
pass_entry = tk.Entry(login_frame, width=22, show="*", font=("Segoe UI", 10),
                      bg=ENTRY_BG, fg=FG, insertbackground=FG, relief="flat", bd=4)
pass_entry.grid(row=2, column=1, padx=(0, 15), pady=6)

# Hint label showing the demo credentials (in a real system, remove this!)
tk.Label(login_frame, text="Accounts:  admin/admin123  |  prof_smith/teach2024",
         bg=CARD, fg="#888", font=("Segoe UI", 8)
         ).grid(row=4, column=0, columnspan=2, pady=(0, 12))

# ── Dashboard (hidden until a successful login) ──
dashboard = tk.Frame(instructor_tab, bg=BG)

# Dashboard top bar: welcome message + Refresh + Logout buttons
dash_top = tk.Frame(dashboard, bg=BG)
dash_top.pack(fill=tk.X, padx=18, pady=(8, 4))
welcome_label = tk.Label(dash_top, text="", font=("Segoe UI", 12, "bold"),
                         bg=BG, fg=WHITE)
welcome_label.pack(side=tk.LEFT)

# ── Pending questions list (Treeview) ──
inst_tree_frame = tk.Frame(dashboard, bg=BG)
inst_tree_frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=4)

inst_columns = ("ID", "Student", "Subject", "Question", "Status")
inst_tree = ttk.Treeview(inst_tree_frame, columns=inst_columns,
                          show="headings", height=5)
for col, w in zip(inst_columns, [40, 90, 100, 300, 130]):
    inst_tree.heading(col, text=col)
    inst_tree.column(col, width=w, minwidth=40)
inst_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

# ── Bottom card: question detail + answer input ──
inst_bottom = tk.Frame(dashboard, bg=CARD)
inst_bottom.pack(fill=tk.BOTH, expand=True, padx=18, pady=(4, 12))

# Read-only box showing the selected question and its AI answer
tk.Label(inst_bottom, text="Question & AI Answer:", bg=CARD, fg=WHITE,
         font=("Segoe UI", 11, "bold")).pack(padx=12, pady=(8, 3), anchor="w")

inst_detail = scrolledtext.ScrolledText(inst_bottom, width=88, height=6,
                                         font=("Consolas", 10), bg="#1a1a2e",
                                         fg="#d4d4ff", relief="flat", bd=4,
                                         wrap="word", state="disabled")
inst_detail.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 4))

# Editable text box where the instructor types their verified answer
tk.Label(inst_bottom, text="Your Verified Answer:", bg=CARD, fg=GREEN,
         font=("Segoe UI", 11, "bold")).pack(padx=12, anchor="w")

inst_answer_text = tk.Text(inst_bottom, width=88, height=3, font=("Segoe UI", 10),
                            bg=ENTRY_BG, fg=FG, insertbackground=FG,
                            relief="flat", bd=4, wrap="word")
inst_answer_text.pack(fill=tk.X, padx=12, pady=4)

# Module-level variable: tracks which question is currently selected
# so submit_instructor_answer() knows which DB row to update
selected_qid = None


def refresh_instructor():
    """
    Reload the pending questions list from the database.

    Only questions that still need instructor review are shown
    (i.e., those returned by get_pending_questions() — status is
    'Pending' or 'AI Answer Generated', not yet 'Instructor Verified').
    """
    for row in inst_tree.get_children():
        inst_tree.delete(row)
    for q in get_pending_questions():
        inst_tree.insert("", tk.END, iid=str(q["question_id"]),
                         values=(q["question_id"], q["student_name"], q["subject"],
                                 q["question_text"][:50], q["status"]))


def on_inst_select(event):
    """
    Triggered when an instructor clicks a row in the pending questions table.

    Loads the full question record and displays it in inst_detail so the
    instructor can read the question and the existing AI answer before
    typing their own verified answer.
    """
    global selected_qid
    sel = inst_tree.selection()
    if not sel:
        return
    # Remember which question is selected (used by submit_instructor_answer)
    selected_qid = int(sel[0])
    q = get_question_by_id(selected_qid)
    if not q:
        return

    lines = [
        f"  Q#{q['question_id']}  [{q['subject']}]  by {q['student_name']}",
        f"  Status: {q['status']}  |  {q['timestamp']}",
        f"  {'─' * 50}",
        f"  Question: {q['question_text']}",
        f"  {'─' * 50}",
    ]
    if q["ai_answer"]:
        lines.append(f"  AI Answer (Confidence: {q['ai_confidence']:.0%}):")
        lines.append(f"  {q['ai_answer']}")
    else:
        lines.append("  AI Answer: (not generated)")

    # If an instructor answer already exists, show it so they can see it
    if q["instructor_answer"]:
        lines.append(f"\n  Existing Instructor Answer:\n  {q['instructor_answer']}")

    set_text(inst_detail, "\n".join(lines))


# Bind row click to the detail handler
inst_tree.bind("<<TreeviewSelect>>", on_inst_select)


def submit_instructor_answer():
    """
    Save the instructor's typed answer to the database for the selected question.

    Guards:
      - selected_qid must not be None (a row must be clicked first)
      - The text box must not be empty

    After saving, clears the text box, resets selected_qid, and refreshes
    the pending list (the answered question will disappear from the list
    once its status changes to 'Instructor Verified').
    """
    global selected_qid
    if selected_qid is None:
        messagebox.showwarning("Select Question", "Click a question from the list first.")
        return

    answer = inst_answer_text.get("1.0", tk.END).strip()
    if not answer:
        messagebox.showwarning("Empty", "Please type your answer.")
        return

    # Persist the answer and update the question status to 'Instructor Verified'
    save_instructor_answer(selected_qid, answer)
    messagebox.showinfo("Success", f"Verified answer saved for Q#{selected_qid}!")
    inst_answer_text.delete("1.0", tk.END)
    selected_qid = None
    refresh_instructor()


# Submit button placed at the bottom of the instructor card
tk.Button(inst_bottom, text="Submit Verified Answer", font=("Segoe UI", 11, "bold"),
          bg=GREEN, fg=WHITE, relief="flat", padx=14, pady=5,
          cursor="hand2", command=submit_instructor_answer).pack(padx=12, pady=(0, 10), anchor="w")

# Tracks who is currently logged in (None = not logged in)
logged_in_user = None


def do_login():
    """
    Validate credentials and switch from the login screen to the dashboard.

    Credentials are stored in the INSTRUCTORS dict at the top of the file.
    In this demo the passwords are stored in plain text; in a production
    system they should be hashed (see instructor_panel.py for the SHA-256
    approach used in the CLI version).
    """
    global logged_in_user
    username = user_entry.get().strip()
    password = pass_entry.get().strip()

    if not username or not password:
        messagebox.showwarning("Login", "Please enter both fields.")
        return

    # Username must exist AND the password must match exactly
    if username not in INSTRUCTORS or INSTRUCTORS[username] != password:
        messagebox.showerror("Login Failed", "Invalid username or password.")
        return

    logged_in_user = username
    login_frame.pack_forget()                      # Hide the login card
    dashboard.pack(fill=tk.BOTH, expand=True)      # Show the dashboard
    welcome_label.config(text=f"Welcome, {username}")
    refresh_instructor()   # Load pending questions immediately after login


def do_logout():
    """
    Log out: hide the dashboard and show the login screen again.
    Clears the credential fields and resets the logged_in_user variable.
    """
    global logged_in_user
    logged_in_user = None
    dashboard.pack_forget()
    login_frame.pack(padx=30, pady=30)
    user_entry.delete(0, tk.END)
    pass_entry.delete(0, tk.END)


# Login button on the login card (row 3 of the grid)
tk.Button(login_frame, text="Login", font=("Segoe UI", 11, "bold"),
          bg=GREEN, fg=WHITE, relief="flat", padx=16, pady=5,
          cursor="hand2", command=do_login
          ).grid(row=3, column=0, columnspan=2, pady=(8, 3))

# Refresh and Logout buttons in the dashboard top bar (right-aligned)
tk.Button(dash_top, text="Refresh", font=("Segoe UI", 9),
          bg=BLUE, fg=WHITE, relief="flat", padx=8, pady=2,
          command=refresh_instructor).pack(side=tk.RIGHT, padx=(4, 0))
tk.Button(dash_top, text="Logout", font=("Segoe UI", 9),
          bg=RED, fg=WHITE, relief="flat", padx=8, pady=2,
          command=do_logout).pack(side=tk.RIGHT)


# ============================================================
#  START THE APP
# ============================================================

# Pre-populate the View Questions tab so the table isn't empty on first open
refresh_viewer()

# root.mainloop() hands control to tkinter's event loop.
# It blocks here and processes all window events (button clicks, key presses,
# redraws, timer callbacks from root.after(), etc.) until the user closes
# the window.  When the window is closed, mainloop() returns and the script ends.
root.mainloop()