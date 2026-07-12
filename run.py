#!/usr/bin/env python3
"""
run.py
======
Unified entry point and interactive CLI menu for evaluating the 5 HSBC assignments.
Can be run locally or inside a Docker container.

Usage:
  python run.py           # opens the interactive menu
  python run.py <task_no>  # executes a specific task directly
"""

import os
import sys
import subprocess

PROJECTS = {
    "1": {
        "name": "AI-Powered Log Analysis for Root Cause",
        "dir": "AI-Powered Log Analysis for Root Cause",
        "cmd": [sys.executable, "-u", "log_analyzer.py", "sample_logs/python_chained.log", "--dry-run"],
        "desc": "Analyzes crash logs under a token budget with dry-run mode (OpenCV pre-parsing log statistics)."
    },
    "2": {
        "name": "Automated Test Case Generation",
        "dir": "Automated Test Case Generation",
        "cmd": [sys.executable, "-u", "generate_tests.py", "-i", "samples/sample_user_story.md",
                "-o", "test_generated.py", "--dry-run"],
        "desc": "Parses the sample user story and shows acceptance criteria, batching plan, and generation pipeline (dry-run — no Ollama needed)."
    },
    "3": {
        "name": "Intelligent Bug Triaging",
        "dir": "Intelligent Bug Triaging",
        "cmd": [sys.executable, "-u", "app.py"],
        "desc": "Starts the Flask bug triaging web server on port 5000."
    },
    "4": {
        "name": "Visual Regression Testing with Computer Vision",
        "dir": "Visual Regression Testing with Computer Vision",
        "cmd": [sys.executable, "-u", "visual_regressor.py", "--baseline", "sample_screenshots/baseline.png", "--current", "sample_screenshots/new_deployment.png", "--dry-run", "--verbose"],
        "desc": "Runs the multi-layer OpenCV comparison (SSIM, features, edges) on the bank dashboard screenshots."
    },
    "5": {
        "name": "Self-Healing UI Automation",
        "dir": "Self-Healing UI Automation",
        "cmd": [sys.executable, "-u", "test_login.py"],
        "desc": "Executes Selenium test suite in headless mode using local Ollama model to heal broken HTML locators."
    }
}


def print_menu():
    print("=" * 80)
    print("                HSBC ASSIGNMENT EVALUATOR MENU")
    print("=" * 80)
    for key, p in PROJECTS.items():
        print(f"  {key}) {p['name']}")
        print(f"     Description : {p['desc']}")
        print(f"     Subdirectory: {p['dir']}")
        print(f"     Default Cmd : {' '.join(p['cmd'])}")
        print("-" * 80)
    print("  q) Quit / Exit")
    print("=" * 80)


def execute_task(choice):
    if choice not in PROJECTS:
        print(f"Error: Invalid selection '{choice}'. Choose 1-5 or q to quit.")
        return False

    p = PROJECTS[choice]
    print(f"\n[evaluator] Launching task: {p['name']} ...")
    print(f"[evaluator] CWD: {p['dir']}")
    print(f"[evaluator] Executing: {' '.join(p['cmd'])}")
    print("=" * 80)

    # Change directory and run
    original_cwd = os.getcwd()
    try:
        os.chdir(p["dir"])
        # Flask runs in a loop, other scripts are exit-oriented
        subprocess.run(p["cmd"], check=True)
    except KeyboardInterrupt:
        print("\n[evaluator] Task stopped by user.")
    except Exception as e:
        print(f"\n[evaluator] Task failed: {e}")
    finally:
        os.chdir(original_cwd)

    print("=" * 80)
    input("\nPress Enter to return to the menu...")
    return True


def main():
    # Force UTF-8 on Windows terminal output
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

    # Direct arg evaluation
    if len(sys.argv) > 1:
        choice = sys.argv[1].strip()
        if choice in PROJECTS:
            execute_task(choice)
            return
        elif choice in ("-h", "--help"):
            print("Usage: python run.py [1-5]")
            return
        else:
            print(f"Unknown task number '{choice}'. Choose 1-5.")
            return

    # Interactive loop
    while True:
        # Clear screen
        os.system('cls' if os.name == 'nt' else 'clear')
        print_menu()
        choice = input("Enter choice (1-5 or q): ").strip().lower()
        if choice == 'q':
            print("Exiting. Thank you!")
            break
        execute_task(choice)


if __name__ == "__main__":
    main()
