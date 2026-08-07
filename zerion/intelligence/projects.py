from knowledge.manager import KnowledgeManager
class ProjectContinuity:
 def __init__(self,knowledge=None):self.knowledge=knowledge or KnowledgeManager()
 def save(self,name,objectives,progress='',dependencies=None,pending=None,decisions=None):
  text=f'Project {name}. Objectives: {objectives}. Progress: {progress}. Pending: {pending or []}. Decisions: {decisions or []}.'
  return self.knowledge.store(text,'project',[name,'project'],.85,.8,{'dependencies':dependencies or [],'pending':pending or []},'project')
 def resume(self,name):return self.knowledge.searcher.search(name,5,['project'])
