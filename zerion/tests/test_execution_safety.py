import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.exec_tools import ShellExecutorTool,PythonExecutorTool
def test_execution_safety():
 assert ShellExecutorTool().execute({'command':'echo safe'}).success
 assert ShellExecutorTool().execute({'command':'echo safe | cat'}).error=='shell_syntax_disallowed'
 assert PythonExecutorTool().execute({'code':'print(2+2)'}).success
 assert PythonExecutorTool().execute({'code':'x'*20001}).error=='input_too_large'
if __name__=='__main__':test_execution_safety()
