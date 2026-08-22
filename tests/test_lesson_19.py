import subprocess
import sys

import pytest
from pydantic import ValidationError

from order_assistant.config import Settings


def test_lesson_19_import_is_silent() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_19"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "" and result.stderr == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_max_concurrency", 0),
        ("llm_queue_capacity", -1),
        ("llm_queue_wait_timeout_seconds", 0),
        ("llm_circuit_failure_threshold", 0),
        ("llm_circuit_open_seconds", 0),
        ("llm_circuit_half_open_max_calls", 0),
        ("llm_transport_max_attempts", 0),
    ],
)
def test_runtime_settings_reject_invalid_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
