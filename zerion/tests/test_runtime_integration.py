import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intelligence.runtime import RuntimeIntelligence
def test_runtime_lifecycle():
 runtime=RuntimeIntelligence();ctx=runtime.prepare('integration goal',[])
 assert ctx['composition']['strategy'] and ctx['resolver_decision'].selected=='normal_reasoning'
 reflection=runtime.complete('integration goal','done',.01,[])
 assert reflection.update_memory and runtime.quality.get('llm')['uses']==1
 assert runtime.world.related('goal:integration goal')
if __name__=='__main__':test_runtime_lifecycle()
