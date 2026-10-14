import pytest
from doctrad2.quality import check_text, numbers
from doctrad2.config import Settings


@pytest.mark.parametrize("source,target,code", [
    ("Voltage 12 V", "Tension 21 V", "numbers"),
    ("Voltage 12 V", "Tension 12 A", "value_units"),
    ("Reference AN/PRC-167", "Référence AN/PRC-168", "identifiers"),
    ("Input 12 V and output 5 A", "Entrée 5 V et sortie 12 A", "value_units"),
    ("Supply -12 V", "Alimentation 12 V", "numbers"),
    ("Voltage 12 V", "", "empty_target"),
])
def test_critical_invariants(source, target, code):
    assert any(f.code == code and f.severity == "critical" for f in check_text(source, target, "n"))


def test_decimal_localization():
    assert numbers("3.2 V") == numbers("3,2 V")
    assert not check_text("3.2 V", "3,2 V", "n")


def test_glossary_is_review_not_silent_rewrite():
    findings = check_text("ground", "sol", "n", {"ground": "masse"})
    assert findings[0].code == "glossary"


@pytest.mark.parametrize("url", ["https://api.openai.com", "http://8.8.8.8", "http://169.254.169.254", "http://192.168.1.2@evil.org", "http://myserver.local", "http://192.168.1.1?secret=x"])
def test_external_endpoints_rejected(tmp_path, url):
    with pytest.raises(ValueError):
        Settings(tmp_path, "sqlite://", "s" * 40, llm_url=url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:8098", "http://192.168.6.10:8098", "http://10.1.2.3:8080", "http://[::1]:8098"])
def test_lan_endpoints(tmp_path, url):
    Settings(tmp_path, "sqlite://", "s" * 40, llm_url=url)
