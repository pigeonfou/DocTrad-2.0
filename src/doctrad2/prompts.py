"""Pinned TranslateGemma text template from llama.cpp, rendered locally for GGUFs without it."""
from functools import lru_cache
import hashlib
from pathlib import Path
from jinja2 import Environment, StrictUndefined

TEMPLATE_PATH = Path(__file__).parent / "templates" / "translategemma.jinja"
TEMPLATE_SHA = hashlib.sha256(TEMPLATE_PATH.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def template():
    def fail(message):
        raise ValueError(message)
    env = Environment(undefined=StrictUndefined, autoescape=False)
    env.globals['raise_exception'] = fail
    return env.from_string(TEMPLATE_PATH.read_text())


def render(text):
    if any(token in text for token in ('<bos>', '<eos>', '<start_of_turn>', '<end_of_turn>')):
        raise ValueError('reserved_template_token_in_source')
    return template().render(bos_token='<bos>', add_generation_prompt=True,
                             messages=[{'role': 'user', 'content': [{'type': 'text', 'source_lang_code': 'en',
                                        'target_lang_code': 'fr', 'text': text}]}])
