"""Supervised Phase 5 façade: analyze/propose/review/test/stage; deploy requires approval."""
from pathlib import Path
import json,time
from .analyzer import CapabilityAnalyzer
from .planner import UpgradePlanner
from .reviewer import CodeReviewer
from .generator import UpgradeGenerator
from .deployment import DeploymentEngine
from testing.runner import TestRunner
class EvolutionEngine:
 def __init__(self,root):
  self.root=Path(root).resolve();self.analyzer=CapabilityAnalyzer(self.root);self.planner=UpgradePlanner();self.reviewer=CodeReviewer();self.generator=UpgradeGenerator(self.root);self.tests=TestRunner(self.root);self.deployments=DeploymentEngine(self.root)
 def analyze(self):
  report=self.analyzer.report();p=self.root/'.zerion/evolution/reports';p.mkdir(parents=True,exist_ok=True);(p/f'analysis-{int(time.time())}.json').write_text(json.dumps(report,indent=2),encoding='utf8');return report
 def prepare(self,reason,changes,**proposal):
  manifest=self.planner.propose(reason,list(changes),**proposal); review=self.reviewer.review(manifest,changes)
  if not review.approved:return manifest,review,[]
  self.generator.stage_changes(manifest,changes); results=self.tests.run(manifest.id);return manifest,review,results
 def deploy(self,manifest,tests,approved=False):return self.deployments.deploy(manifest,approved,tests)
