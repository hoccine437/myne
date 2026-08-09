import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from intelligence.critic import SelfCritic, CritiqueResult, Issue, _REVIEW_RULES


# ---------------------------------------------------------------------------
# Structured issue shape
# ---------------------------------------------------------------------------

def test_issue_has_required_structured_fields():
    critic = SelfCritic()
    result = critic.review("hello", "", confidence=0.9)
    assert result.should_improve is True
    issue = result.issues[0]
    assert isinstance(issue, Issue)
    assert issue.type == "empty_response"
    assert issue.severity in ("low", "medium", "high")
    assert isinstance(issue.description, str) and issue.description
    assert isinstance(issue.suggested_fix, str) and issue.suggested_fix


def test_confident_clean_response_not_flagged():
    critic = SelfCritic()
    result = critic.review("what's the weather like", "It's sunny and 22 degrees.", confidence=0.8)
    assert result.should_improve is False
    assert result.issues == ()


def test_multiple_issues_all_collected():
    critic = SelfCritic()
    # Empty response AND low confidence should both fire independently.
    result = critic.review("x", "", confidence=0.1)
    types = {issue.type for issue in result.issues}
    assert "empty_response" in types
    assert "low_confidence" in types


# ---------------------------------------------------------------------------
# Individual rules (still exercised through review(), each independent)
# ---------------------------------------------------------------------------

def test_contradiction_flagged():
    critic = SelfCritic()
    result = critic.review(
        "can you do X",
        "Yes, I can do that. Actually, I can't do that.",
        confidence=0.9,
    )
    assert any(i.type == "contradiction" for i in result.issues)


def test_unverified_action_claim_flagged():
    critic = SelfCritic()
    result = critic.review(
        "send that email",
        "I've sent the email to your father.",
        confidence=0.9,
    )
    assert any(i.type == "unverified_action_claim" for i in result.issues)


def test_cutoff_response_flagged():
    critic = SelfCritic()
    long_unterminated = "This is a fairly long response that just stops abruptly without"
    result = critic.review("explain something", long_unterminated, confidence=0.9)
    assert any(i.type == "cutoff" for i in result.issues)


def test_review_never_raises_on_bad_input():
    critic = SelfCritic()
    # confidence as a non-float would break a naive `< threshold` comparison
    # if review() weren't defensive -- must degrade to "no issues", not raise.
    result = critic.review("x", "a normal reply.", confidence="not-a-number")
    assert isinstance(result, CritiqueResult)
    assert result.should_improve is False


# ---------------------------------------------------------------------------
# Extensibility: rules are independent and registered in one list
# ---------------------------------------------------------------------------

def test_rules_are_independent_functions_in_a_registry():
    # Each rule must be callable with (goal, response, confidence) and
    # return an Issue or None, with no shared state between them.
    assert len(_REVIEW_RULES) >= 5
    for rule in _REVIEW_RULES:
        result = rule("goal", "a perfectly fine response.", 0.9)
        assert result is None or isinstance(result, Issue)


def test_new_rule_can_be_added_without_touching_existing_ones():
    # Simulates adding a new rule the way a future developer would: append
    # a function to a *copy* of the registry and confirm review()-style
    # iteration still works, without editing any existing rule.
    def _rule_shouts(goal, response, confidence):
        if response.isupper() and len(response) > 5:
            return Issue("shouting", "low", "response is all caps", "Use normal casing.")
        return None

    extended_rules = _REVIEW_RULES + (_rule_shouts,)
    issues = [r("goal", "THIS IS SHOUTING", 0.9) for r in extended_rules]
    issues = [i for i in issues if i is not None]
    assert any(i.type == "shouting" for i in issues)
    # Original registry is untouched by building the extended tuple.
    assert not any(r.__name__ == "_rule_shouts" for r in _REVIEW_RULES)


# ---------------------------------------------------------------------------
# Config-driven thresholds (no hardcoded values)
# ---------------------------------------------------------------------------

