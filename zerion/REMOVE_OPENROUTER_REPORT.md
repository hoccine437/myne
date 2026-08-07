# OpenRouter Removal Report

## Files modified
- `config.py`
- `api.py`
- `providers/__init__.py`
- `providers/router.py`
- `providers/gpt.py`
- `providers/openrouter.py` (removed)
- `providers/deepseek.py` (removed; only Gemini and retired provider remain official)
- `README.md`
- `REQUIREMENTS.md`
- `QUICK_RUN.md`
- `PROJECT_STRUCTURE.md`
- `RELEASE_NOTES.md`
- historical/report documents with retired-provider references

## Removed components
- OpenRouter provider implementation and registry entry.
- OpenRouter URL/model/API-key configuration.
- OpenRouter environment variables and documentation.
- DeepSeek runtime provider implementation and registry entry, because the requested official provider set contains Gemini and retired provider only.
- `api.call_openrouter()` compatibility function was removed with OpenRouter support.

## Updated provider flow
```text
LLM_PROVIDER defaults to gemini
Gemini → Execution Resolver / Provider Dispatch / health tracking
      → retired provider fallback on non-consequential provider failure
```

Official configuration:
```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=replace_with_key
```

`retired provider_API_KEY` remains a configuration alias for `OPENAI_API_KEY` only to preserve existing local environment compatibility; official documentation uses `OPENAI_API_KEY`.

## Test results
- Compilation passed.
- Provider dispatch mock regression passed.
- Runtime pipeline regression passed.
- Memory, reasoning, phone, execution safety, voice fallback, hardening, Constitution, intelligence, capability, Phase 4 and Phase 5 regressions passed.

Result: `gemini gpt regression passed`.

## Active runtime confirmation
Static repository search found no remaining `openrouter`, `OPENROUTER`, or `OpenRouter` reference. `providers.router` registers only `gemini` and `gpt`; `config._SUPPORTED_PROVIDERS` contains only `gemini` and `gpt`; default `LLM_PROVIDER` is `gemini`.

## Verification boundary
Live Gemini→retired provider failover has not been physically validated with configured accounts. Resolver/dispatch fallback is mock-tested; no real API request is claimed.
