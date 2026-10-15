import re
import time
import httpx
import ssl
from .domain import ModelContract
from .prompts import render, TEMPLATE_SHA


class InferenceError(RuntimeError):
    pass


class LlamaTranslator:
    """Direct llama-server protocol. No Unsloth import, proxy, model switch or download."""
    def __init__(self, settings, transport=None):
        if not re.fullmatch(r"[0-9a-f]{64}", settings.model_sha) or not re.fullmatch(r"[0-9a-f]{64}", settings.runtime_sha):
            raise InferenceError("model_and_runtime_sha_required")
        self.contract = ModelContract(model_sha=settings.model_sha, runtime_sha=settings.runtime_sha,
                                      input_tokens=settings.input_tokens, output_tokens=settings.output_tokens)
        tls = ssl.create_default_context(cafile=settings.llm_ca or None)
        if settings.client_cert and settings.client_key:
            tls.load_cert_chain(settings.client_cert, settings.client_key)
        self.client = httpx.Client(verify=tls,base_url=settings.llm_url.rstrip("/"), timeout=90,
                                   headers={"Authorization": f"Bearer {settings.llm_key}"} if settings.llm_key else {},
                                   trust_env=False, follow_redirects=False, transport=transport)
        self._validated = False
        self._local_template = False

    def close(self):
        self.client.close()

    def request(self, path, payload=None):
        for attempt in range(3):
            response = None
            try:
                response = self.client.get(path) if payload is None else self.client.post(path, json=payload)
                if response.status_code in {429, 502, 503, 504}:
                    raise InferenceError("llm_temporarily_unavailable")
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, InferenceError):
                if attempt == 2:
                    raise InferenceError("llm_transport_failed_" + path.strip("/").replace("-", "_") + "_" + (str(response.status_code) if response is not None else "network")) from None
                time.sleep((1, 3)[attempt])
            except (httpx.HTTPError, ValueError):
                raise InferenceError("llm_protocol_failed") from None

    def validate(self):
        props = self.request("/props")
        defaults = props.get("default_generation_settings", {})
        ctx = defaults.get("n_ctx", defaults.get("params", {}).get("n_ctx", 0))
        template = str(props.get("chat_template", ""))
        self._local_template = "source_lang_code" not in template or "target_lang_code" not in template
        if ctx and ctx < self.contract.input_tokens + self.contract.output_tokens:
            raise InferenceError("llm_context_too_small")
        model = str(props.get("model_path", props.get("model_alias", "")))
        if not model or "translategemma-12b" not in model.lower():
            raise InferenceError("wrong_loaded_model")
        self._validated = True
        return {"model": model, "context": ctx, "template": "local-translategemma" if self._local_template else "embedded-translategemma", "template_sha": TEMPLATE_SHA}

    def prompt(self, text):
        if self._local_template:
            return render(text)
        messages = [{"role": "user", "content": [{"type": "text", "source_lang_code": "en",
                                                      "target_lang_code": "fr", "text": text}]}]
        result = self.request("/apply-template", {"messages": messages, "add_generation_prompt": True})
        prompt = result.get("prompt")
        if not isinstance(prompt, str):
            raise InferenceError("template_endpoint_required")
        return prompt

    def token_count(self, prompt):
        result = self.request("/tokenize", {"content": prompt, "add_special": False, "parse_special": True})
        tokens = result.get("tokens")
        if not isinstance(tokens, list):
            raise InferenceError("tokenizer_endpoint_required")
        return len(tokens)

    def chunks(self, text):
        prompt = self.prompt(text)
        if self.token_count(prompt) <= self.contract.input_tokens:
            return [(text, prompt)]
        boundaries = [m.end() for m in re.finditer(r"(?<=[.!?;])\s+|\n+", text)]
        if not boundaries:
            boundaries = [m.end() for m in re.finditer(r"\s+", text)]
        if not boundaries:
            raise InferenceError("unbreakable_unit_too_long")
        midpoint = min(boundaries, key=lambda i: abs(i - len(text) / 2))
        return self.chunks(text[:midpoint].strip()) + self.chunks(text[midpoint:].strip())

    def translate(self, text):
        if not self._validated:
            self.validate()
        outputs = []
        provenance = []
        for source, prompt in self.chunks(text):
            tokenized = self.request("/tokenize", {"content": prompt, "add_special": False, "parse_special": True})
            prompt_tokens = tokenized.get("tokens")
            if not isinstance(prompt_tokens, list) or not prompt_tokens:
                raise InferenceError("tokenizer_endpoint_required")
            result = self.request("/completion", {"prompt": prompt_tokens, "n_predict": self.contract.output_tokens,
                                  "temperature": 0, "seed": 42, "cache_prompt": True, "stream": False})
            if result.get("stopped_limit") or result.get("truncated") or result.get("stop_type") == "limit":
                raise InferenceError("translation_truncated")
            target = result.get("content")
            if not isinstance(target, str) or not target.strip():
                raise InferenceError("empty_translation")
            outputs.append(target.strip())
            provenance.append({"source_length": len(source), "input_tokens": self.token_count(prompt),
                               "output_tokens": result.get("tokens_predicted"), "timings": result.get("timings", {})})
        return "\n".join(outputs), {"contract": self.contract.model_dump(), "chunks": provenance,
                                      "context_policy": "official_template_source_only;context_for_review",
                                      "template_sha": TEMPLATE_SHA, "template_mode": "local" if self._local_template else "embedded"}
