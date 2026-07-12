"""
testgen/cli.py
==============
Command-line interface for the Automated Test Case Generation tool.

Parses arguments, orchestrates the generation pipeline, and handles all
user-facing I/O (printing progress, writing output files, running pytest).

This module is the bridge between the user's shell command and the
``testgen`` package's generation functions.  It is intentionally thin:
all business logic lives in the submodules (``generator``, ``parser``,
``output``, etc.).

Entry point
-----------
    python generate_tests.py [options]   # via the thin entry point script
    python -m testgen.cli [options]      # direct module invocation
"""

import argparse
import subprocess
import sys
from pathlib import Path

from testgen.config import Config
from testgen.constants import (
    DEFAULT_MODEL,
    OLLAMA_DEFAULT_HOST,
    DEFAULT_TEMPERATURE,
    DEFAULT_NUM_CTX,
    DEFAULT_NUM_PREDICT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_BATCH_SIZE,
    DEFAULT_BATCH_THRESHOLD,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_READ_TIMEOUT,
    DEFAULT_MAX_CONN_RETRIES,
    DEFAULT_OUTPUT_FILE,
)
from testgen.generator import generate_single_shot, generate_batched, generate_stub
from testgen.ollama_client import OllamaError
from testgen.output import ensure_pytest_import, summarize, write_stub_module
from testgen.parser import parse_acceptance_items


def build_arg_parser() -> argparse.ArgumentParser:
    """
    Build and return the CLI argument parser.

    Returns:
        A configured ``argparse.ArgumentParser`` instance with all supported
        flags and their defaults.
    """
    p = argparse.ArgumentParser(
        description=(
            "Generate a PyTest suite (happy-path + boundary + edge cases) "
            "from a user story, using a local Ollama model."
        )
    )
    p.add_argument("-i", "--input", required=True,
                   help="Path to the user story / acceptance criteria file (.txt/.md)")
    p.add_argument("-o", "--output", default=DEFAULT_OUTPUT_FILE,
                   help=f"Output PyTest file path (default: {DEFAULT_OUTPUT_FILE})")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL,
                   help=f"Ollama model name (default: {DEFAULT_MODEL}). "
                        "A code-focused model like qwen2.5-coder:7b gives better results.")
    p.add_argument("--host", default=OLLAMA_DEFAULT_HOST,
                   help=f"Ollama server URL (default: {OLLAMA_DEFAULT_HOST})")
    p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)

    # Timeouts / retries
    p.add_argument("--connect-timeout", type=int, default=DEFAULT_CONNECT_TIMEOUT)
    p.add_argument("--read-timeout", type=int, default=DEFAULT_READ_TIMEOUT,
                   help="Seconds of silence between streamed tokens before treating as stall.")
    p.add_argument("--max-conn-retries", type=int, default=DEFAULT_MAX_CONN_RETRIES)

    # Model context/output size
    p.add_argument("--num-ctx", type=int, default=DEFAULT_NUM_CTX)
    p.add_argument("--num-predict", type=int, default=DEFAULT_NUM_PREDICT)

    # Self-healing
    p.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                   help="Self-healing retries per batch on syntax errors.")

    # Batching
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--batch-threshold", type=int, default=DEFAULT_BATCH_THRESHOLD)
    p.add_argument("--no-batch", action="store_true")
    p.add_argument("--force-batch", action="store_true")

    # Post-generation
    p.add_argument("--verify", action="store_true",
                   help="Run `pytest --collect-only` on the output after writing.")
    p.add_argument("--with-stub", action="store_true",
                   help="Also generate a minimal solution stub scaffold.")

    # Dry-run / offline demo
    p.add_argument("--dry-run", action="store_true",
                   help="Parse the story and show batching statistics without "
                        "contacting Ollama. Useful for offline demos and CI checks.")

    return p


