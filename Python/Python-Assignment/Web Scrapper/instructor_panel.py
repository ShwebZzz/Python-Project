"""
instructor_panel.py
-------------------
CLI (terminal) interface for instructors to review and answer student questions.

This module is ONLY used by main.py (the terminal version).
app.py has its own Instructor tab built directly into the tkinter GUI.

SECURITY:
  Passwords are stored as SHA-256 hashes — never in plain text.
  SHA-256 is a one-way cryptographic function: given the hash, you cannot
  reverse it to get the original password. We hash the entered password
  and compare it to the stored hash to verify credentials.

INSTRUCTOR WORKFLOW:
  1. Login with username/password
  2. View pending/AI-answered questions
  3. Read the question + AI-generated answer
  4. Type a verified human answer
  5. Save it — question status moves to "Instructor Verified"
"""

import textwrap
import hashlib   # Python standard library: provides SHA-256 and other hash algorithms

from models import QuestionStatus
from database import (
    get_pending_questions,       # Questions not yet verified by an instructor
    get_all_questions,           # Every question in the system
    get_question_by_id,          # Fetch one specific question
    update_instructor_answer,    # Save the instructor's answer to DB
)

# ---------------------------------------------------------------------------
# Credential store
# ---------------------------------------------------------------------------
# Passwords are stored as SHA-256 hashes for security.
# hashlib.sha256("admin123".encode()).hexdigest() produces the hash of "admin123".
# The encode() converts the string to bytes (required by hashlib).
# The hexdigest() returns the hash as a hex string like "240be518...".
#
# In a real production system these would be in a secure database with
# salt + PBKDF2/bcrypt hashing — SHA-256 alone is not recommended for
# production password storage, but fine for this demo.
INSTRUCTOR_CREDENTIALS = {
    "admin":      hashlib.sha256("admin123".encode()).hexdigest(),
    "prof_smith": hashlib.sha256("teach2024".encode()).hexdigest(),
    "dr_jones":   hashlib.sha256("phys1cs".encode()).hexdigest(),
}


def instructor_login() -> bool:
    """Prompt for instructor credentials and validate them.

    Returns True if login succeeded, False otherwise.
    On success, automatically calls instructor_menu() to enter the dashboard.
    """
    print("\n" + "=" * 60)
    print("           INSTRUCTOR LOGIN")
    print("=" * 60)

    username = input("  Username: ").strip()
    password = input("  Password: ").strip()

    # Basic input validation — empty fields should never pass
    if not username or not password:
        print("  [!] Credentials cannot be empty.")
        return False

    # Check if this username exists in our credential store
    stored_hash = INSTRUCTOR_CREDENTIALS.get(username)
    if stored_hash is None:
        print("  [!] Unknown username.")
        return False

    # Hash the entered password and compare to the stored hash.
    # If they match → correct password.
    # Note: we never store or compare the plain-text password anywhere.
    if hashlib.sha256(password.encode()).hexdigest() != stored_hash:
        print("  [!] Incorrect password.")
        return False

    # Authentication passed
    print(f"  [+] Welcome, {username}!")
    instructor_menu(username)
    return True


def instructor_menu(instructor_name: str):
    """Instructor dashboard loop — shown after successful login.

    Keeps looping until the instructor chooses "Logout" (option 4).
    `instructor_name` is passed into _post_answer() so the DB records
    which instructor wrote each answer.
    """
    while True:
        print("\n" + "=" * 60)
        print("           INSTRUCTOR DASHBOARD")
        print("=" * 60)
        print("  1. View Pending / AI-Answered Questions")
        print("  2. Post Verified Answer")
        print("  3. View All Questions")
        print("  4. Logout")
        print("=" * 60)

        choice = input("  Enter choice: ").strip()

        if choice == "1":
            _view_pending(instructor_name)
        elif choice == "2":
            _post_answer(instructor_name)
        elif choice == "3":
            _view_all()
        elif choice == "4":
            print("  Logged out.\n")
            break   # Exit loop → return to main.py
        else:
            print("  [!] Invalid choice.")


