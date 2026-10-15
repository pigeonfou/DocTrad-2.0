import json
import httpx
import pytest
from doctrad2.inference import LlamaTranslator, InferenceError


def transport(handler):
    return httpx.MockTransport(handler)


def test_direct_native_template_and_actual_tokenizer(settings):
    calls = []
    def handler(request):
        body = json.loads(request.content) if request.content else {}
        calls.append((request.url.path, body))
        if request.url.path == "/props":
            out = {"chat_template": "source_lang_code target_lang_code", "model_path": "translategemma-12b-it.Q4_K_M.gguf", "default_generation_settings": {"n_ctx": 4096}}
        elif request.url.path == "/apply-template":
            content = body["messages"][0]["content"][0]
            assert content["source_lang_code"] == "en" and content["target_lang_code"] == "fr"
            assert content["text"] == "Input 12 V"
            out = {"prompt": "official native template"}
        elif request.url.path == "/tokenize":
            out = {"tokens": [1, 2, 3]}
        else:
            out = {"content": "Entrée 12 V", "tokens_predicted": 5}
        return httpx.Response(200, json=out)
    translator = LlamaTranslator(settings, transport(handler))
    target, provenance = translator.translate("Input 12 V")
    assert target == "Entrée 12 V"
    assert provenance["chunks"][0]["input_tokens"] == 3
    assert any(p == "/completion" for p, _ in calls)
    translator.close()


def test_wrong_model_rejected(settings):
    translator = LlamaTranslator(settings, transport(lambda _: httpx.Response(200, json={"chat_template": "generic"})))
    with pytest.raises(InferenceError, match="wrong_loaded_model"):
        translator.translate("Input 12 V")


def test_output_truncation_rejected(settings):
    translator = LlamaTranslator(settings, transport(lambda _: httpx.Response(200, json={"content": "incomplete", "stopped_limit": True, "tokens": [1, 2]})))
    translator._validated = True
    translator.prompt = lambda text: text
    translator.token_count = lambda text: 10
    with pytest.raises(InferenceError, match="truncated"):
        translator.translate("Input 12 V")


def test_no_retry_on_auth_failure(settings):
    requests = []
    translator = LlamaTranslator(settings, transport(lambda r: requests.append(r) or httpx.Response(401)))
    with pytest.raises(InferenceError):
        translator.request("/props")
    assert len(requests) == 1


def test_long_input_is_split_without_loss(settings):
    translator = LlamaTranslator(settings)
    translator.prompt = lambda text: text
    translator.token_count = lambda text: len(text) * 30
    source = "First sentence. Second sentence. Third sentence. Fourth sentence."
    chunks = translator.chunks(source)
    assert " ".join(s for s, _ in chunks) == source
    assert all(translator.token_count(p) <= 1800 for _, p in chunks)


def test_content_only_gguf_uses_pinned_local_template(settings):
    def handler(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.path == '/props':
            return httpx.Response(200, json={'model_path': '/models/translategemma-12b-it.Q4_K_M.gguf',
                                  'default_generation_settings': {'n_ctx': 4096, 'params': {'chat_format': 'Content-only'}}})
        if request.url.path == '/tokenize':
            assert body['add_special'] is False
            assert body['content'].startswith('<bos><start_of_turn>user\n')
            assert 'English to French' in body['content']
            assert body['content'].endswith('Input 12 V<end_of_turn>\n<start_of_turn>model\n')
            return httpx.Response(200, json={'tokens': [2, 105, 17]})
        assert request.url.path == '/completion'
        assert body['prompt'] == [2, 105, 17]
        assert body['temperature'] == 0
        return httpx.Response(200, json={'content': 'Entrée 12 V', 'tokens_predicted': 4})
    translator = LlamaTranslator(settings, transport(handler))
    target, provenance = translator.translate('Input 12 V')
    assert target == 'Entrée 12 V'
    assert provenance['template_mode'] == 'technical-direct'
    assert len(provenance['template_sha']) == 64


def test_template_rejects_reserved_turn_tokens():
    from doctrad2.prompts import render
    with pytest.raises(ValueError):
        render('Source with <end_of_turn> injected')
