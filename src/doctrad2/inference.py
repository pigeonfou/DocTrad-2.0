import re
import time
import httpx
import ssl
from .domain import ModelContract
from .prompts import render, messages, TEMPLATE_SHA
from .text_policy import translation_source, sentence_parts, POLICY_VERSION
from .quality import check_text
from .fidelity import restore_unambiguous_units
from .literals import shield, restore, literal_only


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
        self.examples = []
        self.term_cache = {}
        self._validated = False
        self._local_template = False

    def close(self):
        self.client.close()

    def request(self, path, payload=None):
        delays = (1, 3, 10, 20, 30)
        for attempt in range(len(delays) + 1):
            response = None
            try:
                response = self.client.get(path) if payload is None else self.client.post(path, json=payload)
                if response.status_code in {429, 502, 503, 504}:
                    raise InferenceError("llm_temporarily_unavailable")
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, InferenceError):
                if attempt == len(delays):
                    raise InferenceError("llm_transport_failed_" + path.strip("/").replace("-", "_") + "_" + (str(response.status_code) if response is not None else "network")) from None
                time.sleep(delays[attempt])
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
            return render(text, self.examples)
        result = self.request("/apply-template", {"messages": messages(text, self.examples), "add_generation_prompt": True})
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

    def complete(self, prompt, temperature=0, seed=42):
        tokenized = self.request("/tokenize", {"content": prompt, "add_special": False, "parse_special": True})
        tokens = tokenized.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            raise InferenceError("tokenizer_endpoint_required")
        result = self.request("/completion", {"prompt": tokens, "n_predict": self.contract.output_tokens,
                              "temperature": temperature, "seed": seed, "cache_prompt": True, "stream": False})
        if result.get("stopped_limit") or result.get("truncated") or result.get("stop_type") == "limit":
            raise InferenceError("translation_truncated")
        target = result.get("content")
        if not isinstance(target, str) or not target.strip():
            raise InferenceError("empty_translation")
        return target.strip(), {"input_tokens": len(tokens), "output_tokens": result.get("tokens_predicted"),
                                "timings": result.get("timings", {})}

    def translate(self, text):
        if not self._validated:
            self.validate()
        source_text = translation_source(text)
        self.examples = []
        # Short emphasized phrases are translated independently, then supplied as
        # normal user/assistant examples using the official conversation schema.
        # These terms are derived from this source, never a document wordlist.
        if literal_only(source_text):
            return text, {'contract': self.contract.model_dump(), 'translation_policy': POLICY_VERSION, 'literal_only': True, 'chunks': []}
        terms = re.findall(r"\b[A-Z]{2,}(?:[ -]+[A-Z]{2,}){1,3}\b", source_text)
        terms += re.findall(r'\b[A-Za-z]+(?:-[A-Za-z]+)+\b', source_text)
        for term in dict.fromkeys(terms):
            if term == source_text or len(term) > 60 or len(self.examples) >= 3:
                continue
            if term not in self.term_cache:
                prior = self.examples
                self.examples = []
                try:
                    translated_term, _ = self.complete(self.prompt(term))
                finally:
                    self.examples = prior
                if not any(f.severity == 'critical' for f in check_text(term, translated_term, '')):
                    self.term_cache[term] = translated_term
            if term in self.term_cache:
                self.examples.append((term, self.term_cache[term]))
        bullet = re.match(r"^([>•›])\s+(?=[A-Za-z])", source_text)
        prefix = bullet.group() if bullet else ''
        if prefix:
            source_text = source_text[len(prefix):]
        outputs, provenance = [], []
        # Keep complete sentences, not visual PDF lines, as inference units.
        for sentence in sentence_parts(source_text):
            for source, prompt in self.chunks(sentence):
                raw, info = self.complete(prompt)
                target, repairs = restore_unambiguous_units(source, raw)
                candidates = [{"target": target, "raw_target": raw, "unit_repairs": repairs, "generation": info}]
                findings = check_text(source, target, '')
                def terminology_misses(candidate):
                    return sum(' ' in term and term.isupper() and term in source and expected.casefold() not in candidate.casefold()
                               for term, expected in self.examples)
                if any(f.severity == 'critical' for f in findings) or terminology_misses(target) or (len(source) < 120 and len(target) > max(30, len(source) * 1.6)):
                    alternate, alternate_info = self.complete(prompt, temperature=.2, seed=43)
                    corrected, repairs = restore_unambiguous_units(source, alternate)
                    candidates.append({"target": corrected, "raw_target": alternate, "unit_repairs": repairs, "generation": alternate_info})
                def rank(candidate):
                    issues = check_text(source, candidate['target'], '')
                    return (sum(f.severity == 'critical' for f in issues), terminology_misses(candidate['target']),
                            sum(f.severity == 'review' for f in issues), len(candidate['target']))
                if min(rank(c)[0] for c in candidates) > 0:
                    masked, mapping = shield(source)
                    if mapping:
                        masked_target, masked_info = self.complete(self.prompt(masked))
                        restored = restore(masked_target, mapping)
                        if restored is not None:
                            candidates.append({"target": restored, "raw_target": masked_target, "unit_repairs": [],
                                               "generation": {**masked_info, "literal_spans": mapping}})
                selected = min(range(len(candidates)), key=lambda index: rank(candidates[index]))
                target = candidates[selected]['target']
                outputs.append(target)
                provenance.append({"source_length": len(source), **candidates[selected]['generation'],
                                   "selected_attempt": selected, "attempts": [
                                       {**candidate['generation'], "raw_target": candidate['raw_target'], "target": candidate['target'], "unit_repairs": candidate['unit_repairs'], "findings": [f.code for f in check_text(source, candidate['target'], '')]}
                                       for candidate in candidates]})
        return prefix + " ".join(outputs), {"contract": self.contract.model_dump(), "chunks": provenance,
                                      "context_policy": "official_template_complete_sentences;context_for_review",
                                      "translation_policy": POLICY_VERSION, "terminology_examples": self.examples,
                                      "template_sha": TEMPLATE_SHA, "template_mode": "local" if self._local_template else "embedded"}
