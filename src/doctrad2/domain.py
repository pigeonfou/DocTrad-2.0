from typing import Literal
from pydantic import BaseModel, Field
from .prompts import TEMPLATE_SHA


class Finding(BaseModel):
    code: str
    severity: Literal["info", "review", "critical"]
    unit_id: str | None = None
    detail: str


class Run(BaseModel):
    text: str
    bbox: tuple[float, float, float, float]
    font: str = ""
    size: float = 10
    color: int = 0
    flags: int = 0


class Node(BaseModel):
    id: str
    page: int
    text: str
    bbox: tuple[float, float, float, float] | None = None
    kind: str = "paragraph"
    parent: str | None = None
    runs: list[Run] = Field(default_factory=list)
    locator: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    engine: str = "native"
    translatable: bool = True


class Page(BaseModel):
    number: int
    width: float
    height: float
    rotation: int = 0
    cropbox: list[float] = Field(default_factory=list)
    images: int = 0
    drawings: int = 0
    scanned: bool = False


class DocumentIR(BaseModel):
    schema_version: Literal["2.0.0"] = "2.0.0"
    source_sha: str
    format: Literal["pdf", "docx", "pptx"]
    extractor_version: str = "native-2.0.0"
    pages: list[Page] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    navigation: dict = Field(default_factory=dict)
    findings: list[Finding] = Field(default_factory=list)


class ModelContract(BaseModel):
    name: str = "translategemma-12b-it.Q4_K_M.gguf"
    model_sha: str
    runtime_sha: str
    template: str = "translategemma-text-template-v2:" + TEMPLATE_SHA
    quantization: str = "Q4_K_M"
    input_tokens: int = 1800
    output_tokens: int = 1200
    context_size: int = 4096
    source_language: str = "en"
    target_language: str = "fr"


class QualityReport(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)

    @property
    def blocked(self):
        return any(f.severity == "critical" for f in self.findings)
