#!/usr/bin/env python3
"""Qualify the local workbench without permitting any network connection."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import socket
import sys

import pymupdf as fitz

from doctrad2.skynet_cli import export
from doctrad2.skynet_document import import_document, translation_plan
from doctrad2.skynet_inference import InferenceConfig, InferenceDisabled, ModelAPI
from doctrad2.skynet_store import DocumentStore, RevisionConflict


def no_network(*args, **kwargs):
    raise AssertionError('network_forbidden_in_offline_qualification')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--reference', type=Path, action='append', default=[])
    args = parser.parse_args()
    socket.socket.connect = no_network
    socket.create_connection = no_network
    args.root.mkdir(mode=0o700, parents=True, exist_ok=False)
    store = DocumentStore(args.root / 'store')
    config = InferenceConfig.model_validate_json(args.config.read_text())
    assert not config.remote_enabled and not config.readiness()['ready']
    try:
        ModelAPI(config, 'vision')
    except InferenceDisabled:
        pass
    else:
        raise AssertionError('remote_model_client_must_remain_disabled')
    references = []
    for reference in args.reference:
        with redirect_stdout(sys.stderr):
            document = import_document(store, reference)
        plan = translation_plan(store, document)
        assert plan['units'] and not plan['inference_performed']
        references.append({'file': reference.name, 'document': document, 'units': len(plan['units']),
                           'requires_vision_pages': plan['requires_vision_pages']})
    source = args.root / 'fixture.pdf'
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((40, 60), 'Input voltage: 12 V.', fontsize=11)
    page.insert_text((40, 140), 'Current: 3.5 A.', fontsize=11)
    pdf.save(source)
    pdf.close()
    with redirect_stdout(sys.stderr):
        document = import_document(store, source)
    _, ir = store.document(document)
    assert len(ir.nodes) == 2
    first = store.revise(document, None, {ir.nodes[0].id: "Tension d'entrée : 12 V."}, 'offline-test', 'First block')
    second = store.revise(document, first, {ir.nodes[1].id: 'Courant : 3,5 A.'}, 'offline-test', 'Second block')
    try:
        store.revise(document, first, {ir.nodes[0].id: '12 V'}, 'offline-test', 'Stale edit')
    except RevisionConflict:
        pass
    else:
        raise AssertionError('stale_revision_must_be_rejected')
    output = args.root / 'fixture-fr.pdf'
    result = export(store, document, second, output)
    assert result['requires_review'] and output.is_file()
    print(json.dumps({'branch': 'Doctrad-Skynet', 'application_host': 'doctrad',
                      'skynet_contacted': False, 'inference_performed': False, 'references': references,
                      'revision_conflict_checked': True, 'native_render_checked': True,
                      'connection_readiness': config.readiness()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
