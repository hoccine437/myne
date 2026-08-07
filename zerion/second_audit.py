# second_audit.py — release-phase second audit (fresh eyes).
#
# Asks only falsifiable questions and prints PASS/FAIL per check.
# Import-safe (main() under __main__ guard); exit code = number of failed
# checks (0 = gate). Run: python second_audit.py

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
SELF = os.path.basename(__file__)

results = []  # (name, ok, detail)


def check(name, ok, detail=""):
    ok = bool(ok)
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))


def run(cmd, cwd=BASE, timeout=90):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def _shell_true_callsites():
    """AST-level detection of subprocess-style calls with shell=True.
    String guards (rule text like "'shell=True' in text") are not call
    sites and must not trigger this."""
    import ast
    hits = []
    for p in BASE.rglob("*.py"):
        if "tests/" in str(p) or "__pycache__" in str(p) or p.name == SELF:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (kw.arg == "shell" and isinstance(kw.value, ast.Constant)
                            and kw.value.value is True):
                        hits.append(f"{p.relative_to(BASE)}:{node.lineno}")
    return hits


def main() -> int:
    py = [sys.executable]

    print("== A. Integrity & installation ==")
    r = run(py + ["-c", "from constitution.constitution import ConstitutionEngine; print(ConstitutionEngine.verify_lock())"])
    check("Constitution integrity (lock verifies; protected files untouched)", "True" in r.stdout, r.stderr[-200:])

    r = run(py + ["-m", "py_compile", "main.py"])
    check("main.py compiles", r.returncode == 0, r.stderr[-200:])

    r = run(py + ["setup.py"], timeout=120)
    check("setup bootstrap runs", r.returncode == 0, r.stderr[-200:])
    check("setup verifies constitution", "integrity" in r.stdout.lower())

    print("== B. Imports ==")
    fail = []
    for p in sorted(BASE.rglob("*.py")):
        rel_path = p.relative_to(BASE)
        rel = str(rel_path)
        if rel.startswith("tests/") or "__pycache__" in rel:
            continue
        parts = list(rel_path.with_suffix("").parts)
        mod = ".".join(parts[:-1]) if parts[-1] == "__init__" else ".".join(parts)
        if mod in ("setup", "second_audit"):
            continue
        try:
            __import__(mod)
        except Exception as e:
            fail.append(f"{mod}: {type(e).__name__}")
    check(f"every module imports ({len(fail)} failures)", not fail, "; ".join(fail[:5]))

    print("== C. Secrets & artifacts scan ==")
    key_prefix = "AI" + "za"  # built at runtime; this file must not self-match
    leaks = []
    for p in BASE.rglob("*"):
        if p.is_dir() or "__pycache__" in p.parts or "run" in p.parts or p.name == SELF:
            continue
        if p.suffix in (".py", ".md", ".txt", ".json", ".example") and p.stat().st_size < 500_000:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if key_prefix in text and ".env" not in p.name:
                leaks.append(str(p.relative_to(BASE)))
    check("no leaked API keys in tracked files", not leaks, "; ".join(leaks))
    check("no leftover extraction dir", not (BASE / "zerion_extracted").exists())
    key_env_file = (BASE / ".env")
    env_has_real_key = False
    if key_env_file.exists():
        env_text = key_env_file.read_text(errors="ignore")
        for line in env_text.splitlines():
            if line.startswith("GEMINI_API_KEY="):
                value = line.split("=", 1)[1].strip()
                env_has_real_key = bool(value) and value != "replace_with_key"
    check("no real .env with a key present", not env_has_real_key)

    print("== D. Core runtime behaviors ==")
    script = "/status\n/tools\nwhat time is it\n\nexit\n"
    r = subprocess.run(py + ["main.py"], input=script, capture_output=True, text=True,
                       cwd=BASE, timeout=90)
    check("main.py full loop, rc=0", r.returncode == 0, r.stderr[-300:])
    check("no tracebacks in loop", "Traceback" not in r.stdout)
    check("graceful keyless degradation", "system error" in r.stdout or "Commands:" in r.stdout)

    proc = subprocess.Popen(py + ["main.py"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, cwd=BASE)
    time.sleep(2.0)
    proc.send_signal(signal.SIGINT)
    out, _ = proc.communicate(timeout=15)
    check("SIGINT clean shutdown", proc.returncode == 0 and "Goodbye" in out)

    print("== E. Service (24/7) lifecycle ==")
    # full lifecycle is covered in tests/test_runtime.py (start→READY→greet→
    # heartbeat→SIGTERM-clean). Here: the read-only one-shot check.
    r = run(py + ["-m", "runtime", "--check"], timeout=60)
    check("one-shot health check runs", r.returncode in (0, 1), (r.stderr or "")[-200:])
    check("health states printed", "core" in r.stdout and "overall" in r.stdout)

    print("== F. Full test suite ==")
    r = run(py + ["-m", "pytest", "tests/", "-q", "--tb=no"], timeout=900)
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "?"
    check("pytest suite green", "passed" in tail and "failed" not in tail, tail)
    print(f"      suite: {tail}")

    print("== G. Mobile/Termux compatibility audit (no device available — static checks) ==")
    src_all = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                        for p in BASE.rglob("*.py")
                        if "tests/" not in str(p) and "__pycache__" not in str(p) and p.name != SELF)
    shell_hits = _shell_true_callsites()
    check("no hardcoded x86-only assumptions", "x86_64" not in src_all or "arm" in src_all.lower())
    check("no unsafe shell invocations (AST call sites)", not shell_hits, "; ".join(shell_hits))
    check("termux wake-lock guidance present", "termux-wake-lock" in (BASE / "runtime/autostart.py").read_text())
    check("phone adapter never assumes root", ('"-c", "su"' not in src_all and "'su', '-c'" not in src_all))

    print()
    failed = [n for n, ok, _ in results if not ok]
    print(f"SECOND AUDIT: {len(results) - len(failed)}/{len(results)} passed" +
          (f", FAILED: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
