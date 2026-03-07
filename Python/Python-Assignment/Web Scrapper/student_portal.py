"""
student_portal.py
-----------------
CLI (terminal) interface for students to post questions and view answers.

This module is ONLY used by main.py (the terminal version of the app).
app.py (the GUI version) has its own equivalent code built directly into
the tkinter window.

FLOW when a student posts a question:
  1. Ask for student name
  2. Show subject menu, student picks one
  3. Ask for the question text
  4. Check database for similar/duplicate questions
  5. Save question to database
  6. Call ai_engine.generate_answer() which scrapes the web and returns an answer
  7. Save the AI answer back to the database
  8. Display the answer to the student
"""

import textwrap   # Python standard library: wraps long text to fit terminal width

from models import SUPPORTED_SUBJECTS, QuestionStatus
from database import (
    insert_question,          # Save a new question to DB
    update_ai_answer,         # Save AI answer to DB
    get_all_questions,        # Fetch every question
    get_question_by_id,       # Fetch one specific question
    find_similar_questions,   # Duplicate detection
)
from ai_engine import generate_answer   # The AI pipeline (scrape → summarize → answer)


def student_menu():
    """Top-level student menu loop.

    Keeps showing the menu until the student chooses to go back (option 4).
    Each iteration reads input, dispatches to the appropriate function,
    then loops back.
    """
    while True:
        print("\n" + "=" * 60)
        print("           STUDENT PORTAL")
        print("=" * 60)
        print("  1. Post a New Question")
        print("  2. View My Questions")
        print("  3. View a Question by ID")
        print("  4. Back to Main Menu")
        print("=" * 60)

        choice = input("  Enter choice: ").strip()

        if choice == "1":
            _post_question()
        elif choice == "2":
            _view_all_questions()
        elif choice == "3":
            _view_question_by_id()
        elif choice == "4":
            break   # Exit the while loop → return to main.py's main menu
        else:
            print("  [!] Invalid choice. Try again.")


def _post_question():
    """Walk the student through posting a question.

    This is the most complex function in this file — it handles:
      - Input validation (empty fields)
      - Subject selection (numbered list or free text)
      - Duplicate detection (warn but allow the student to continue)
      - Saving to DB
      - Triggering the AI pipeline
      - Displaying the result
    """
    print("\n--- Post a New Question ---\n")

    # --- Collect student name ---
    student_name = input("  Your name: ").strip()
    if not student_name:
        print("  [!] Name cannot be empty.")
        return   # Abort early, go back to menu

    # --- Subject selection ---
    print("\n  Available subjects:")
    for i, subj in enumerate(SUPPORTED_SUBJECTS, 1):
        print(f"    {i}. {subj}")   # Print numbered list from models.py

    subj_input = input("\n  Choose subject number (or type custom): ").strip()

    try:
        idx = int(subj_input)   # Student typed a number
        if 1 <= idx <= len(SUPPORTED_SUBJECTS):
            subject = SUPPORTED_SUBJECTS[idx - 1]   # Convert 1-based to 0-based index
        else:
            print("  [!] Invalid number. Using 'General Knowledge'.")
            subject = "General Knowledge"
    except ValueError:
        # Student typed a custom subject name instead of a number
        subject = subj_input if subj_input else "General Knowledge"

    # --- Collect question text ---
    question_text = input("  Your question: ").strip()
    if not question_text:
        print("  [!] Question cannot be empty.")
        return

    # --- Duplicate detection ---
    # Search the database for questions with overlapping keywords.
    # If similar questions exist, show them so the student can see if
    # their question was already answered before posting a duplicate.
    similar = find_similar_questions(question_text)
    if similar:
        print(f"\n  [i] Found {len(similar)} similar question(s) already in the system:")
        for sq in similar[:3]:
            print(f"      Q#{sq.question_id}: {sq.question_text[:80]}...")
            if sq.instructor_answer:
                print(f"        Instructor Answer: {sq.instructor_answer[:100]}...")
            elif sq.ai_answer:
                print(f"        AI Answer: {sq.ai_answer[:100]}...")
        cont = input("\n  Still want to post? (y/n): ").strip().lower()
        if cont != "y":
            print("  Question cancelled.")
            return

    # --- Save the question to the database ---
    qid = insert_question(student_name, subject, question_text)
    print(f"\n  [+] Question posted! (ID: {qid})")
    print("  [*] Generating AI answer, please wait...\n")

    # --- Trigger the AI pipeline ---
    # generate_answer() calls scraper.py and ai_engine.py internally.
    # This can take 5–30 seconds depending on internet speed.
    ai_result = generate_answer(question_text, subject)

    if ai_result["success"]:
        # Save the AI answer back to the database
        update_ai_answer(
            qid,
            ai_result["answer"],
            ai_result["confidence"],
            ai_result["keywords"],
            ai_result["topic"],
        )

        # Display the answer nicely in the terminal
        print("\n  " + "-" * 56)
        print("  AI-GENERATED ANSWER")
        print("  " + "-" * 56)
        _print_wrapped(ai_result["answer"])
        print(f"\n  Confidence : {ai_result['confidence']:.0%}")   # e.g., "80%"
        print(f"  Keywords   : {ai_result['keywords']}")
        print(f"  Topic      : {ai_result['topic']}")
        print("  " + "-" * 56)
    else:
        # AI failed — question is still saved; an instructor can answer later
        print(f"  [!] AI could not generate an answer: {ai_result['error']}")
        print("  Your question is saved. An instructor will answer it later.")


