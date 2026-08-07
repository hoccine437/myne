# Build and Verification

Zerion Lite has no compiled build artifact. A production candidate is prepared by installing dependencies and running syntax/regression verification.

## Prerequisites

```bash
python --version
python -m pip install -r requirements.txt
```

## Compile check

```bash
python -m compileall -q .
```

## Protected-core check

```bash
python -c "from constitution.constitution import ConstitutionEngine; print(ConstitutionEngine.verify_lock())"
```

## Full local verification

Use the commands in `QUICK_RUN.md` section 13. The suite must pass before a release artifact is tagged.

## Runtime smoke check

```bash
printf 'exit\n' | python main.py
```

## Release artifact exclusions

Do not package:

```text
.env
.zerion/
__pycache__/
knowledge/*.db
providers/provider_health.db
voice model files
speech cache files
```

## Versioning

The candidate version is stored in `VERSION`. Update `VERSION`, `CHANGELOG.md`, and `RELEASE_NOTES.md` together for a new release.
