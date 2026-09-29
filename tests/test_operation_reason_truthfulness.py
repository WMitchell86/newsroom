"""V1.2-G4.10 — a row that did not fail must not carry a failure sentence.

Found in a self-review pass, on the live system: four operations with
`status: succeeded` were returned by GET /operations carrying
«Операцията не можа да завърши поради технически проблем.» The editor is
told the work failed while the result sits right there.

`_editor_reason` returned that sentence for any row without an error code,
and a successful row has no error code — so "no code" was read as "failure
whose cause was unobserved" when it actually meant "nothing went wrong".
"""

from editor_assistant.workflow import story_operations


def test_a_succeeded_row_has_no_reason():
    assert story_operations._editor_reason({"status": "succeeded", "result": {"id": "x"}}) == ""


def test_a_running_row_has_no_reason():
    assert story_operations._editor_reason({"status": "running"}) == ""


def test_a_pending_row_has_no_reason():
    assert story_operations._editor_reason({"status": "pending"}) == ""


def test_a_failed_row_without_a_code_keeps_the_unobserved_sentence():
    # This is the case the constant was written for, and it must survive.
    reason = story_operations._editor_reason({"status": "failed", "error_code": ""})
    assert "не можа да завърши" in reason


def test_a_failed_row_with_a_code_carries_the_real_reason():
    reason = story_operations._editor_reason({
        "status": "failed", "error_code": "QUOTA_EXHAUSTED", "error": "Quota spent.",
    })
    assert "Quota spent." in reason
