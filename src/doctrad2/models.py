"""Roles are explicit: an OCR model must never be used as a translator."""


def catalog(settings):
    return [
        {"id": "translategemma-12b", "name": "TranslateGemma 12B Q4_K_M",
         "role": "translation", "configured": bool(settings.model_sha and settings.runtime_sha),
         "availability": "configured_not_probed"},
        {"id": "unlimited-ocr-gguf", "name": "Unlimited-OCR-GGUF",
         "role": "ocr", "quantization": "Q5_K_M", "experimental": True,
         "configured": False, "availability": "installation_required",
         "repository": "sahilchachra/Unlimited-OCR-GGUF",
         "files": ["Unlimited-OCR-Q5_K_M.gguf", "mmproj-Unlimited-OCR-F16.gguf"],
         "reason": "Modèle et projecteur à installer sur la BC-250 ; test local avec scripts/test-unlimited-ocr.py. "
                   "La passerelle actuelle ne permet pas le changement de modèle.",
         "translation_model": "translategemma-12b"},
    ]
