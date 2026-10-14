from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse
import ipaddress


@dataclass(frozen=True)
class Settings:
    root: Path
    database_url: str
    secret: str
    llm_url: str = "http://127.0.0.1:8098"
    llm_key: str = ""
    model_sha: str = ""
    runtime_sha: str = ""
    input_tokens: int = 1800
    output_tokens: int = 1200
    secure_cookie: bool = True
    tessdata: str = ""
    docling_models: str = ""

    def __post_init__(self):
        if len(self.secret) < 32:
            raise ValueError("DOCTRAD2_SECRET doit contenir au moins 32 caractères")
        u = urlparse(self.llm_url)
        if u.scheme not in {"http", "https"} or u.username or u.password or u.query or u.fragment:
            raise ValueError("URL LLM invalide")
        # Numeric LAN addresses avoid DNS rebinding and unintended external document transmission.
        if u.hostname != "localhost":
            try:
                address = ipaddress.ip_address(u.hostname)
            except ValueError as exc:
                raise ValueError("Le moteur LLM exige une adresse IP LAN explicite") from exc
            if not (address.is_loopback or address in ipaddress.ip_network("10.0.0.0/8")
                    or address in ipaddress.ip_network("172.16.0.0/12")
                    or address in ipaddress.ip_network("192.168.0.0/16")
                    or address in ipaddress.ip_network("fc00::/7")):
                raise ValueError("Le moteur LLM doit être local ou sur le LAN privé")
        if not 128 <= self.input_tokens <= 1800 or not 64 <= self.output_tokens <= 1800:
            raise ValueError("Budget TranslateGemma non accepté")

    @classmethod
    def load(cls):
        root = Path(os.getenv("DOCTRAD2_ROOT", "/var/lib/doctrad2"))
        return cls(root=root, database_url=os.getenv("DOCTRAD2_DATABASE", f"sqlite:///{root}/jobs.sqlite"),
                   secret=os.getenv("DOCTRAD2_SECRET", ""), llm_url=os.getenv("DOCTRAD2_LLM_URL", "http://127.0.0.1:8098"),
                   llm_key=os.getenv("DOCTRAD2_LLM_KEY", ""), model_sha=os.getenv("DOCTRAD2_MODEL_SHA", ""),
                   runtime_sha=os.getenv("DOCTRAD2_RUNTIME_SHA", ""),
                   secure_cookie=os.getenv("DOCTRAD2_SECURE_COOKIE", "1") == "1",
                   tessdata=os.getenv("TESSDATA_PREFIX", ""), docling_models=os.getenv("DOCTRAD2_DOCLING_MODELS", ""))
