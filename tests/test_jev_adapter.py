"""M3J Part B/J: offline tests for the thin Jev adapter.

The SDK is never installed in tests - a fake module/client stands in. The
adapter must (a) report capability-unavailable explicitly, (b) build typed
questions, (c) preserve probabilities/confidence, (d) map provider failures
(redacting the key), and (e) never grant Jev editorial authority.
"""

import pytest

from editor_assistant.workflow import jev


class FakeChoice:
    def __init__(self, instructions, criteria):
        self.instructions = instructions
        self.criteria = criteria


class FakeNoul:
    def __init__(self, instructions):
        self.instructions = instructions


class FakeScore:
    def __init__(self, instructions, criteria):
        self.instructions = instructions
        self.criteria = criteria


class FakeSDK:
    Choice = FakeChoice
    Noul = FakeNoul
    Score = FakeScore

    def __init__(self):
        self.last_client_kwargs = None

    def TypeSafeClient(self, **kwargs):
        self.last_client_kwargs = kwargs
        return object()


class FakeClient:
    def __init__(self, response=None, error=None, sink=None):
        self._response = response
        self._error = error
        self._sink = sink if sink is not None else {}

    def system_one(self, **kwargs):
        self._sink.update(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _choice_response():
    return {
        "model": "jev-1.13.0",
        "choices": {
            "support_relation": {
                "choice": "PARTIAL_SUPPORT",
                "probabilities": {
                    "EXACT_SUPPORT": 0.10,
                    "PARTIAL_SUPPORT": 0.82,
                    "NOT_ADDRESSED": 0.05,
                    "CONTRADICTED": 0.03,
                },
                "confidence": 0.82,
            }
        },
        "usage": {"input_tokens": 120, "output_tokens": 9},
    }


def test_missing_sdk_is_capability_unavailable(monkeypatch):
    monkeypatch.setattr(jev, "load_sdk", lambda: None)
    with pytest.raises(jev.JevCapabilityUnavailable) as exc:
        jev.evaluate({"claim": "x"}, {}, env={"TYPESAFE_API_KEY": "k"})
    assert exc.value.code == jev.JEV_CAPABILITY_UNAVAILABLE
    assert "not installed" in str(exc.value)


def test_missing_key_is_capability_unavailable():
    with pytest.raises(jev.JevCapabilityUnavailable) as exc:
        jev.evaluate({"claim": "x"}, {}, env={}, sdk=FakeSDK())
    assert exc.value.code == jev.JEV_CAPABILITY_UNAVAILABLE
    assert jev.TYPESAFE_API_KEY_ENV in str(exc.value)


def test_typed_questions_are_built_with_the_right_shape():
    specs = {
        "support_relation": jev.question(
            jev.QUESTION_CHOICE,
            "Does the passage support the claim?",
            ("EXACT_SUPPORT", "PARTIAL_SUPPORT", "NOT_ADDRESSED", "CONTRADICTED"),
        ),
        "is_public": jev.question(jev.QUESTION_NOUL, "Is the source public?"),
        "strength": jev.question(
            jev.QUESTION_SCORE, "How strong is support?", ["weak", "medium", "strong"]
        ),
    }
    built = jev.build_sdk_questions(specs, FakeSDK())
    assert set(built["support_relation"].criteria) == {
        "EXACT_SUPPORT",
        "PARTIAL_SUPPORT",
        "NOT_ADDRESSED",
        "CONTRADICTED",
    }
    assert all(value is None for value in built["support_relation"].criteria.values())
    assert built["is_public"].instructions == "Is the source public?"
    assert built["strength"].criteria == ["weak", "medium", "strong"]


def test_question_validation_rejects_bad_specs():
    with pytest.raises(jev.JevError):
        jev.question("vibes", "?")
    with pytest.raises(jev.JevError):
        jev.question(jev.QUESTION_CHOICE, "?", ("only-one",))
    with pytest.raises(jev.JevError):
        jev.question(jev.QUESTION_NOUL, "?", ("yes", "no"))


def test_evaluate_preserves_probabilities_and_effective_model():
    client = FakeClient(_choice_response())
    specs = {"support_relation": jev.question(jev.QUESTION_CHOICE, "?", ("A", "B"))}
    record = jev.evaluate(
        {"claim": "x"},
        specs,
        env={"TYPESAFE_API_KEY": "k", "JEV_MODEL": "jev-latest"},
        client=client,
        sdk=FakeSDK(),
    )
    assert record["status"] == jev.JEV_OK
    assert record["model_requested"] == "jev-latest"
    assert record["model_effective"] == "jev-1.13.0"
    answer = record["answers"]["support_relation"]
    assert answer["answer"] == "PARTIAL_SUPPORT"
    assert answer["probabilities"]["PARTIAL_SUPPORT"] == 0.82
    assert answer["confidence"] == 0.82
    assert record["usage"]["input_tokens"] == 120
    assert isinstance(record["latency_ms"], int)


def test_default_model_alias_is_jev_latest():
    assert jev.model_alias(env={}) == "jev-latest"
    assert jev.model_alias(env={"JEV_MODEL": "  "}) == "jev-latest"
    assert jev.model_alias(env={"JEV_MODEL": "jev-1.13.0"}) == "jev-1.13.0"


def test_provider_failure_is_mapped_and_key_redacted():
    client = FakeClient(error=RuntimeError("boom with sk-secret inside"))
    with pytest.raises(jev.JevProviderError) as exc:
        jev.evaluate(
            {"claim": "x"},
            {},
            env={"TYPESAFE_API_KEY": "sk-secret"},
            client=client,
            sdk=FakeSDK(),
        )
    assert exc.value.code == jev.JEV_PROVIDER_ERROR
    assert "sk-secret" not in str(exc.value)
    assert "<redacted>" in str(exc.value)


def test_build_client_returns_none_without_key_or_sdk(monkeypatch):
    monkeypatch.setattr(jev, "load_sdk", lambda: None)  # SDK present or not
    assert jev.build_client(sdk=None, env={"TYPESAFE_API_KEY": "k"}) is None
    assert jev.build_client(sdk=FakeSDK(), env={}) is None
    assert jev.build_client(sdk=FakeSDK(), env={"TYPESAFE_API_KEY": "k"}) is not None


def test_effective_model_falls_back_when_response_omits_it():
    client = FakeClient({"choices": {}})
    record = jev.evaluate({"x": 1}, {}, env={"TYPESAFE_API_KEY": "k"}, client=client, sdk=FakeSDK())
    assert record["model_effective"] == "jev-latest"


def test_adapter_is_not_wired_into_production_deciders():
    """Authority regression: Jev is reachable only through the eval runner."""
    root = __import__("pathlib").Path(__file__).resolve().parents[1] / "src" / "editor_assistant"
    protected = [
        root / "workflow" / "readiness.py",
        root / "workflow" / "angles.py",
        root / "workflow" / "discovery.py",
        root / "workflow" / "cases.py",
    ]
    for path in protected:
        text = path.read_text(encoding="utf-8").lower()
        assert "jev" not in text, f"Jev must not be referenced from {path.name}"

    # ...and the adapter module itself must not import any decider.
    adapter = (root / "workflow" / "jev.py").read_text(encoding="utf-8")
    for forbidden in ("readiness", "angles", "discovery", "cases"):
        assert f"workflow.{forbidden}" not in adapter
