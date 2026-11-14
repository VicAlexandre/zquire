import jsonschema
import pytest

from zquire import __version__
from zquire.errors import ZquireError
from zquire.tools import TOOLS, invoke


def test_status_reports_version():
    assert invoke(TOOLS["status"], {}) == {"zquire_version": __version__}


@pytest.mark.parametrize(
    "arguments",
    [{}, {"text": 1}, {"text": "a", "extra": 1}, {"text": "a", "repeat_count": "2"}],
    ids=["missing-required", "wrong-type", "unexpected-property", "string-for-integer"],
)
def test_invalid_arguments_are_rejected_before_the_handler(fake_tools, arguments):
    with pytest.raises(ZquireError) as raised:
        invoke(fake_tools["echo"], arguments)
    assert raised.value.code == "INVALID_ARGUMENT"


def test_invalid_argument_message_names_the_offending_path(fake_tools):
    with pytest.raises(ZquireError) as raised:
        invoke(fake_tools["echo"], {"text": "a", "repeat_count": "2"})
    assert raised.value.message.startswith("$.repeat_count:")


def test_valid_arguments_reach_the_handler(fake_tools):
    assert invoke(fake_tools["echo"], {"text": "ab", "repeat_count": 2}) == {"text": "abab"}


def test_result_violating_output_schema_is_a_fault(fake_tools):
    with pytest.raises(jsonschema.ValidationError):
        invoke(fake_tools["bad_output"], {})


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        (None, {"code": "C", "message": "m"}),
        ("try x", {"code": "C", "message": "m", "hint": "try x"}),
        ("", {"code": "C", "message": "m", "hint": ""}),
    ],
    ids=["no-hint", "hint", "empty-hint"],
)
def test_error_payload(hint, expected):
    assert ZquireError("C", "m", hint).to_dict() == expected
