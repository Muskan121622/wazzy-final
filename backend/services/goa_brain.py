"""
Goa Brain — a local, self-contained retrieval index (RAG) that keeps LLM tokens low.

Instead of injecting the whole places table + knowledge file into every Groq call,
we embed everything into a TF-IDF vector index once, then retrieve ONLY the
top-k most relevant snippets (within a token budget) per query.

Design notes:
  • Zero heavy deps: pure-Python TF-IDF + cosine similarity (no torch/onnx), so it
    works on Python 3.14 and tight disks. The embedder is pluggable — swap in
    fastembed/sentence-transformers later by implementing _embed().
  • Index is built from: DB `places` (incl. OSM/HF/Kaggle ingested rows) + goa_knowledge.json.
  • Persisted to data/goa_brain_index.json and rebuilt when source count changes.
"""
import os
import re
import sys
import json
import math
import hashlib

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from database.db import get_connection

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
KNOWLEDGE_FILE = os.path.join(DATA_DIR, "goa_knowledge.json")
INDEX_FILE = os.path.join(DATA_DIR, "goa_brain_index.json")

_word_re = re.compile(r"[a-z0-9]+")


def _tokens(text):
    return _word_re.findall((text or "").lower())


def _doc_text(p):
    return " ".join(filter(None, [
        p.get("name", ""), p.get("area", ""), p.get("category", ""),
        "indoor" if p.get("indoor_flag") else "outdoor",
        f"{str(p.get('crowd_level', '')).lower()} crowd",
        p.get("description", ""),
    ]))


def _build_documents():
    docs = []
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM places")
    for p in [dict(r) for r in cur.fetchall()]:
        docs.append({
            "id": p["id"],
            "type": "place",
            "title": p["name"],
            "text": _doc_text(p),
            "payload": {
                "place_id": p["id"], "name": p["name"], "area": p["area"],
                "category": p["category"], "price": p.get("price"),
                "rating": p.get("rating"), "indoor": bool(p.get("indoor_flag")),
                "crowd": p.get("crowd_level"), "hours": p.get("opening_hours"),
            },
        })
    conn.close()

    if os.path.exists(KNOWLEDGE_FILE):
        try:
            with open(KNOWLEDGE_FILE, "r") as f:
                kb = json.load(f)
            for h in kb.get("host_recommendations", []):
                txt = f"{h.get('host_name','')} {h.get('property','')} {h.get('host_quote','')}"
                docs.append({
                    "id": "host_" + hashlib.md5(txt.encode()).hexdigest()[:8],
                    "type": "host_tip", "title": h.get("host_name", "Host Tip"),
                    "text": txt, "payload": {"quote": h.get("host_quote"), "place_id": h.get("recommended_place_id")},
                })
            for i, tip in enumerate(kb.get("local_tips", [])):
                docs.append({
                    "id": f"tip_{i}", "type": "local_tip", "title": "Local Tip",
                    "text": tip, "payload": {"tip": tip},
                })
        except Exception as e:
            print(f"[goa_brain] knowledge load skipped: {e}")
    return docs


class GoaBrain:
    def __init__(self):
        self.docs = []
        self.df = {}
        self.doc_tf = []
        self.idf = {}
        self.doc_norm = []
        self.ready = False

    def build(self, force=False):
        self.docs = _build_documents()
        n_docs = len(self.docs)

        # Load cache if it matches current corpus size
        if not force and os.path.exists(INDEX_FILE):
            try:
                with open(INDEX_FILE, "r") as f:
                    cached = json.load(f)
                if cached.get("count") == n_docs and cached.get("doc_ids") == [d["id"] for d in self.docs]:
                    self.df = cached["df"]
                    self._finalize_vectors()
                    return self
            except Exception:
                pass

        # Document frequency
        tokenized = []
        for d in self.docs:
            toks = _tokens(d["text"])
            tokenized.append(toks)
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1

        N = max(n_docs, 1)
        self.idf = {t: math.log((N + 1) / (dfv + 1)) + 1.0 for t, dfv in self.df.items()}

        # Term frequency vectors (raw counts stored sparse as dict)
        self.doc_tf = []
        for toks in tokenized:
            tf = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            self.doc_tf.append(tf)

        self._persist(n_docs)
        self._finalize_vectors()
        return self

    def _finalize_vectors(self):
        # Precompute L2 norms for cosine
        self.doc_norm = []
        for tf in self.doc_tf:
            s = 0.0
            for t, c in tf.items():
                w = c * self.idf.get(t, 0.0)
                s += w * w
            self.doc_norm.append(math.sqrt(s) or 1.0)
        self.ready = True

    def _persist(self, n_docs):
        try:
            with open(INDEX_FILE, "w") as f:
                json.dump({
                    "count": n_docs,
                    "doc_ids": [d["id"] for d in self.docs],
                    "df": self.df,
                }, f)
        except Exception as e:
            print(f"[goa_brain] index persist skipped: {e}")

    def search(self, query, top_k=3):
        if not self.ready:
            self.build()
        qtf = {}
        for t in _tokens(query):
            qtf[t] = qtf.get(t, 0) + 1
        qvec = {t: c * self.idf.get(t, 0.0) for t, c in qtf.items()}
        qnorm = math.sqrt(sum(w * w for w in qvec.values())) or 1.0

        scored = []
        for idx, tf in enumerate(self.doc_tf):
            dot = 0.0
            for t, w in qvec.items():
                if t in tf:
                    dot += w * (tf[t] * self.idf.get(t, 0.0))
            if dot > 0:
                sim = dot / (qnorm * self.doc_norm[idx])
                scored.append((sim, idx))
        scored.sort(key=lambda x: -x[0])
        return [(self.docs[i], round(s, 4)) for s, i in scored[:top_k]]

    def context_block(self, query, top_k=3, max_chars=700):
        """Return a compact, token-budgeted context string for the LLM."""
        hits = self.search(query, top_k=top_k)
        if not hits:
            return ""
        lines = []
        used = 0
        for doc, score in hits:
            p = doc["payload"]
            if doc["type"] == "place":
                bits = [p["name"], p["area"], p["category"],
                        "indoor" if p["indoor"] else "outdoor",
                        f"₹{p['price']}" if p.get("price") is not None else "",
                        f"⭐{p['rating']}" if p.get("rating") else "",
                        f"open {p['hours']}" if p.get("hours") else ""]
                line = "📍 " + " · ".join(filter(None, bits)) + f" [id={p['place_id']}]"
            elif doc["type"] == "host_tip":
                line = f"🏠 Host: {p.get('quote','')}"
            else:
                line = f"💡 {p.get('tip','')}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)


# module-level singleton (lazy)
_brain = None


def get_brain(force_build=False):
    global _brain
    if _brain is None or force_build:
        _brain = GoaBrain()
        _brain.build(force=force_build)
    return _brain


if __name__ == "__main__":
    b = get_brain(force_build=True)
    for q in ["quiet seafood near Baga", "rainy afternoon indoor museum", "hidden gem south goa"]:
        print(f"\n=== {q} ===")
        print(b.context_block(q))
