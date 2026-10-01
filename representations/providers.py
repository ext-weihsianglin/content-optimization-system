"""Hosted HTTP adapters with strict indexing, dimensions, and role handling."""

import os

import httpx
import numpy as np


class ProviderError(Exception):
    def __init__(self, reason, *, retryable=False, fatal=False):
        super().__init__(reason)
        self.reason, self.retryable, self.fatal = reason, retryable, fatal


def validated_vectors(data, count, dimensions):
    if not isinstance(data, list) or len(data) != count:
        raise ProviderError("response_cardinality_mismatch")
    ordered = [None] * count
    for item in data:
        index = item.get("index")
        if type(index) is not int or not 0 <= index < count or ordered[index] is not None:
            raise ProviderError("response_index_mismatch")
        try:
            vector = np.asarray(item["embedding"], dtype=np.float32)
        except (KeyError, ValueError, TypeError):
            raise ProviderError("invalid_vector") from None
        if vector.shape != (dimensions,) or not np.isfinite(vector).all() or not np.isfinite(np.linalg.norm(vector)) or np.linalg.norm(vector) == 0:
            raise ProviderError("invalid_vector_dimension_or_norm")
        ordered[index] = vector
    return ordered


class HTTPProvider:
    def __init__(self, config):
        self.config = config
        self.key = os.environ.get(config["key_env"])
        if not self.key:
            raise ProviderError(f"missing_credential:{config['key_env']}", fatal=True)
        if config["provider"] == "openrouter" and not config.get("provider_order"):
            raise ProviderError("openrouter_requires_pinned_provider_order", fatal=True)
        if config["attempts"] < 1 or config["batch_size"] < 1 or config["concurrency"] < 1:
            raise ProviderError("invalid_runner_limits", fatal=True)

    def embed(self, texts, role):
        cfg = self.config
        if role not in {"query", "document"}:
            raise ProviderError("unsupported_input_role", fatal=True)
        inputs = [(cfg.get("query_instruction", "") if role == "query" else "") + text for text in texts]
        if any(not text.strip() or len(text.encode()) > cfg["max_input_bytes"] for text in inputs):
            raise ProviderError("empty_or_oversized_input")
        payload = {"model": cfg["model"], "input": inputs, "encoding_format": "float"}
        if cfg["provider"] == "voyage":
            payload.update(input_type=role, output_dimension=cfg["dimensions"], output_dtype="float", truncation=False)
            payload.pop("encoding_format")
        elif cfg["provider"] == "openai":
            payload["dimensions"] = cfg["dimensions"]
        else:
            # Full Qwen output; do not assume an endpoint supports dimensions.
            payload["provider"] = {"order": cfg["provider_order"], "allow_fallbacks": False,
                                   "require_parameters": True, "data_collection": "deny"}
        try:
            response = httpx.post(cfg["endpoint"], headers={"Authorization": "Bearer " + self.key},
                                  json=payload, timeout=cfg["timeout"])
        except httpx.TransportError:
            raise ProviderError("transport_error", retryable=True) from None
        if response.status_code != 200:
            code = response.status_code
            raise ProviderError(f"http_{code}", retryable=code in {408, 409, 429} or code >= 500,
                                fatal=code in {401, 403, 404})
        try:
            result = response.json()
            vectors = validated_vectors(result.get("data"), len(texts), cfg["dimensions"])
        except (ValueError, AttributeError):
            raise ProviderError("malformed_response") from None
        return vectors, result.get("usage", {})
