"""Ranked long-term memory, additive beside the legacy Memory API."""
from knowledge.manager import KnowledgeManager
class LongTermMemory:
 def __init__(self, manager=None):self.manager=manager or KnowledgeManager()
 def remember(self,text,category='fact',tags=None,importance=.5,confidence=.7):return self.manager.store(text,category,tags or [],importance,confidence,layer='long_term')
 def recall(self,query,limit=5):return self.manager.searcher.search(query,limit,['long_term'])