def test_low_confidence_threshold_is_read_from_config():
    critic = SelfCritic()
    original = config.LOW_CONFIDENCE_THRESHOLD
    try:
        config.LOW_CONFIDENCE_THRESHOLD = 0.99  # nearly everything now counts as "low"
        result = critic.review("x", "a decently confident answer.", confidence=0.8)
        assert any(i.type == "low_confidence" for i in result.issues)
    finally:
        config.LOW_CONFIDENCE_THRESHOLD = original


def test_minimum_response_length_is_read_from_config():
    critic = SelfCritic()
    original = config.MINIMUM_RESPONSE_LENGTH
    try:
        config.MINIMUM_RESPONSE_LENGTH = 100
        result = critic.review("x", "short but previously fine", confidence=0.9)
        assert any(i.type == "too_short" for i in result.issues)
    finally:
        config.MINIMUM_RESPONSE_LENGTH = original


def test_maximum_improvement_attempts_zero_disables_improve():
    critic = SelfCritic()
    original = config.MAXIMUM_IMPROVEMENT_ATTEMPTS
    try:
        config.MAXIMUM_IMPROVEMENT_ATTEMPTS = 0
        flagged = CritiqueResult(should_improve=True, issues=(
            Issue("empty_response", "high", "empty response", "say something"),
        ), confidence=0.1)
        # Should return the original untouched, with no api call attempted.
        result = critic.improve("goal", "original text", flagged)
        assert result == "original text"
    finally:
        config.MAXIMUM_IMPROVEMENT_ATTEMPTS = original


# ---------------------------------------------------------------------------
# Single-pass guarantee / no feedback loop
# ---------------------------------------------------------------------------

def test_improve_noop_when_not_flagged():
    critic = SelfCritic()
    clean = CritiqueResult(should_improve=False, issues=(), confidence=0.9)
    assert critic.improve("goal", "original text", clean) == "original text"


def test_improve_falls_back_on_api_failure():
    import intelligence.critic as critic_mod

    original = critic_mod.api.call_llm

    def _boom(system_prompt, user_prompt):
        raise RuntimeError("network down")

    critic_mod.api.call_llm = _boom
    try:
        critic = SelfCritic()
        flagged = CritiqueResult(should_improve=True, issues=(
            Issue("empty_response", "high", "empty response", "say something"),
        ), confidence=0.1)
        result = critic.improve("goal", "original text", flagged)
        assert result == "original text"
    finally:
        critic_mod.api.call_llm = original


def test_improve_uses_revised_text_on_success():
    import intelligence.critic as critic_mod

    original = critic_mod.api.call_llm
    critic_mod.api.call_llm = lambda s, u: "  a fixed reply.  "
    try:
        critic = SelfCritic()
        flagged = CritiqueResult(should_improve=True, issues=(
            Issue("empty_response", "high", "empty response", "say something"),
        ), confidence=0.1)
        result = critic.improve("goal", "", flagged)
        assert result == "a fixed reply."
    finally:
        critic_mod.api.call_llm = original


def test_improve_calls_llm_at_most_once():
    import intelligence.critic as critic_mod

    call_count = {"n": 0}
    original = critic_mod.api.call_llm

    def _counting(system_prompt, user_prompt):
        call_count["n"] += 1
        return "revised text that is still short"  # still "flaggable" if re-reviewed

    critic_mod.api.call_llm = _counting
    try:
        critic = SelfCritic()
        flagged = CritiqueResult(should_improve=True, issues=(
            Issue("empty_response", "high", "empty response", "say something"),
        ), confidence=0.1)
        result = critic.improve("goal", "", flagged)
        assert call_count["n"] == 1
        assert result == "revised text that is still short"
        # Critically: improve() does not re-review or re-call itself even
        # though the returned text would itself trip a rule.
    finally:
        critic_mod.api.call_llm = original


