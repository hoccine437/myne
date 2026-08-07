# skills/domains.py
"""Additional domain skill packs (Phase-5 verification surface).

A skill here is a real, routable domain pack: name, routing keywords,
focus areas, representative example tasks, and cautions the Core should
keep visible when working in the domain. They plug into the existing
Skill dataclass/SkillManager — nothing new competes with them.

The four legacy domains (software_engineering, financial_markets,
electronics, human_knowledge) stay defined in their original modules;
this file only ADDS domains.
"""

from skills.base import Skill


def _pack(name, keywords, focus, examples, cautions=()):
    prompt = f"You are assisting in the {name} domain. Focus: {focus}. " + (
        f"Cautions: {'; '.join(cautions)}. " if cautions else "") + "Be precise and honest about uncertainty."
    return Skill(
        name=name,
        knowledge_categories=tuple(keywords),
        prompt=prompt,
        reasoning_rules=tuple(list(examples) + list(cautions)),
        preferred_tools=("skill_route", "read_file", "search_files"),
    )


ADDITIONAL_DOMAINS: tuple[Skill, ...] = (
    _pack("mathematics",
          ["math", "equation", "algebra", "calculus", "integral", "derivative", "proof", "matrix", "probability", "statistics"],
          "exact calculation, proof structure, estimation sanity",
          ["compute 12 * (3 + 4)", "solve x^2 - 5x + 6 = 0", "estimate a probability from observations"],
          ["show the calculation instead of asserting the result"]),
    _pack("physics",
          ["physics", "force", "energy", "velocity", "momentum", "thermodynamics", "quantum", "wavelength"],
          "units, orders of magnitude, conservation laws",
          ["compute kinetic energy of a 2kg mass at 10 m/s"],
          ["verify the units before concluding"]),
    _pack("chemistry",
          ["chemistry", "reaction", "mole", "acid", "compound", "oxidation", "stoichiometry"],
          "balanced equations, molar bookkeeping, safety flags",
          ["balance a redox equation"],
          ["flag hazardous reagents explicitly"]),
    _pack("health_information",
          ["symptom", "health", "medicine", "dosage", "disease", "nutrition", "vaccine"],
          "general information, reputable-source framing, red-flag escalation",
          ["explain what ibuprofen does"],
          ["this is general information, not medical advice", "urge professional care for urgent symptoms"]),
    _pack("legal_information",
          ["law", "contract", "regulation", "gdpr", "license", "copyright", "liability"],
          "concepts and structure, jurisdiction caveats",
          ["explain what an MIT license permits"],
          ["not legal advice; jurisdiction matters"]),
    _pack("culinary",
          ["recipe", "cook", "bake", "ingredient", "oven", "marinate", "sauté"],
          "ratios, temperatures, substitutions, food-safety temps",
          ["suggest a substitution for butter in this recipe"]),
    _pack("languages",
          ["translate", "grammar", "conjugate", "language", "french", "spanish", "arabic"],
          "faithful translation, register, false friends",
          ["translate 'welcome home' into French"]),
    _pack("history",
          ["history", "empire", "war", "century", "dynasty", "ancient", "revolution"],
          "dates, causation, source criticism",
          ["summarize the causes of the First World War"]),
    _pack("mechanical_engineering",
          ["gear", "torque", "bearing", "cad", "stress", "actuator", "bolts"],
          "loads, tolerances, materials",
          ["compute the torque needed to turn this shaft"],
          ["respect safety factors"]),
    _pack("writing",
          ["essay", "blog", "story", "rewrite", "edit", "poem", "headline"],
          "clarity, structure, voice, revision passes",
          ["tighten this paragraph without changing its meaning"]),
)

ADDITIONAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    s.name: s.knowledge_categories for s in ADDITIONAL_DOMAINS
}
