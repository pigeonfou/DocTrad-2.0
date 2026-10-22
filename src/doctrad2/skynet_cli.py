"""Branch-isolated document workbench on DocTrad. SKYNET hosts inference only."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from .reconstruction import build, validate_pdf
from .quality import check_text
from .skynet_document import import_document, translation_plan
from .skynet_inference import InferenceConfig, ModelAPI
from .skynet_store import DocumentStore


def translate(store, document, config):
    plan = translation_plan(store, document)
    if any(item['severity'] == 'critical' for item in plan['findings']) or not plan['units']:
        raise ValueError('document_extraction_requires_resolution')
    base = store.head(document)
    client = ModelAPI(config, 'translation')
    pieces, evidence = {}, []
    try:
        for unit in plan['units']:
            target = client.translate_unit(unit)
            pieces.setdefault(unit['block_id'], []).append(target)
            evidence.append(store.put_json({'unit': unit, 'target': target,
                                            'model': client.endpoint.model_dump(exclude={'api_key_env', 'ca_file'})}))
        updates = {block_id: ' '.join(parts) for block_id, parts in pieces.items()}
        return store.revise(document, base, updates, 'model:' + client.endpoint.model_id,
                            'EN→FR candidate translation', {'responses': evidence})
    finally:
        client.close()


def export(store, document, revision, output):
    _, ir = store.document(document)
    value = store.read_json(revision)
    if value.get('schema') != 'doctrad-skynet-revision-1' or value['document'] != document:
        raise ValueError('revision_document_mismatch')
    expected = {node.id for node in ir.nodes if node.translatable}
    if not expected or set(value['entries']) != expected:
        raise ValueError('incomplete_document_translation')
    current_findings = [finding for node in ir.nodes if node.id in expected
                        for finding in check_text(node.text, value['entries'][node.id]['target'], node.id)]
    if any(f.severity == 'critical' for f in (*ir.findings, *current_findings)):
        raise ValueError('critical_findings_block_export')
    translated = {block_id: item['target'] for block_id, item in value['entries'].items()}
    data = store.read(ir.source_sha)
    rendered, report = build(data, ir, translated)
    if ir.format == 'pdf':
        validate_pdf(data, rendered, report)
    if report.blocked:
        raise ValueError('composition_requires_resolution')
    artifact = store.put(rendered)
    proof = store.put_json({'document': document, 'revision': revision, 'artifact': artifact,
                            'quality': report.model_dump(), 'requires_review': True,
                            'renderer': 'existing-native-baseline'})
    with Path(output).open('xb') as handle:
        handle.write(rendered)
    return {'artifact': artifact, 'report': proof, 'requires_review': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    ingest = commands.add_parser('import')
    ingest.add_argument('file', type=Path)
    plan = commands.add_parser('plan')
    plan.add_argument('document')
    revise = commands.add_parser('revise')
    revise.add_argument('document')
    revise.add_argument('--base')
    revise.add_argument('--updates', type=Path, required=True)
    revise.add_argument('--actor', required=True)
    revise.add_argument('--reason', required=True)
    render = commands.add_parser('export')
    render.add_argument('document')
    render.add_argument('--revision', required=True)
    render.add_argument('--output', type=Path, required=True)
    readiness = commands.add_parser('readiness')
    readiness.add_argument('--config', type=Path, required=True)
    run = commands.add_parser('translate')
    run.add_argument('document')
    run.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    store = DocumentStore(args.root)
    if args.command == 'import':
        with redirect_stdout(sys.stderr):
            document = import_document(store, args.file)
        result = {'document': document, 'inference_performed': False}
    elif args.command == 'plan':
        result = translation_plan(store, args.document)
    elif args.command == 'revise':
        result = {'revision': store.revise(args.document, args.base,
                  json.loads(args.updates.read_text()), args.actor, args.reason)}
    elif args.command == 'export':
        result = export(store, args.document, args.revision, args.output)
    else:
        config = InferenceConfig.model_validate_json(args.config.read_text())
        result = config.readiness() if args.command == 'readiness' else {
            'revision': translate(store, args.document, config)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
