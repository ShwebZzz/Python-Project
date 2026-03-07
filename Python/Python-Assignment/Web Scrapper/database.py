"""
database.py
-----------
SQLite database layer for the Doubt Resolution System.
Handles all CRUD operations for students, questions, and answers.

WHAT IS SQLITE?
SQLite is a lightweight database that stores everything in a single file
(doubt_system.db) right next to this script. No separate database server
is needed — Python's built-in sqlite3 module handles everything.

HOW THIS FILE FITS IN:
  - main.py / app.py call initialize_database() on startup
  - student_portal.py / app.py call insert_question(), update_ai_answer()
  - instructor_panel.py / app.py call update_instructor_answer()
  - All read operations (get_all_questions, etc.) are called by the portal files
"""

import sqlite3
import os
from models import Question, QuestionStatus

# Build an absolute path to the database file so it always sits in the
# same folder as this script, regardless of where you launch Python from.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doubt_system.db")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    """Return a connection to the SQLite database.

    row_factory = sqlite3.Row makes each returned row behave like a
    dictionary (row["column_name"]) instead of a plain tuple (row[0]).

    PRAGMA foreign_keys = ON enforces referential integrity so the
    'answers' table can't reference a non-existent question_id.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row        # Access columns by name, not index
    conn.execute("PRAGMA foreign_keys = ON")  # Enforce FK constraints
    return conn


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def initialize_database():
    """Create all required tables if they do not exist.

    This is safe to call every time the app starts — IF NOT EXISTS means
    it won't wipe existing data or throw an error on repeat runs.

    Tables:
      students   — keeps a record of every unique student name
      questions  — one row per question posted; stores everything about it
      answers    — append-only log of every answer ever written (AI or human)
    """
    conn = get_connection()
    cursor = conn.cursor()

    # students table: just a registry of names for future features
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT    NOT NULL,
            created_at   TEXT    DEFAULT (datetime('now','localtime'))
        )
    """)

    # questions table: the main table — one row per question
    # DEFAULT values mean you only need to INSERT the required fields;
    # the rest fill themselves in automatically.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            question_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name     TEXT    NOT NULL,
            subject          TEXT    NOT NULL,
            question_text    TEXT    NOT NULL,
            status           TEXT    NOT NULL DEFAULT 'Pending',
            ai_answer        TEXT    DEFAULT '',
            instructor_answer TEXT   DEFAULT '',
            ai_confidence    REAL    DEFAULT 0.0,
            keywords         TEXT    DEFAULT '',
            topic            TEXT    DEFAULT '',
            timestamp        TEXT    DEFAULT (datetime('now','localtime'))
        )
    """)

    # answers table: an audit log — every time anyone answers a question,
    # a new row is appended here. The FOREIGN KEY ensures the question_id
    # always points to a real question.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            answer_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id  INTEGER NOT NULL,
            answer_type  TEXT    NOT NULL,   -- 'AI' or 'Instructor'
            answer_text  TEXT    NOT NULL,
            answered_by  TEXT    DEFAULT '',
            created_at   TEXT    DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (question_id) REFERENCES questions(question_id)
        )
    """)

    conn.commit()   # Write all changes to disk
    conn.close()    # Release the database file


# ---------------------------------------------------------------------------
# Question CRUD
# ---------------------------------------------------------------------------

def insert_question(student_name: str, subject: str, question_text: str) -> int:
    """Insert a new question and return its auto-generated ID.

    Uses parameterized queries (? placeholders) instead of string
    formatting to prevent SQL injection attacks.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO questions (student_name, subject, question_text, status)
           VALUES (?, ?, ?, ?)""",
        (student_name, subject, question_text, QuestionStatus.PENDING.value),
    )
    question_id = cursor.lastrowid  # The ID SQLite assigned to the new row
    conn.commit()
    conn.close()

    # Also register student if not seen before (best-effort, non-critical)
    _register_student(student_name)
    return question_id


def update_ai_answer(question_id: int, ai_answer: str, confidence: float,
                     keywords: str, topic: str):
    """Store the AI-generated answer for a question.

    Updates two places:
      1. The questions row — sets the answer text and bumps status to AI_ANSWERED
      2. The answers log — appends a record so we have a full history
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Update the main questions row
    cursor.execute(
        """UPDATE questions
           SET ai_answer = ?, status = ?, ai_confidence = ?, keywords = ?, topic = ?
           WHERE question_id = ?""",
        (ai_answer, QuestionStatus.AI_ANSWERED.value, confidence, keywords, topic, question_id),
    )

    # Append to the audit log
    cursor.execute(
        """INSERT INTO answers (question_id, answer_type, answer_text, answered_by)
           VALUES (?, 'AI', ?, 'System')""",
        (question_id, ai_answer),
    )
    conn.commit()
    conn.close()


