from .manifest import UpgradeManifest
class UpgradePlanner:
 """Creates proposals only; it has no filesystem mutation capability."""
 def propose(self,reason,files,risk='low',dependencies=None,benefit='Improved maintainability',rollback='Restore staged backup',complexity='small')->UpgradeManifest:
  m=UpgradeManifest(reason,files,risk,dependencies or [],benefit,rollback,complexity);m.validate();return m
