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
            out = {"chat_template": "source_lang_code target_lang_code", "model_path": "translategemma.gguf", "default_generation_settings": {"n_ctx": 4096}}
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
    with pytest.raises(InferenceError, match="template_required"):
        translator.translate("Input 12 V")


def test_output_truncation_rejected(settings):
    translator = LlamaTranslator(settings, transport(lambda _: httpx.Response(200, json={"content": "incomplete", "stopped_limit": True})))
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
