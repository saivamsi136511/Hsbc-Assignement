#!/usr/bin/env python3
"""
Automated tests for log_analyzer.py. These run entirely offline (no Ollama
required) and lock in the parsing/heuristic behavior, especially the
easy-to-get-wrong bits: per-language frame ordering, chained-exception role
assignment, redaction, and hallucination guarding.

Run with:  python3 test_log_analyzer.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log_analyzer as la

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_logs")


def _read(name):
    with open(os.path.join(SAMPLES, name), encoding="utf-8") as f:
        return f.read()


class TestFormatDetection(unittest.TestCase):
    def test_python(self):
        fmt, events = la.parse_log(_read("python_chained.log"))
        self.assertEqual(fmt, "python")
        self.assertEqual(len(events), 1)

    def test_java(self):
        fmt, events = la.parse_log(_read("java_caused_by.log"))
        self.assertEqual(fmt, "java")

    def test_node(self):
        fmt, events = la.parse_log(_read("node_error.log"))
        self.assertEqual(fmt, "node")

    def test_go(self):
        fmt, events = la.parse_log(_read("go_panic.log"))
        self.assertEqual(fmt, "go")

    def test_generic_fallback(self):
        fmt, events = la.parse_log(_read("generic_unstructured.log"))
        self.assertEqual(fmt, "generic")
        self.assertTrue(len(events) >= 1)


class TestOffendingLocation(unittest.TestCase):
    """The single most important correctness property: pointing at the right
    file/line. Python's convention (root cause = FIRST traceback, actual
    frame = LAST 'File' line) is the inverse of Java/Node/Go/C#'s convention
    (root cause = LAST 'Caused by', actual frame = FIRST 'at' line)."""

    def test_python_root_cause_is_first_traceback_not_last(self):
        _, events = la.parse_log(_read("python_chained.log"))
        event = events[-1]
        root = event.root_cause
        self.assertEqual(root.exc_type, "KeyError")  # NOT OrderProcessingError
        frame = la.actual_frame(root, event.format)
        self.assertEqual(frame.file, "/srv/app/workers/pricing.py")
        self.assertEqual(frame.line, 41)

    def test_java_root_cause_is_caused_by_not_top(self):
        _, events = la.parse_log(_read("java_caused_by.log"))
        event = events[-1]
        root = event.root_cause
        self.assertEqual(root.exc_type, "java.lang.IllegalStateException")
        frame = la.actual_frame(root, event.format)
        self.assertEqual(frame.file, "CartSessionStore.java")
        self.assertEqual(frame.line, 22)

    def test_node_offending_frame(self):
        _, events = la.parse_log(_read("node_error.log"))
        event = events[-1]
        frame = la.actual_frame(event.root_cause, event.format)
        self.assertTrue(frame.file.endswith("userService.js"))
        self.assertEqual(frame.line, 27)

    def test_go_offending_frame(self):
        _, events = la.parse_log(_read("go_panic.log"))
        event = events[-1]
        frame = la.actual_frame(event.root_cause, event.format)
        self.assertTrue(frame.file.endswith("batch.go"))
        self.assertEqual(frame.line, 44)


class TestFrameDedup(unittest.TestCase):
    def test_recursive_frames_collapsed(self):
        _, events = la.parse_log(_read("secrets_and_recursion.log"))
        event = events[-1]
        root = event.root_cause
        # 7 identical recur.py:12 frames + 1 distinct recur.py:9 frame in the
        # source log should collapse to 2 displayed entries, not 8.
        self.assertLessEqual(len(root.frames), 3)
        self.assertTrue(any("repeated" in f.raw for f in root.frames))


class TestRedaction(unittest.TestCase):
    def test_secrets_are_masked(self):
        raw = _read("secrets_and_recursion.log")
        redacted = la.redact(raw)
        self.assertNotIn("sk_live_abcdef1234567890", redacted)
        self.assertNotIn("jane.doe@example.com", redacted)
        self.assertNotIn("10.0.0.42", redacted)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", redacted)
        # Line numbers / file paths must survive redaction so parsing still works
        self.assertIn("recur.py", redacted)
        self.assertIn("line 12", redacted)


class TestHeuristicFallback(unittest.TestCase):
    def test_known_exception_gets_specific_advice(self):
        _, events = la.parse_log(_read("python_chained.log"))
        report = la.heuristic_report(events[-1])
        self.assertEqual(report["error_type"], "KeyError")
        self.assertIn(".get(", report["suggested_fix"])

    def test_unrecognized_log_has_safe_defaults(self):
        event = la.CrashEvent(format="unknown", chain=[], raw_text="", start_offset=0, end_offset=0)
        report = la.heuristic_report(event)
        self.assertEqual(report["confidence"], "low")
        self.assertIsNone(report["offending_file"])


class TestValidation(unittest.TestCase):
    def test_hallucinated_location_flagged_unverified(self):
        _, events = la.parse_log(_read("node_error.log"))
        event = events[-1]
        fake = {"offending_file": "/nowhere/fake.js", "offending_line": 1}
        out = la.validate_report(dict(fake), event)
        self.assertFalse(out["_verified_against_evidence"])

    def test_real_location_verified(self):
        _, events = la.parse_log(_read("node_error.log"))
        event = events[-1]
        real = {"offending_file": "/srv/app/src/services/userService.js", "offending_line": 27}
        out = la.validate_report(dict(real), event)
        self.assertTrue(out["_verified_against_evidence"])


class TestContextWindowManagement(unittest.TestCase):
    def test_small_context_not_truncated(self):
        _, events = la.parse_log(_read("node_error.log"))
        ctx = la.build_llm_context(events[-1], max_chars=6000)
        self.assertFalse(ctx.truncated)

    def test_huge_context_gets_truncated_and_shrinks(self):
        _, events = la.parse_log(_read("python_chained.log"))
        ctx = la.build_llm_context(events[-1], max_chars=50)
        self.assertLessEqual(len(ctx.text), 200)  # allows for one final hard-truncate pass


class TestMultipleCrashEvents(unittest.TestCase):
    def test_which_selects_correct_event(self):
        log_text = (
            'Traceback (most recent call last):\n'
            '  File "/app/a.py", line 5, in first_thing\n'
            '    x = 1/0\n'
            'ZeroDivisionError: division by zero\n'
            'Traceback (most recent call last):\n'
            '  File "/app/b.py", line 9, in second_thing\n'
            '    y = undefined_var\n'
            "NameError: name 'undefined_var' is not defined\n"
        )
        _, events = la.parse_log(log_text)
        self.assertEqual(len(events), 2)
        self.assertEqual(la.select_events(events, "first")[0].root_cause.exc_type, "ZeroDivisionError")
        self.assertEqual(la.select_events(events, "last")[0].root_cause.exc_type, "NameError")
        self.assertEqual(len(la.select_events(events, "all")), 2)


class TestEmptyAndBinaryInput(unittest.TestCase):
    def test_empty_text_parses_to_no_events(self):
        fmt, events = la.parse_log("")
        self.assertEqual(events, [])

    def test_binary_garbage_does_not_crash(self):
        garbage = os.urandom(200)
        text = la._decode(garbage)
        # should not raise
        fmt, events = la.parse_log(text)
        self.assertIsInstance(events, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