def main(argv=None) -> None:
    """
    CLI entry point for the test case generation tool.

    Parses arguments, reads the user story, runs the appropriate generation
    pipeline (single-shot or batched), writes output files, and optionally
    verifies with pytest.

    Args:
        argv: Argument list to parse (defaults to ``sys.argv[1:]`` when ``None``).

    Returns:
        None. Calls ``sys.exit`` on fatal errors.
    """
    args = build_arg_parser().parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"ERROR: Input file not found: {input_path}")

    story_text = input_path.read_text(encoding="utf-8")
    if not story_text.strip():
        sys.exit("ERROR: Input file is empty.")

    cfg = Config(
        input_path=str(input_path),
        output_path=args.output,
        model=args.model,
        host=args.host,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        num_predict=args.num_predict,
        connect_timeout=args.connect_timeout,
        read_timeout=args.read_timeout,
        max_conn_retries=args.max_conn_retries,
        max_retries=args.max_retries,
        batch_size=args.batch_size,
        batch_threshold=args.batch_threshold,
        no_batch=args.no_batch,
        force_batch=args.force_batch,
        verify=args.verify,
        with_stub=args.with_stub,
    )

    preamble, items = parse_acceptance_items(story_text)
    use_batch = (not cfg.no_batch) and (
        cfg.force_batch or len(items) > cfg.batch_threshold
    )

    # ------------------------------------------------------------------ #
    # DRY-RUN MODE: show parsing/batching stats, skip Ollama entirely
    # ------------------------------------------------------------------ #
    if args.dry_run:
        sep = "=" * 60
        print(sep)
        print("  AUTOMATED TEST CASE GENERATION  --  DRY-RUN MODE")
        print(sep)
        print(f"  Input file : {input_path}")
        print(f"  Preamble   : {len(preamble)} characters")
        print(f"  Acceptance criteria found: {len(items)}")
        if use_batch:
            from math import ceil
            n_batches = ceil(len(items) / cfg.batch_size)
            print(f"  Batch mode : ENABLED  (threshold={cfg.batch_threshold}, "
                  f"batch_size={cfg.batch_size})")
            print(f"  Batches    : {n_batches}")
            for i in range(n_batches):
                start = i * cfg.batch_size
                chunk = items[start:start + cfg.batch_size]
                print(f"    Batch {i + 1:>2}: {len(chunk)} criteria")
        else:
            print(f"  Batch mode : DISABLED (story is under "
                  f"threshold of {cfg.batch_threshold} criteria)")
        print()
        print("  In live mode the tool would:")
        print("    1. Send each batch to Ollama (model: "
              f"{cfg.model})")
        print("    2. Auto-heal any syntax errors (max retries: "
              f"{cfg.max_retries})")
        print("    3. AST-merge batch outputs into one clean PyTest module")
        print(f"    4. Write the suite to: {cfg.output_path}")
        print()
        print("  [dry-run] Ollama call skipped. Re-run without "
              "--dry-run to generate a real test suite.")
        print(sep)
        return

    ollama_kwargs = cfg.to_ollama_kwargs()

    try:
        if use_batch and items:
            code, valid = generate_batched(
                preamble, items, cfg.batch_size, ollama_kwargs, cfg.max_retries
            )
        else:
            code, valid = generate_single_shot(story_text, ollama_kwargs, cfg.max_retries)
    except OllamaError as exc:
        sys.exit(f"ERROR: {exc}")

    code = ensure_pytest_import(code)

    output_path = Path(cfg.output_path)
    output_path.write_text(code, encoding="utf-8")
    print(f"-> Wrote {output_path} ({'valid' if valid else 'INVALID -- needs manual fix'} syntax)")

    stats = summarize(code)
    print("-> Summary:")
    for k, v in stats.items():
        print(f"     {k}: {v}")

    if cfg.with_stub:
        try:
            stub_code, stub_valid = generate_stub(code, ollama_kwargs, cfg.max_retries)
        except OllamaError as exc:
            print(f"WARNING: could not generate stub: {exc}")
        else:
            stub_path = write_stub_module(stub_code, output_path)
            stub_path.write_text(stub_code, encoding="utf-8")
            print(f"-> Wrote {stub_path} ({'valid' if stub_valid else 'INVALID'} syntax)")

    if cfg.verify:
        print("-> Running `pytest --collect-only` to sanity-check the file...")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", str(output_path)],
            capture_output=True, text=True,
        )
        print(result.stdout[-3000:])
        if result.returncode != 0:
            print(result.stderr[-2000:])
            print(
                "NOTE: Collection errors are expected if `solution.py` "
                "doesn't exist yet -- that's normal until you implement it."
            )
