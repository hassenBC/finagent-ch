"""GPU smoke test: embed a few sentences on CUDA and print timings. Run with `make gpu-smoke`."""

import json
import time

import torch
from sentence_transformers import SentenceTransformer

assert torch.cuda.is_available(), "CUDA not available: run nvidia-smi in WSL"

sentences = [
    "passage: Vontobel's CET1 ratio stood at 20.1% at the end of the year.",
    "passage: Le résultat net de la BCV a progressé par rapport à l'exercice précédent.",
    "query: CET1 ratio Vontobel",
]
start = time.perf_counter()
model = SentenceTransformer("intfloat/multilingual-e5-small", device="cuda")
load_s = time.perf_counter() - start

start = time.perf_counter()
emb = model.encode(sentences, normalize_embeddings=True)
encode_ms = (time.perf_counter() - start) * 1000

result = {
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
    "gpu": torch.cuda.get_device_name(0),
    "vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1),
    "model_load_s": round(load_s, 1),
    "encode_ms": round(encode_ms, 1),
    "shape": list(emb.shape),
    # the query should be closer to the Vontobel passage than to the BCV one
    "sim_query_vontobel": round(float(emb[2] @ emb[0]), 4),
    "sim_query_bcv": round(float(emb[2] @ emb[1]), 4),
}
print(json.dumps(result, indent=2))
