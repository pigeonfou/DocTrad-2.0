#!/usr/bin/env python3
"""Recheck recorded OCR with production technical controls; performs no inference."""
import argparse
import json
from pathlib import Path

from doctrad2.ocr_quality import compare_ocr


def analyze(data):
    runs = data['runs'] if isinstance(data, dict) and 'runs' in data else [{'results': data}]
    report = []
    for run_index, run in enumerate(runs):
        for item in run['results']:
            record = {'run_index': run_index, 'case': item['case'], 'original_passed': item.get('passed'),
                      'original_word_recall': item.get('word_recall'),
                      'original_word_precision': item.get('word_precision'),
                      'original_numbers_preserved': item.get('numbers_preserved'),
                      'ended_eog': item.get('ended_eog'), 'new_inference_performed': False}
            if item.get('recognized_excerpt'):
                record.update(error='complete_recorded_response_required', requires_review=True)
            else:
                record.update(compare_ocr(item['source'], item['recognized']))
            report.append(record)
    return {'version': 'ocr-technical-analysis-1', 'inference_performed': False,
            'quality_certified': False, 'cases': report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(json.loads(args.input.read_text(encoding='utf-8')))
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({'cases': len(report['cases']), 'inference_performed': False,
                      'technical_checks_passed': sum(c.get('technical_checks_passed') is True for c in report['cases']),
                      'quality_certified': False}))


if __name__ == '__main__':
    main()
