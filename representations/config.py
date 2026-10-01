"""Versioned hosted and local model adapters over frozen textual inputs."""

from pathlib import Path

from .storage import read_json
from . import SERIALIZER_VERSION
from .url_path import VERSION as PATH_VERSION


def load_config(path=None):
    config = read_json(path or Path(__file__).with_name("config.json"))
    if config.get("schema_version") != "1.0.0":
        raise ValueError("Unsupported representation configuration")
    if not 64 <= config["chunk_bytes"] <= config["page_bytes"] <= 7000:
        raise ValueError("Require 64 <= chunk_bytes <= page_bytes <= 7000")
    for name, model in config["models"].items():
        model["serializer_version"] = SERIALIZER_VERSION
        model["path_normalizer_version"] = PATH_VERSION
        if model["provider"] not in {"openai", "voyage", "openrouter", "mlx"}:
            raise ValueError(f"Unsupported embedding provider: {name}")
        if model["dimensions"] < 1 or model["max_input_bytes"] < config["page_bytes"] + 256:
            raise ValueError(f"Invalid model capacity: {name}")
    return config
