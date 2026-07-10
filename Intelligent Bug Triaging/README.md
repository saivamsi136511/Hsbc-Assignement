# Intelligent Bug Triaging System

An AI-powered bug classification and triaging system that automatically ingests raw bug reports, sanitizes/cleans the text, dynamically triages them using local LLMs (Ollama) or custom rule-based heuristics, and commits them to a local SQLite database for lifecycle management. 

It comes with a fully-functional Web Dashboard for viewing, searching, filtering, and updating bug reports.

---

## 🛠️ How It Works

```
Raw Bug Report (Title + Description)
      ↓
Text Cleaning (Sanitization / Redaction)
      ↓
Triaging Engine (NLP / Local LLM)
      ↓
Categorization & Severity Assessment
  - Categories: UI, Backend, Database, API, Authentication, Performance
  - Severity: Low, Medium, High, Critical
  - Priority: P0 (Blocker) to P3 (Minor)
      ↓
SQLite Storage (bugs.db)
      ↓
Interactive Flask Dashboard (Port 5000)
```

---

## 🚀 Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. (Optional) Setup Local LLM (Ollama)
Ensure Ollama is running and download a model for triaging:
```bash
ollama serve
ollama pull llama3.1
```
*(If Ollama is offline or unavailable, the system automatically falls back to an offline rule-based heuristic classifier so validation never fails)*

### 3. Run the Web Server
```bash
python app.py
```
This launches the Flask application on [http://localhost:5000](http://localhost:5000).

---

## 🔬 In-Depth Verification

You can verify the bug triaging classification logic with the offline test script:
```bash
python test_triaging.py
```

To seed sample bugs into the SQLite database:
```bash
# Direct SQLite seed
python seed_bugs.py --clear

# API seed (runs against live Flask application)
python seed_bugs.py --api http://localhost:5000
```

---

## 📂 Project Files

- **`app.py`**: Flask REST API endpoints and dashboard controller.
- **`database.py`**: SQLite database setup, index schema, and CRUD interface.
- **`models.py`**: Data classes representing raw BugReports and triaged Tickets.
- **`triaging_engine.py`**: NLP parsing, text cleaning/sanitization, Ollama JSON requests, and heuristic fallback logic.
- **`test_triaging.py`**: Verification script verifying triaging outcomes on multiple categories.
- **`seed_bugs.py`**: Utility script to seed sample data into SQLite or via REST endpoints.
- **`templates/index.html`**: HTML layout for the dashboard.
- **`static/`**: Stylesheet and JavaScript files.
