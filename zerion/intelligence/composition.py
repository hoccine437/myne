from capabilities.manager import CapabilityManager
class CapabilityComposition:
 def __init__(self,manager=None):self.manager=manager or CapabilityManager()
 def compose(self,goal,records):
  names=[r.get('metadata',{}).get('name',r['category']) for r in records]
  strategy=' + '.join(names) or 'new capability research proposal'
  return {'goal':goal,'components':names,'strategy':strategy,'reusable':bool(names)}
 def persist_success(self,goal,composition):return self.manager.acquire(goal,composition['strategy'],['composition',*composition['components']])
