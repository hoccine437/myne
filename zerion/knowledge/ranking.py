from __future__ import annotations
import math,time

def score(item:dict, relevance:float=0)->float:
 """Ranking combines relevance, importance, confidence, recency and use."""
 age=max(0,time.time()-item['accessed']); recency=math.exp(-age/(60*60*24*30))
 return round(.45*relevance+.22*item['importance']+.18*item['confidence']+.1*recency+.05*min(1,item['uses']/10),4)
