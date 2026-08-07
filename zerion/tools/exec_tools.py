"""Explicitly approved, bounded local execution tools.

Shell execution accepts an argument-list command string via ``shlex.split``;
operators must use dedicated tools/workflows rather than shell pipelines or
redirection. This removes shell parsing and injection from the runtime path.
"""
from __future__ import annotations
import os, shlex, subprocess, sys
from core import logging as log
from tools.base import Tool, ToolResult
_TIMEOUT_SECONDS=15; _MAX_OUTPUT_CHARS=4000; _MAX_CODE_CHARS=20_000

def _truncate(text:str)->str:return text[:_MAX_OUTPUT_CHARS]+("\n... (truncated)" if len(text)>_MAX_OUTPUT_CHARS else "")
def _limits():
 """POSIX child limits; unavailable platforms safely retain timeout bounds."""
 if os.name!='posix':return None
 def apply():
  try:
   import resource
   resource.setrlimit(resource.RLIMIT_CPU,(_TIMEOUT_SECONDS,_TIMEOUT_SECONDS+1))
   resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
   resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024*1024,16*1024*1024))
  except Exception:pass
 return apply

def _run(args:list[str], *, code=False)->ToolResult:
 if not args:return ToolResult.fail('missing_parameter','No command provided.')
 try:
  result=subprocess.run(args,capture_output=True,text=True,timeout=_TIMEOUT_SECONDS,preexec_fn=_limits(),env={'PATH':os.environ.get('PATH',''),'LANG':os.environ.get('LANG','C.UTF-8')})
  output=_truncate((result.stdout+result.stderr).strip())
  if result.returncode:return ToolResult.fail('nonzero_exit',output or f'Exited with code {result.returncode}.')
  log.info(f"approved {'Python' if code else 'command'} execution completed")
  return ToolResult.ok(output,output or '(no output)')
 except subprocess.TimeoutExpired:return ToolResult.fail('timeout',f'Timed out after {_TIMEOUT_SECONDS}s.')
 except OSError as exc:return ToolResult.fail('execution_failed',str(exc))
class PythonExecutorTool(Tool):
 name='run_python';description='Execute a short approved Python code snippet and return output.';parameters={'code':'Python source code to run'};destructive=True
 def available(self):return True
 def execute(self,parameters:dict)->ToolResult:
  code=str(parameters.get('code',''))
  if not code.strip():return ToolResult.fail('missing_parameter','No code provided.')
  if len(code)>_MAX_CODE_CHARS:return ToolResult.fail('input_too_large','Code exceeds the approved execution limit.')
  return _run([sys.executable,'-I','-c',code],code=True)
class ShellExecutorTool(Tool):
 name='run_shell';description='Execute an approved argument-list command; shell syntax is not supported.';parameters={'command':'command and arguments (no pipes, redirects, or substitutions)'};destructive=True
 def available(self):return True
 def execute(self,parameters:dict)->ToolResult:
  command=str(parameters.get('command','')).strip()
  if not command:return ToolResult.fail('missing_parameter','No command provided.')
  try:args=shlex.split(command,posix=True)
  except ValueError as exc:return ToolResult.fail('invalid_command',f'Invalid command syntax: {exc}')
  if any(token in {'|','||','&&',';','>','>>','<','`'} or '$(' in token for token in args):return ToolResult.fail('shell_syntax_disallowed','Pipes, redirects, substitutions, and shell control syntax are not supported.')
  return _run(args)