def update_instructor_answer(question_id: int, answer_text: str, instructor_name: str = "Instructor"):
    """Store the instructor-verified answer.

    Sets status to INSTRUCTOR_VERIFIED — the highest-trust state.
    Also appends to the answers audit log with the instructor's name.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Bump status to final state and store the answer
    cursor.execute(
        """UPDATE questions
           SET instructor_answer = ?, status = ?
           WHERE question_id = ?""",
        (answer_text, QuestionStatus.INSTRUCTOR_VERIFIED.value, question_id),
    )

    # Audit log entry — 'Instructor' type, attributed to the logged-in instructor
    cursor.execute(
        """INSERT INTO answers (question_id, answer_type, answer_text, answered_by)
           VALUES (?, 'Instructor', ?, ?)""",
        (question_id, answer_text, instructor_name),
    )
    conn.commit()
    conn.close()


def get_question_by_id(question_id: int) -> Question | None:
    """Fetch a single question by its ID.
    Returns None if no question with that ID exists.
    """
    conn = get_connection()
    row = conn.execute("SELECT * FROM questions WHERE question_id = ?", (question_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return _row_to_question(row)  # Convert the raw DB row to a Question object


def get_all_questions() -> list[Question]:
    """Return every question in the database, newest first."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM questions ORDER BY question_id DESC").fetchall()
    conn.close()
    return [_row_to_question(r) for r in rows]  # Convert each row to a Question


def get_pending_questions() -> list[Question]:
    """Return questions that have NOT yet been verified by an instructor.

    This is what the instructor panel shows — questions still needing
    human review (both Pending and AI-answered ones).
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM questions WHERE status != ? ORDER BY question_id",
        (QuestionStatus.INSTRUCTOR_VERIFIED.value,),
    ).fetchall()
    conn.close()
    return [_row_to_question(r) for r in rows]


def find_similar_questions(question_text: str) -> list[Question]:
    """Basic duplicate detection using keyword overlap (LIKE search).

    Picks the 5 longest words from the question (length > 3) and searches
    the database for any existing question containing those words.
    Returns up to 5 matches so students can see if their question was
    already asked before posting again.
    """
    words = question_text.lower().split()

    # Only use meaningful words (longer than 3 chars avoid "the", "is", "a", etc.)
    keywords = [w for w in words if len(w) > 3][:5]
    if not keywords:
        return []

    conn = get_connection()

    # Build a dynamic WHERE clause: "LOWER(question_text) LIKE ? OR LOWER(...) LIKE ?"
    conditions = " OR ".join(["LOWER(question_text) LIKE ?" for _ in keywords])
    params = [f"%{kw}%" for kw in keywords]   # wrap each keyword with % wildcards

    rows = conn.execute(
        f"SELECT * FROM questions WHERE {conditions} ORDER BY question_id DESC LIMIT 5",
        params,
    ).fetchall()
    conn.close()
    return [_row_to_question(r) for r in rows]


# ---------------------------------------------------------------------------
# Private helpers (names start with _ = internal use only)
# ---------------------------------------------------------------------------

def _register_student(name: str):
    """Insert a student record if the name hasn't been stored yet.

    Called automatically after every insert_question(). The student list
    is informational — it doesn't affect any question logic.
    """
    conn = get_connection()
    existing = conn.execute("SELECT 1 FROM students WHERE student_name = ?", (name,)).fetchone()
    if not existing:
        conn.execute("INSERT INTO students (student_name) VALUES (?)", (name,))
        conn.commit()
    conn.close()


def _row_to_question(row: sqlite3.Row) -> Question:
    """Convert a raw SQLite row (dict-like) into a typed Question dataclass.

    This keeps the rest of the code clean — callers always work with
    Question objects, never raw database rows.
    """
    return Question(
        question_id=row["question_id"],
        student_name=row["student_name"],
        subject=row["subject"],
        question_text=row["question_text"],
        status=row["status"],
        ai_answer=row["ai_answer"],
        instructor_answer=row["instructor_answer"],
        ai_confidence=row["ai_confidence"],
        keywords=row["keywords"],
        topic=row["topic"],
        timestamp=row["timestamp"],
    )
