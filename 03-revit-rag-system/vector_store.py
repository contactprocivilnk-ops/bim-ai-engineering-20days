import os
import json
import math
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError("GEMINI_API_KEY not found in .env file.")

client = genai.Client(api_key=api_key)
# Using available embedding model verified from client.models.list()
EMBEDDING_MODEL = "gemini-embedding-001"

BASE_DIR = Path(__file__).resolve().parent
CHUNKS_FILE = BASE_DIR / "revit_api_chunks.json"
INDEX_FILE = BASE_DIR / "revit_vector_index.json"

def get_embedding(text: str) -> list[float]:
    """Generates a dense vector representation using gemini-embedding-001."""
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    if hasattr(response, "embedding") and response.embedding:
        return response.embedding.values
    elif hasattr(response, "embeddings") and response.embeddings:
        return response.embeddings[0].values
    raise ValueError(f"Could not extract embedding values: {response}")

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculates cosine similarity between two high-dimensional vectors."""
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

def build_vector_index():
    """Generates embeddings for all semantic chunks and saves the searchable index."""
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(f"Chunks file missing: {CHUNKS_FILE}")

    with open(CHUNKS_FILE, "r", encoding="utf-8") as f:
        chunks = json.load(f)

    print("\n" + "=" * 70)
    print(f"BUILDING VECTOR INDEX WITH MODEL: {EMBEDDING_MODEL}")
    print("=" * 70)

    index_data = []
    for item in chunks:
        print(f"  [EMBEDDING] {item['chunk_id']} ({item['class_name']})...")
        vector = get_embedding(item["content"])
        index_data.append({
            "chunk_id": item["chunk_id"],
            "class_name": item["class_name"],
            "topic": item["topic"],
            "content": item["content"],
            "embedding": vector
        })
        time.sleep(0.5)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2)

    print("-" * 70)
    print(f"[SUCCESS] Vector index generated and stored at: {INDEX_FILE}")
    print(f"Total Vectors Indexed: {len(index_data)} (Dimensions: {len(index_data[0]['embedding'])})")
    print("=" * 70 + "\n")

def search_knowledge_base(query: str, top_k: int = 2) -> list[dict]:
    """Retrieves top-k most relevant API chunks for any engineering query."""
    if not INDEX_FILE.exists():
        build_vector_index()

    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        index_data = json.load(f)

    query_vec = get_embedding(query)
    results = []

    for item in index_data:
        sim = cosine_similarity(query_vec, item["embedding"])
        results.append({
            "chunk_id": item["chunk_id"],
            "class_name": item["class_name"],
            "topic": item["topic"],
            "similarity": round(sim, 4),
            "content": item["content"]
        })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_k]

if __name__ == "__main__":
    # 1. Build Index
    build_vector_index()

    # 2. Test Semantic Search Query
    test_query = "How to safely delete empty drafting views without causing crashes"
    print(f"Test Query: '{test_query}'\n")
    matches = search_knowledge_base(test_query, top_k=2)

    for i, match in enumerate(matches, 1):
        print(f"Match #{i} (Score: {match['similarity']}):")
        print(f"  Class: {match['class_name']} | Topic: {match['topic']}")
        print(f"  Preview: {match['content'][:150]}...\n")