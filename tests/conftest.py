import pytest
from doctrad2.config import Settings
from doctrad2.db import Database


@pytest.fixture
def settings(tmp_path):
    return Settings(root=tmp_path, database_url=f"sqlite:///{tmp_path}/jobs.sqlite", secret="s" * 48,
                    model_sha="a" * 64, runtime_sha="b" * 64, secure_cookie=False)


@pytest.fixture
def database(settings):
    db = Database(settings.database_url)
    db.migrate()
    return db


def pdf(text="Input voltage 12 V", *, graphics=True):
    import pymupdf as fitz
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 80), text, fontsize=12)
    if graphics:
        page.draw_line((50, 180), (400, 180), color=(1, 0, 0), width=2)
        page.draw_rect(fitz.Rect(50, 200, 180, 300), fill=(0, .3, .7))
    doc.set_toc([[1, "Technical specification", 1]])
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(400, 400, 500, 420), "uri": "https://example.org"})
    result = doc.tobytes()
    doc.close()
    return result
