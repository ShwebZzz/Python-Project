"""
main.py
-------
Entry point for the Subject-Specific Doubt Resolution System (TERMINAL version).

Run this file to use the app entirely in the terminal (no window required):
    python main.py

ARCHITECTURE:
  main.py is the "glue" — it initialises the database and shows the main menu.
  The real work is done by the modules it imports:
    - database.py       → initialise tables on startup
    - student_portal.py → handle the "Post a Question" and view flows
    - instructor_panel.py → handle instructor login and answer flows

  For the GUI (desktop window) version, run app.py instead.
"""

import sys
import logging

from database import initialize_database
from student_portal import student_menu
from instructor_panel import instructor_login

# ---------------------------------------------------------------------------
# Logging setup
# Logging prints timestamped messages to the terminal when the app runs.
# Format: "12:34:56  INFO      scraper  Fetching https://..."
# Other modules use `logger = logging.getLogger(__name__)` to send messages here.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,                    # Show INFO and above (INFO, WARNING, ERROR)
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",                    # Show time as HH:MM:SS
)

# ---------------------------------------------------------------------------
# Banner — displayed when the app starts
# ---------------------------------------------------------------------------
BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║     SUBJECT-SPECIFIC DOUBT RESOLUTION SYSTEM                 ║
║     ─────────────────────────────────────────                ║
║     An Academic Platform for Question Answering              ║
║                                                              ║
║     Features:                                                ║
║       • Post subject-related questions                       ║
║       • AI-powered answers via web scraping                  ║
║       • Instructor-verified responses                        ║
║       • Keyword extraction & topic classification            ║
║       • Duplicate question detection                         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""

# Help text shown before the instructor login prompt
INSTRUCTOR_HELP = """
  Default instructor accounts for demo:

    Username       Password
    ──────────     ──────────
    admin          admin123
    prof_smith     teach2024
    dr_jones       phys1cs
"""


# ---------------------------------------------------------------------------
# Main application loop
# ---------------------------------------------------------------------------

def main():
    """Application entry point — sets up the app and runs the main menu loop."""

    # Initialise the database on startup.
    # This creates the tables if they don't exist yet.
    # Safe to call on every run — uses IF NOT EXISTS internally.
    initialize_database()

    print(BANNER)

    # Keep showing the main menu until the user selects "Exit"
    while True:
        print("\n" + "=" * 60)
        print("           MAIN MENU")
        print("=" * 60)
        print("  1. Post a Question       (Student)")
        print("  2. View All Questions")
        print("  3. Instructor Login")
        print("  4. Exit")
        print("=" * 60)

        choice = input("  Enter choice: ").strip()

        if choice == "1":
            student_menu()        # Hands control to student_portal.py
        elif choice == "2":
            _view_all_questions()
        elif choice == "3":
            print(INSTRUCTOR_HELP)
            instructor_login()    # Hands control to instructor_panel.py
        elif choice == "4":
            print("\n  Goodbye!\n")
            sys.exit(0)           # Exit with success status code 0
        else:
            print("  [!] Invalid choice. Please enter 1-4.")


def _view_all_questions():
    """Quick read-only view of all questions — available without any login.

    Imports are done inside the function (lazy imports) to avoid
    circular import issues at module load time.
    """
    from database import get_all_questions
    from student_portal import _display_question_full

    questions = get_all_questions()
    if not questions:
        print("\n  No questions have been posted yet.")
        return

    print(f"\n  Total questions: {len(questions)}\n")
    for q in questions:
        _display_question_full(q)   # Full display from student_portal.py


# ---------------------------------------------------------------------------
# Script entry point
# Python only runs main() when this file is executed directly.
# If another module were to import main.py, main() would NOT run automatically.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    main()
