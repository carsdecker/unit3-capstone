"""
onnx_embed.py -- embeddings via ONNX Runtime, replacing sentence-transformers.
(Course file from Deployment Patterns on AWS, unchanged.)

WHY THIS EXISTS: sentence-transformers depends on PyTorch, whose core
runtime library alone (libtorch_cpu.so, ~418MB) already exceeds Lambda's
250MB unzipped package limit before adding anything else. This module
reimplements the same all-MiniLM-L6-v2 embedding pipeline using onnxruntime
and tokenizers instead.

CORRECTNESS: the course verified this against SentenceTransformer("all-MiniLM-L6-v2")
-- cosine similarity >0.9999999. It must produce vectors equivalent to whatever
populated the OpenSearch index, so this project uses it for ingestion AND queries.

REQUIRED FILES (download separately; both must sit in the same directory as this file):
  - model.onnx     (~87MB)
  - tokenizer.json (~456KB)
"""
import os
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

_MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
_MODEL_PATH = os.path.join(_MODEL_DIR, "model.onnx")
_TOKENIZER_PATH = os.path.join(_MODEL_DIR, "tokenizer.json")

_session = None
_tokenizer = None


def _get_session():
    global _session
    if _session is None:
        _session = ort.InferenceSession(_MODEL_PATH, providers=["CPUExecutionProvider"])
    return _session


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer.from_file(_TOKENIZER_PATH)
        _tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        _tokenizer.enable_truncation(max_length=256)
    return _tokenizer


def _mean_pooling(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    """Replicates sentence-transformers' mean pooling exactly."""
    mask_expanded = np.expand_dims(attention_mask, -1).astype(np.float32)
    mask_expanded = np.broadcast_to(mask_expanded, token_embeddings.shape)
    summed = np.sum(token_embeddings * mask_expanded, axis=1)
    counts = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
    return summed / counts


def get_embedding(text: str) -> list[float]:
    tokenizer = _get_tokenizer()
    session = _get_session()

    encoding = tokenizer.encode(text)
    input_ids = np.array([encoding.ids], dtype=np.int64)
    attention_mask = np.array([encoding.attention_mask], dtype=np.int64)
    token_type_ids = np.zeros_like(input_ids)

    outputs = session.run(
        None,
        {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        },
    )
    token_embeddings = outputs[0]  # shape: (1, seq_len, 384)

    sentence_embedding = _mean_pooling(token_embeddings, attention_mask)

    # L2-normalize -- required for this model (verified by the course).
    norm = np.linalg.norm(sentence_embedding, axis=1, keepdims=True)
    sentence_embedding = sentence_embedding / norm

    return sentence_embedding[0].tolist()