from dataclasses import dataclass,field
@dataclass(frozen=True)
class Skill:
 name:str; knowledge_categories:tuple[str,...]; prompt:str; reasoning_rules:tuple[str,...]; preferred_tools:tuple[str,...]=(); learning_history:tuple[str,...]=field(default_factory=tuple)
