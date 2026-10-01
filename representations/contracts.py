"""Stable schemas prevent all-null/missing-view parquet type inference bugs."""

import pyarrow as pa


UNIT_SCHEMA = pa.schema([
    ("unit_id", pa.string()), ("snapshot_id", pa.string()), ("extraction_id", pa.string()),
    ("view", pa.string()), ("subview", pa.string()), ("text", pa.string()),
    ("text_hash", pa.string()), ("status", pa.string()), ("reason", pa.string()),
    ("block_ids", pa.list_(pa.string())), ("section_id", pa.string()),
    ("chunk_index", pa.int32()), ("serialized_start", pa.int64()), ("serialized_end", pa.int64()),
    ("content_weight", pa.int64()), ("role", pa.string()), ("modality", pa.string()),
    ("asset_id", pa.string()), ("product_entity_id", pa.string()),
    ("diagnostics_json", pa.string()),
])

ASSOCIATION_SCHEMA = pa.schema([
    ("record_id", pa.string()), ("snapshot_id", pa.string()), ("extraction_id", pa.string()),
    ("query_unit_id", pa.string()), ("prompt", pa.string()), ("citation_category", pa.string()),
    ("hostname", pa.string()), ("href", pa.string()), ("payload_hash", pa.string()),
    ("extraction_status", pa.string()), ("quality_flags", pa.list_(pa.string())),
    ("split", pa.string()),
])

FAILURE_SCHEMA = pa.schema([
    ("request_id", pa.string()), ("reason", pa.string()), ("attempts", pa.int32()),
    ("retryable", pa.bool_()),
])
