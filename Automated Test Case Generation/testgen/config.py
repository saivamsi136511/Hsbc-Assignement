"""
testgen/config.py
=================
CLI configuration dataclass for the test case generation tool.

Provides a single ``Config`` dataclass that collects all user-facing
settings in one place, pre-populated with the constants from
``testgen.constants``.  The CLI parser populates this from ``argparse``
and passes it down to the generation pipeline.
"""

from dataclasses import dataclass, field
from typing import Optional

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


@dataclass
class Config:
    """
    All user-configurable settings for a single test-generation run.

    This dataclass acts as a typed container for the CLI arguments so that
    the generation pipeline functions can receive a single, well-typed object
    rather than an ``argparse.Namespace`` with stringly-typed fields.

    Attributes:
        input_path:       Path to the user story / acceptance-criteria file.
        output_path:      Path for the generated PyTest file.
        model:            Ollama model name.
        host:             Ollama server base URL.
        temperature:      LLM sampling temperature.
        num_ctx:          Context window token budget.
        num_predict:      Max tokens to generate (-1 = unlimited).
        connect_timeout:  TCP connect timeout in seconds.
        read_timeout:     Read (silence) timeout in seconds per streamed token.
        max_conn_retries: Reconnection retry budget.
        max_retries:      Self-healing retry budget per syntax error.
        batch_size:       Acceptance criteria per batch in batch mode.
        batch_threshold:  Auto-switch to batch mode above this many items.
        no_batch:         Force single-shot even for large stories.
        force_batch:      Force batch mode even for small stories.
        verify:           Run ``pytest --collect-only`` after writing the file.
        with_stub:        Also generate a solution stub scaffold.
    """

    # Required
    input_path: str = ""

    # Output
    output_path: str = DEFAULT_OUTPUT_FILE

    # LLM settings
    model: str = DEFAULT_MODEL
    host: str = OLLAMA_DEFAULT_HOST
    temperature: float = DEFAULT_TEMPERATURE
    num_ctx: int = DEFAULT_NUM_CTX
    num_predict: int = DEFAULT_NUM_PREDICT

    # HTTP / retry settings
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT
    read_timeout: int = DEFAULT_READ_TIMEOUT
    max_conn_retries: int = DEFAULT_MAX_CONN_RETRIES

    # Self-healing
    max_retries: int = DEFAULT_MAX_RETRIES

    # Batching
    batch_size: int = DEFAULT_BATCH_SIZE
    batch_threshold: int = DEFAULT_BATCH_THRESHOLD
    no_batch: bool = False
    force_batch: bool = False

    # Post-generation options
    verify: bool = False
    with_stub: bool = False

    def to_ollama_kwargs(self) -> dict:
        """
        Build the keyword-argument dict expected by ``call_ollama``.

        Returns:
            A dict with keys matching the parameters of
            ``testgen.ollama_client.call_ollama``.
        """
        return {
            "model":            self.model,
            "host":             self.host,
            "temperature":      self.temperature,
            "num_ctx":          self.num_ctx,
            "num_predict":      self.num_predict,
            "connect_timeout":  self.connect_timeout,
            "read_timeout":     self.read_timeout,
            "max_conn_retries": self.max_conn_retries,
        }
