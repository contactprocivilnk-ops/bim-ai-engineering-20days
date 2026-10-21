import json
from pathlib import Path
from dataclasses import dataclass, asdict

BASE_DIR = Path(__file__).resolve().parent
SEEDS_FILE = BASE_DIR / "revit_api_seeds.json"
CHUNKS_FILE = BASE_DIR / "revit_api_chunks.json"

@dataclass
class DocumentChunk:
    chunk_id: str
    topic: str
    class_name: str
    namespace: str
    content: str
    metadata: dict

def create_semantic_chunks() -> list[dict]:
    """Transforms raw Revit API seeds into dense contextual text chunks for embedding."""
    if not SEEDS_FILE.exists():
        raise FileNotFoundError(f"Missing seeds file at: {SEEDS_FILE}")

    with open(SEEDS_FILE, "r", encoding="utf-8") as f:
        seeds = json.load(f)

    chunks = []
    print("\n" + "=" * 70)
    print(" PROCESSING REVIT API KNOWLEDGE BASE CHUNKS")
    print("=" * 70)

    for idx, item in enumerate(seeds, start=1):
        # Format dense text representation for semantic retrieval
        content = (
            f"Topic: {item['topic']}\n"
            f"Class: {item['class_name']} (Namespace: {item['namespace']})\n"
            f"Summary: {item['summary']}\n"
            f"Code Pattern:\n{item['syntax_pattern']}\n"
            f"Best Practices: {item['best_practices']}\n"
            f"Common Pitfalls: {item['common_pitfalls']}"
        )

        chunk = DocumentChunk(
            chunk_id=f"chunk_revit_api_{idx:03d}",
            topic=item["topic"],
            class_name=item["class_name"],
            namespace=item["namespace"],
            content=content,
            metadata={
                "has_code_sample": bool(item.get("syntax_pattern")),
                "length_chars": len(content),
            }
        )
        chunks.append(asdict(chunk))
        print(f"  [PROCESSED] {chunk.chunk_id} -> {chunk.class_name} ({chunk.metadata['length_chars']} chars)")

    # Save output to chunks JSON
    with open(CHUNKS_FILE, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2)

    print("-" * 70)
    print(f"[SUCCESS] Saved {len(chunks)} semantic chunks to: {CHUNKS_FILE}")
    print("=" * 70 + "\n")
    return chunks

if __name__ == "__main__":
    create_semantic_chunks()