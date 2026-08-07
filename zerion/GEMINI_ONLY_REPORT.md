# Gemini-Only Runtime Report

## Files modified
- `config.py`
- `api.py`
- `providers/__init__.py`
- `providers/router.py`
- `providers/gemini.py`
- `.env.example`
- `setup.py`
- Gemini/provider documentation files
- `tests/test_gemini_only.py`

## Removed components
- GPT and Groq provider modules, dispatch adapter, provider health persistence, multi-provider fallback/cooldown logic, and their tests.
- OpenRouter had already been removed before this change.

## Final runtime architecture
```text
main → llm → api shim → Gemini-only router → GeminiProvider → official Google API
```

## Default model
`GEMINI_MODEL=gemini-3-flash-lite` is configured in `config.py`, `.env.example`, and setup defaults. The project uses raw official Gemini REST calls, not an installed Gemini SDK; model availability cannot be automatically validated without a configured key and a real authenticated API response. If Google rejects this identifier for an account/API version, the returned model/API diagnostic is surfaced without silently changing models.

## Configuration
```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=replace_with_key
GEMINI_MODEL=gemini-3-flash-lite
```

## Validation
- Router rejects non-Gemini provider names.
- Router verifies `GEMINI_API_KEY` before request dispatch.
- Gemini provider performs a bounded network reachability check before HTTPS request.
- Runtime provider/API validation remains unverified without a configured real account.
