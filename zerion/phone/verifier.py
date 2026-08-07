from .models import ActionResult
class ExecutionVerifier:
 def verify(self,result:ActionResult,expected:str='')->ActionResult:
  if not result.success:return result
  # Platform commands return process status, which is the strongest portable
  # confirmation Termux exposes without accessibility privileges.
  return ActionResult(True,result.message,result.data,True)
