# mcp/servers/knowledge.py
"""Knowledge adapter: search/retrieve against the canonical knowledge DB.
A REAL read of the store — wrapped because the agent lane must be able to
reach it without touching the DB handle directly."""

from knowledge.manager import KnowledgeManager


def _search(parameters):
    query = str((parameters or {}).get("query", ""))
    limit = min(int((parameters or {}).get("limit", 5) or 5), 10)
    try:
        km = KnowledgeManager()
        rows = km.searcher.search(query, limit)
        return {"success": True, "data": [
            {"layer": r["layer"], "category": r["category"],
             "content": r["content"][:400], "confidence": r["confidence"]}
            for r in rows]}
    except Exception as e:
        return {"success": False, "error": f"knowledge search failed: {e}"}


def _summary(parameters):
    try:
        km = KnowledgeManager()
        n = km.db.query("SELECT COUNT(*) AS n FROM records")[0]["n"]
        layers = [dict(r) for r in km.db.query(
            "SELECT layer, COUNT(*) AS n FROM records GROUP BY layer")]
        return {"success": True, "data": {"records": n, "by_layer": layers}}
    except Exception as e:
        return {"success": False, "error": str(e)}


SERVER = {
    "name": "knowledge",
    "lifecycle": "in-process",
    "capabilities": {
        "knowledge.search":  {"handler": _search,  "kind": "read", "timeout_s": 10,
                              "retry": "transient"},
        "knowledge.summary": {"handler": _summary, "kind": "read", "timeout_s": 5},
    },
}
