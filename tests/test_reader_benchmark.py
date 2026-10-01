import pytest

from preprocessing.reader_benchmark import local_endpoint, output_result, prepare_prompt


@pytest.mark.parametrize("endpoint", ["https://example.com/v1/completions", "http://localhost:8087", "http://127.0.0.1.example.com", "http://user:pass@127.0.0.1"])
def test_remote_endpoints_rejected(endpoint):
    with pytest.raises(ValueError):
        local_endpoint(endpoint)


def test_loopback_endpoint_allowed():
    assert local_endpoint("http://127.0.0.1:8087/v1/completions")


def test_model_output_is_inert_and_capped_output_is_disclosed():
    result = output_result({"choices": [{"text": "# Heading\n\n<script>alert(1)</script>", "finish_reason": "length"}], "usage": {"completion_tokens": 10}}, "https://example.com", {})
    assert result.status == "ok"
    assert result.diagnostics["output_capped"]
    assert "<script>" not in result.html
    assert all(block["source_locator"] is None for block in result.blocks)


class CharacterTokenizer:
    def encode(self, text, **kwargs):
        return list(text)

    def decode(self, tokens):
        return "".join(tokens)

    def apply_chat_template(self, messages, tokenize, **kwargs):
        text = "[" + messages[0]["content"] + "]"
        return list(text) if tokenize else text


def test_prefix_budget_includes_template_and_preserves_untruncated_source():
    tokenizer = CharacterTokenizer()
    prompt, diagnostics = prepare_prompt(tokenizer, "abcdef", 5)
    assert prompt == "[abc]"
    assert diagnostics == {"source_tokens": 6, "input_tokens": 5, "input_truncated": True}
    prompt, diagnostics = prepare_prompt(tokenizer, "abcdef", 20)
    assert prompt == "[abcdef]"
    assert not diagnostics["input_truncated"]