def _view_all_questions():
    """Display a compact summary of every question in the system."""
    questions = get_all_questions()
    if not questions:
        print("\n  No questions found.")
        return

    print(f"\n  Total questions: {len(questions)}\n")
    for q in questions:
        _display_question_summary(q)   # One-line summary per question


def _view_question_by_id():
    """Ask for a question ID and display its full details."""
    qid_str = input("\n  Enter Question ID: ").strip()
    try:
        qid = int(qid_str)
    except ValueError:
        print("  [!] Invalid ID.")
        return

    q = get_question_by_id(qid)
    if q is None:
        print(f"  [!] No question found with ID {qid}.")
        return
    _display_question_full(q)   # Full display with all answers


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _display_question_summary(q):
    """Print a compact one-line summary of a question.

    The status icon shows the question state at a glance:
      [ ] = Pending (no answer yet)
      [A] = AI answer generated
      [V] = Instructor verified
    """
    status_icon = {
        QuestionStatus.PENDING.value: "[ ]",
        QuestionStatus.AI_ANSWERED.value: "[A]",
        QuestionStatus.INSTRUCTOR_VERIFIED.value: "[V]",
    }.get(q.status, "[ ]")

    # Truncate question text so long questions don't wrap to multiple lines
    print(f"  {status_icon} Q#{q.question_id}  [{q.subject}]  {q.question_text[:70]}")
    print(f"       Student: {q.student_name}  |  Status: {q.status}  |  {q.timestamp}")
    print()


def _display_question_full(q):
    """Print all details for a single question — used in the 'View by ID' flow."""
    print("\n" + "=" * 60)
    print(f"  Question #{q.question_id}")
    print("=" * 60)
    print(f"  Student  : {q.student_name}")
    print(f"  Subject  : {q.subject}")
    print(f"  Status   : {q.status}")
    print(f"  Posted   : {q.timestamp}")
    if q.keywords:
        print(f"  Keywords : {q.keywords}")
    if q.topic:
        print(f"  Topic    : {q.topic}")
    print(f"\n  Question : {q.question_text}")
    print("-" * 60)

    if q.ai_answer:
        print("  AI Answer:")
        _print_wrapped(q.ai_answer)
        if q.ai_confidence:
            print(f"\n  AI Confidence: {q.ai_confidence:.0%}")
    else:
        print("  AI Answer: (not yet generated)")

    print("-" * 60)

    if q.instructor_answer:
        print("  Instructor Answer (VERIFIED):")
        _print_wrapped(q.instructor_answer)
    else:
        print("  Instructor Answer: (awaiting review)")

    print("=" * 60)


def _print_wrapped(text: str, width: int = 56, indent: str = "    "):
    """Print text wrapped to fit within the terminal, with indentation.

    textwrap.fill() breaks a string into lines of at most `width` characters.
    We process each paragraph (newline-separated) individually so blank
    lines and paragraph structure in the answer are preserved.
    """
    for line in text.split("\n"):
        wrapped = textwrap.fill(line, width=width, initial_indent=indent,
                                subsequent_indent=indent)
        print(wrapped)