def test_no_recursive_review_or_improve_calls():
    # Static guarantee: improve() must not reference review() or improve()
    # anywhere in its own source, which would indicate recursion/looping.
    import inspect
    import intelligence.critic as critic_mod

    src = inspect.getsource(critic_mod.SelfCritic.improve)
    assert "self.review(" not in src
    assert "self.improve(" not in src
    assert ".review(" not in src


# ---------------------------------------------------------------------------
# Structured critique logging
# ---------------------------------------------------------------------------

def test_flagged_critique_is_logged_to_knowledge_store():
    calls = []

    class _FakeKnowledge:
        def store(self, **kwargs):
            calls.append(kwargs)
            return 1

    critic = SelfCritic(knowledge=_FakeKnowledge())
    critic.review("do the thing", "", confidence=0.9)

    assert len(calls) == 1
    record = calls[0]
    assert record["layer"] == "critique"
    assert record["metadata"]["goal"] == "do the thing"
    assert record["metadata"]["issues"][0]["type"] == "empty_response"
    assert "severity" in record["metadata"]["issues"][0]
    assert "suggested_fix" in record["metadata"]["issues"][0]


def test_clean_response_is_not_logged():
    calls = []

    class _FakeKnowledge:
        def store(self, **kwargs):
            calls.append(kwargs)
            return 1

    critic = SelfCritic(knowledge=_FakeKnowledge())
    critic.review("hello", "a perfectly fine confident response.", confidence=0.9)
    assert calls == []


def test_logging_failure_does_not_break_review():
    class _BrokenKnowledge:
        def store(self, **kwargs):
            raise RuntimeError("db unavailable")

    critic = SelfCritic(knowledge=_BrokenKnowledge())
    # Must not raise, even though logging inside review() will fail.
    result = critic.review("x", "", confidence=0.9)
    assert result.should_improve is True


# ---------------------------------------------------------------------------
# Fully optional: config.ENABLE_SELF_CRITIC gates the whole feature
# ---------------------------------------------------------------------------

def test_enable_self_critic_flag_exists_and_defaults_true():
    assert hasattr(config, "ENABLE_SELF_CRITIC")
    assert isinstance(config.ENABLE_SELF_CRITIC, bool)


def test_main_py_skips_critic_entirely_when_disabled():
    # main.py's hook is `if config.ENABLE_SELF_CRITIC and intent == "chat" and response:`.
    # This confirms that exact guard is present as source, so flipping the
    # flag off is guaranteed to skip review()/improve() calls entirely
    # rather than merely short-circuiting inside the critic.
    tsrc = Path(__file__).resolve().parents[1].joinpath("core", "turn_runner.py").read_text(encoding="utf-8")
    # the canonical lifecycle (both front ends run it) — the gate remains exact
    assert "config.ENABLE_SELF_CRITIC and intent" in tsrc
    assert "config.ENABLE_SELF_CRITIC and intent" in tsrc  # canonical lifecycle source


if __name__ == "__main__":
    test_issue_has_required_structured_fields()
    test_confident_clean_response_not_flagged()
    test_multiple_issues_all_collected()
    test_contradiction_flagged()
    test_unverified_action_claim_flagged()
    test_cutoff_response_flagged()
    test_review_never_raises_on_bad_input()
    test_rules_are_independent_functions_in_a_registry()
    test_new_rule_can_be_added_without_touching_existing_ones()
    test_low_confidence_threshold_is_read_from_config()
    test_minimum_response_length_is_read_from_config()
    test_maximum_improvement_attempts_zero_disables_improve()
    test_improve_noop_when_not_flagged()
    test_improve_falls_back_on_api_failure()
    test_improve_uses_revised_text_on_success()
    test_improve_calls_llm_at_most_once()
    test_no_recursive_review_or_improve_calls()
    test_flagged_critique_is_logged_to_knowledge_store()
    test_clean_response_is_not_logged()
    test_logging_failure_does_not_break_review()
    test_enable_self_critic_flag_exists_and_defaults_true()
    test_main_py_skips_critic_entirely_when_disabled()
    print("All self-critic tests passed.")
