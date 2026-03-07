# Subject-Specific Doubt Resolution System

> **For team members:** This README explains everything — what the project does, how every file works, how to install it, and how to run it. Read it top to bottom before touching the code.

---

## Table of Contents

1. [What Does This Project Do?](#1-what-does-this-project-do)
2. [How It Works — The Big Picture](#2-how-it-works--the-big-picture)
3. [Project File Structure](#3-project-file-structure)
4. [File-by-File Explanation](#4-file-by-file-explanation)
5. [Prerequisites](#5-prerequisites)
6. [Installation — Step by Step](#6-installation--step-by-step)
7. [How to Run the App](#7-how-to-run-the-app)
8. [Using the GUI App (`app.py`)](#8-using-the-gui-app-apppy)
9. [Using the CLI App (`main.py`)](#9-using-the-cli-app-mainpy)
10. [Instructor Login Credentials](#10-instructor-login-credentials)
11. [Optional: Enable AI-Powered Answers](#11-optional-enable-ai-powered-answers)
12. [Troubleshooting](#12-troubleshooting)
13. [Glossary](#13-glossary)

---

## 1. What Does This Project Do?

This is an **AI-powered academic doubt resolution system**. Think of it as an online Q&A board for students and teachers, but with a built-in AI assistant that automatically searches the web and generates answers.

**Students** can:
- Post a question under a subject (e.g., Physics, Computer Science)
- Instantly receive an AI-generated answer sourced from the web
- View all previously asked questions and their answers

**Instructors** can:
- Log in with a username and password
- Review all questions and their AI-generated answers
- Post a verified, human-reviewed answer that overrides the AI answer

The system stores everything (questions, answers, history) in a local database file so nothing is lost between sessions.

---

## 2. How It Works — The Big Picture

Here is the full flow from when a student asks a question to when they receive an answer:

```
Student types a question
        │
        ▼
┌─────────────────────┐
│   1. Save to DB     │  ← question is stored in SQLite database immediately
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  2. Search the Web  │  ← scraper.py searches DuckDuckGo for the question
└──────────┬──────────┘
           │
           ▼
┌──────────────────────────┐
│  3. Download Web Pages   │  ← top 5 URLs are fetched
│  (trafilatura / BS4)     │  ← text is extracted from those pages
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  4. Filter & Score       │  ← keep only paragraphs relevant to the question
│  Relevant Paragraphs     │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  5. Generate Answer      │  ← ai_engine.py picks the best sentences
│  (Local OR HuggingFace)  │  ← optionally calls HuggingFace AI model
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│  6. Save Answer to DB    │  ← answer, keywords, topic, confidence stored
│  & Display to Student    │
└──────────────────────────┘
           │  (later)
           ▼
┌──────────────────────────┐
│  7. Instructor Reviews   │  ← instructor logs in, reads question + AI answer
│  & Posts Verified Answer │  ← types their own answer which is saved as VERIFIED
└──────────────────────────┘
```

---

## 3. Project File Structure

```
Python-Assignment/
├── README.md                  ← You are here
└── Web Scrapper/
    ├── app.py                 ← GUI version of the app (run this for the window)
    ├── main.py                ← CLI (terminal) version of the app
    ├── models.py              ← Defines data structures used everywhere
    ├── database.py            ← All database read/write operations
    ├── scraper.py             ← Searches the web and extracts text
    ├── ai_engine.py           ← Turns scraped text into a readable answer
    ├── student_portal.py      ← Student menus for the CLI version
    ├── instructor_panel.py    ← Instructor menus for the CLI version
    └── doubt_system.db        ← SQLite database file (auto-created on first run)
```

---

## 4. File-by-File Explanation

### `models.py` — Data Blueprints
Defines the shape of data used across the whole project.
- `QuestionStatus` — An enum (named constants) with three states: `Pending`, `AI Answer Generated`, `Instructor Verified`
- `SUPPORTED_SUBJECTS` — The list of subjects students can pick from
- `Question` — A dataclass (like a blueprint) that holds all info about one question

### `database.py` — The Storage Layer
Handles all reading and writing to the SQLite database (`doubt_system.db`).
- `initialize_database()` — Creates the tables the first time the app runs
- `insert_question()` — Saves a new question
- `update_ai_answer()` — Saves the AI-generated answer
- `update_instructor_answer()` — Saves the instructor's verified answer
- `get_all_questions()` — Returns every question ever asked
- `find_similar_questions()` — Checks if a similar question was already asked (duplicate detection)

### `scraper.py` — The Web Search Engine
Searches the internet for answers.
- Uses **DuckDuckGo** to find the top 5 relevant web pages for the question
- Downloads each page and extracts the main text (ignoring ads, menus, etc.)
- Uses **trafilatura** (a smart text extractor) as the primary method, with **BeautifulSoup** as a backup
- Scores each paragraph by how many words it shares with the question
- Returns the top 10 most relevant paragraphs + source URLs

### `ai_engine.py` — The Answer Generator
Turns raw web text into a clean, readable answer.
- Receives the scraped paragraphs from `scraper.py`
- **Extracts keywords** from the question (most meaningful repeated words)
- **Classifies the topic** using keyword matching (e.g. "calculus" → "Calculus")
- **Summarizes** the content: either using the free **HuggingFace flan-t5-base AI model** (if you set the `HF_TOKEN`) or using a local algorithm that picks the best sentences
- **Computes a confidence score** (0%–100%) based on how much relevant content was found
- Returns the final answer with source links attached

### `student_portal.py` — Student CLI Interface
The terminal menus for students (used only in `main.py`).
- Post a new question (name → subject → question → AI answer generated)
- View all questions
- View a specific question by its ID
- Detects duplicate questions before saving

### `instructor_panel.py` — Instructor CLI Interface
The terminal menus for instructors (used only in `main.py`).
- Login with SHA-256 hashed password verification
- View pending/AI-answered questions
- Type and submit a verified answer
- View all questions

### `main.py` — CLI Entry Point
Run this file to use the app **entirely in the terminal** (no window, no mouse needed).
Shows a main menu: Post a question / View questions / Instructor login / Exit

### `app.py` — GUI Entry Point ✅ (Recommended)
Run this file to open the **graphical desktop window**. It has 3 tabs:
1. **Student Portal** — fill in your name, pick a subject, type a question, click Post
2. **View Questions** — browse all questions with filtering by status, click any row for details
3. **Instructor** — login form → dashboard showing pending questions → text box to write verified answer

---

## 5. Prerequisites

Before installing anything, make sure you have the following:

| Requirement | Version | How to Check |
|-------------|---------|--------------|
| Python | 3.8 or higher | `python --version` in terminal |
| pip | Latest | `pip --version` |
| Internet connection | — | Needed for web scraping |

> **Note:** On Windows, use `python` and `pip`. On Mac/Linux, you may need `python3` and `pip3`.

---

## 6. Installation — Step by Step

### Step 1 — Clone the repository

Open a terminal (Command Prompt, PowerShell, or Terminal) and run:

```sh
git clone https://github.com/Coder4261/Python-Assignment.git
```

Then navigate into the project folder:

```sh
cd "Python-Assignment/Web Scrapper"
```

### Step 2 — (Recommended) Create a virtual environment

A virtual environment keeps the project's packages separate from other Python projects on your computer. This is best practice.

```sh
# Create the virtual environment
python -m venv venv

# Activate it on Windows:
venv\Scripts\activate

# Activate it on Mac/Linux:
source venv/bin/activate
```

You should see `(venv)` appear at the start of your terminal prompt. That means it worked.

### Step 3 — Install required packages

Run this single command to install all dependencies:

```sh
pip install requests beautifulsoup4 trafilatura duckduckgo-search
```

**What each package does:**

| Package | Purpose |
|---------|---------|
| `requests` | Downloads web pages from URLs |
| `beautifulsoup4` | Parses HTML to extract readable text |
| `trafilatura` | Smarter text extraction from web pages |
| `duckduckgo-search` | Searches DuckDuckGo without needing an API key |

> `tkinter` (for the GUI) and `sqlite3` (for the database) are already included in Python — you do **not** need to install them separately.

### Step 4 — Verify everything installed correctly

```sh
python -c "import requests, bs4, trafilatura, duckduckgo_search; print('All packages OK')"
```

You should see: `All packages OK`

---

## 7. How to Run the App

There are **two ways** to run this project. Both do the same thing — one has a graphical window, the other works in the terminal.

### Option A — GUI App (Recommended for first-time users)

```sh
python app.py
```

This opens a desktop window with three tabs. No typing of menu numbers needed — just click.

### Option B — CLI App (Terminal only)

```sh
python main.py
```

This shows a text menu in the terminal. Navigate by typing a number (1, 2, 3...) and pressing Enter.

---

## 8. Using the GUI App (`app.py`)

### Tab 1 — Student Portal

1. Type your **name** in the "Your Name" field
2. Pick a **subject** from the dropdown (e.g., "Computer Science")
3. Type your **question** in the text box
4. Click **"Post Question"**
5. Wait a few seconds — the app searches the web and generates an answer
6. The AI answer appears in the dark box below, along with:
   - **Confidence %** — how sure the AI is about the answer
   - **Keywords** — key terms extracted from the question
   - **Topic** — the specific sub-topic detected
   - **Sources** — the URLs the answer was built from

### Tab 2 — View Questions

- Shows a table of all questions ever posted
- Use the **Filter** dropdown to show only Pending / AI Answered / Verified questions
- Click **Refresh** to reload the list
- Click any row to see the **full question and answers** in the detail box below

### Tab 3 — Instructor

1. Enter your **username and password** (see [Instructor Login Credentials](#10-instructor-login-credentials))
2. Click **Login**
3. You see a list of all unanswered/AI-answered questions
4. Click any question row to see its details and the AI answer
5. Type your own verified answer in the text box at the bottom
6. Click **"Submit Verified Answer"** to save it
7. Click **Logout** when done

---

## 9. Using the CLI App (`main.py`)

Run `python main.py` and you will see a menu like this:

```
============================================================
           MAIN MENU
============================================================
  1. Post a Question       (Student)
  2. View All Questions
  3. Instructor Login
  4. Exit
============================================================
  Enter choice:
```

**To post a question as a student:**
1. Press `1` → Enter
2. Enter your name → Enter
3. Type a subject number (e.g., `1` for Computer Science) → Enter
4. Type your question → Enter
5. If similar questions exist, you'll be asked if you still want to post (type `y`)
6. Wait for the AI answer to appear

**To log in as instructor:**
1. Press `3` → Enter
2. Enter username and password (see below)
3. From the instructor menu, press `1` to see pending questions
4. Press `2` to answer a question by its ID

---

## 10. Instructor Login Credentials

These are the demo accounts built into the system:

| Username | Password |
|----------|----------|
| `admin` | `admin123` |
| `prof_smith` | `teach2024` |
| `dr_jones` | `phys1cs` |

> **Security note:** These credentials are for demonstration only. In a real production system, passwords would never be stored in plain text in the code.

---

## 11. Optional: Enable AI-Powered Answers

By default, the system uses a **local algorithm** to summarise web content (no internet AI required). If you want higher-quality answers using the **Google flan-t5-base** AI model via HuggingFace, follow these steps:

1. Go to [https://huggingface.co](https://huggingface.co) and create a free account
2. Go to your account settings → Access Tokens → create a new token
3. Set it as an environment variable before running the app:

**Windows (Command Prompt):**
```cmd
set HF_TOKEN=your_token_here
python app.py
```

**Windows (PowerShell):**
```powershell
$env:HF_TOKEN="your_token_here"
python app.py
```

**Mac/Linux:**
```sh
export HF_TOKEN=your_token_here
python app.py
```

When `HF_TOKEN` is set, the system will:
1. Ask HuggingFace to summarize the scraped text
2. Ask HuggingFace to generate a polished answer from that summary
3. Fall back to the local algorithm if HuggingFace is unavailable

---

## 12. Troubleshooting

### `ModuleNotFoundError: No module named 'bs4'` (or similar)
You haven't installed the packages yet, or your virtual environment isn't activated.
```sh
pip install requests beautifulsoup4 trafilatura duckduckgo-search
```

### `ModuleNotFoundError: No module named 'tkinter'`
On some Linux systems, tkinter is not included by default.
```sh
sudo apt-get install python3-tk
```
On Windows/Mac, tkinter comes bundled with Python. Reinstall Python from [python.org](https://python.org) if missing.

### "No search results found" or web scraping fails
- Check your internet connection
- DuckDuckGo may temporarily rate-limit requests. Wait a minute and try again.
- The app will fall back to Wikipedia/GeeksForGeeks URLs if DuckDuckGo fails

### The app window opens but is blank / crashes
Make sure you are running from inside the `Web Scrapper` folder:
```sh
cd "Python-Assignment/Web Scrapper"
python app.py
```

### HuggingFace returns a 503 error
The AI model is loading on HuggingFace's servers (they sleep after inactivity). Wait 20–30 seconds and try again.

### Database issues / corrupted database
Delete `doubt_system.db` and run the app again — it will create a fresh database automatically.

---

## 13. Glossary

| Term | What it means in this project |
|------|-------------------------------|
| **Web Scraping** | Automatically downloading web pages and pulling out the text content |
| **SQLite** | A lightweight database stored as a single file (`doubt_system.db`) — no server required |
| **DuckDuckGo** | The search engine used to find relevant web pages for a question |
| **BeautifulSoup (BS4)** | A Python library that parses HTML and lets you extract specific text |
| **Trafilatura** | A smarter Python library that extracts only the "main" article text from a page, ignoring menus/ads |
| **HuggingFace** | A platform hosting free AI models. We use `flan-t5-base` for text summarization |
| **flan-t5-base** | Google's AI text model — can summarize, paraphrase, and answer questions |
| **Extractive Summarization** | Picking the most relevant existing sentences (our local fallback — no AI needed) |
| **Confidence Score** | A percentage (0–100%) indicating how sure the system is about the answer quality |
| **CRUD** | Create, Read, Update, Delete — the four basic database operations |
| **Enum** | A named set of constants (e.g., `QuestionStatus.PENDING`) used to avoid typos |
| **Dataclass** | A Python class that just holds data fields — like a structured record |
| **SHA-256** | A one-way cryptographic hash function used to store passwords safely in the CLI app |
| **tkinter** | Python's built-in GUI (Graphical User Interface) library — used to build the desktop window |
| **Thread** | A background task that runs alongside the main program so the GUI stays responsive while the AI works |
| **Virtual Environment** | An isolated Python workspace so installed packages don't conflict with other projects |

---

## Authors
- [Coder4261](https://github.com/Coder4261)

## License
This project is for educational purposes.

