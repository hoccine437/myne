# Runtime Pipeline Fix Report

## Symptom
A provider response of `User Safety: safe` was displayed as the assistant answer to `hi`.

## Trace evidence
A mocked trace of `llm.get_llm_output('hi', {})` returned:

```text
{'text': 'User Safety: safe'}
provider_called 1
```

This proves the pipeline did not exit before provider execution.

- **Provider call:** `llm.py:171`, `api.call_llm(rendered_system_prompt, user_prompt)`.
- **Provider return:** assigned to `content` at that same line.
- **Premature output path:** `llm.py:176–184` parsed a valid JSON envelope and returned `parsed["text"]` without applying the existing noise filter.
- The existing `_clean_plain_text()` filter was only used by the non-JSON fallback at the former line 189.

There was no premature `return`, `continue`, exception, safety gate, planner exit, or provider-router non-invocation in the demonstrated path. The provider supplied safety metadata inside valid JSON, and the structured parser treated it as user-facing text.

## Fix
- Applied `_clean_plain_text()` to structured JSON `text` responses.
- Changed all-noise cleanup to return an empty string instead of returning the original metadata.
- When a valid JSON response contains no usable text after filtering, return the safe local fallback: `Hello. How can I help?`.
- Existing JSON contract, provider API, Constitution, approval gates, planner, and memory behavior are unchanged.

## Verification
`tests/test_runtime_pipeline.py` verifies:
1. `api.call_llm` is invoked exactly once for `hi`.
2. A structured `User Safety: safe` payload becomes `Hello. How can I help?`.
3. The backward-compatible `api.call_llm` shim invokes its router facade and returns its response.

Result: `pipeline regression passed`.

## Lifecycle conclusion
For the traced request the executed path is:

```text
User input → main cognitive/memory preparation → Intent/Fast Planner
→ llm.get_llm_output → api.call_llm → provider router facade
→ provider response → structured JSON parsing → response text → main display
```

Reflection/experience/memory completion happens after normal LLM output in `main.py`; the test isolates the LLM boundary and does not claim a live provider or physical-device execution.