def _view_pending(instructor_name: str):
    """Show all questions that are still waiting for instructor verification.

    'Pending' means: status is either Pending or AI Answered.
    'Instructor Verified' questions are excluded because they are already done.
    """
    questions = get_pending_questions()
    if not questions:
        print("\n  No pending questions. All caught up!")
        return

    print(f"\n  Pending questions: {len(questions)}\n")
    for q in questions:
        _display_question(q)   # Full display including AI answer if present


def _post_answer(instructor_name: str):
    """Let the instructor post a verified answer for a specific question.

    Flow:
      1. Ask for question ID
      2. Fetch and display the question (so instructor can read it)
      3. Warn if already verified (ask to overwrite)
      4. Collect answer via multi-line input (blank line ends input)
      5. Save to database
    """
    qid_str = input("\n  Enter Question ID to answer: ").strip()
    try:
        qid = int(qid_str)
    except ValueError:
        print("  [!] Invalid ID.")
        return

    q = get_question_by_id(qid)
    if q is None:
        print(f"  [!] No question found with ID {qid}.")
        return

    # Show the question so the instructor knows what they're answering
    _display_question(q)

    # Warn if this question already has a verified answer
    if q.status == QuestionStatus.INSTRUCTOR_VERIFIED.value:
        print("  [i] This question already has a verified answer.")
        overwrite = input("  Overwrite? (y/n): ").strip().lower()
        if overwrite != "y":
            return

    # Collect a multi-line answer.
    # The instructor types their answer across as many lines as they need.
    # A blank Enter on an otherwise-empty line signals "done".
    print("\n  Type your answer (press Enter twice to finish):")
    lines = []
    while True:
        line = input("  > ")
        if line == "":
            if lines:
                break   # Blank line after content → stop collecting
            continue    # Blank line with no content yet → just keep waiting
        lines.append(line)

    if not lines:
        print("  [!] Empty answer. Cancelled.")
        return

    answer_text = "\n".join(lines)   # Rejoin lines into a single string
    update_instructor_answer(qid, answer_text, instructor_name)
    print(f"\n  [+] Verified answer saved for Q#{qid}.")


def _view_all():
    """Show every question in the system — for instructor overview."""
    questions = get_all_questions()
    if not questions:
        print("\n  No questions in the system.")
        return

    print(f"\n  Total questions: {len(questions)}\n")
    for q in questions:
        _display_question(q)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _display_question(q):
    """Print a single question with all its current details.

    Shows status badge, subject, student name, the question itself,
    the AI answer (if any), and the instructor answer (if any).
    """
    # Map status value to a short human-readable badge
    status_badge = {
        QuestionStatus.PENDING.value: "PENDING",
        QuestionStatus.AI_ANSWERED.value: "AI ANSWERED",
        QuestionStatus.INSTRUCTOR_VERIFIED.value: "VERIFIED",
    }.get(q.status, q.status)   # Fall back to raw status string if unknown

    print("  " + "-" * 56)
    print(f"  Q#{q.question_id}  [{status_badge}]  Subject: {q.subject}")
    print(f"  Student : {q.student_name}  |  {q.timestamp}")
    print(f"  Question: {q.question_text}")
    if q.keywords:
        print(f"  Keywords: {q.keywords}")
    if q.ai_answer:
        print("  AI Answer:")
        _print_wrapped(q.ai_answer)
        print(f"  AI Confidence: {q.ai_confidence:.0%}")
    if q.instructor_answer:
        print("  Instructor Answer:")
        _print_wrapped(q.instructor_answer)
    print("  " + "-" * 56 + "\n")


def _print_wrapped(text: str, width: int = 56, indent: str = "    "):
    """Wrap long text to fit the terminal width, with indentation."""
    for line in text.split("\n"):
        wrapped = textwrap.fill(line, width=width, initial_indent=indent,
                                subsequent_indent=indent)
        print(wrapped)

