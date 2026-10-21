from doctrad2.ocr_quality import compare_ocr, parse_ocr


def test_table_retains_cells_rows_entities_and_line_breaks():
    result = parse_ocr('<table><tr><td>Pressure</td><td>&gt;7 bar<br/>Limit</td></tr>'
                       '<tr><td>Volume</td><td>275 in<sup>3</sup></td></tr></table>')
    assert result['tables'] == [[['Pressure', '>7 bar\nLimit'], ['Volume', '275 in^3']]]
    assert result['format_issues'] == []
    assert 'Pressure\t>7 bar\nLimit' in result['text']


def test_same_scalar_values_cannot_hide_swapped_units():
    result = compare_ocr('Input: 24 V, current: 3.5 A.', 'Input: 24 A, current: 3.5 V.')
    assert result['checks']['numbers'] == {'missing': [], 'added': []}
    assert result['checks']['physical_quantities']['missing']
    assert not result['technical_checks_passed']


def test_equivalent_negative_signs_and_cubic_formatting():
    result = compare_ocr('AM –110 dBm. Volume: 275 in3.', r'AM -110 dBm. Volume: 275 in\( ^{3} \).')
    assert result['technical_checks_passed']
    assert result['requires_review']


def test_glued_numbers_are_counted_instead_of_silently_omitted():
    result = compare_ocr('30-512 MHz 764-2600 MHz', '30-512 MHz764-2600 MHz')
    assert result['checks']['numbers'] == {'missing': [], 'added': []}
    result = compare_ocr('30-512 MHz 764-2600 MHz', '30-512 MHz-2600 MHz')
    assert result['checks']['numbers']['missing']


def test_reference_change_is_not_hidden_by_numeric_multiset():
    result = compare_ocr('RT-2096, RT-2100', 'RT-2100, TX-2096')
    assert result['checks']['numbers'] == {'missing': [], 'added': []}
    assert result['checks']['identifiers']['missing']
    assert not result['technical_checks_passed']


def test_empty_and_malformed_tables_cannot_pass():
    assert not compare_ocr('Label', '<｜end▁of▁sentence｜>')['technical_checks_passed']
    assert not compare_ocr('24 V', '<table><tr><td>24 V')['technical_checks_passed']
    assert parse_ocr('<table><tr><td colspan="2">24 V</td></tr></table>')['format_issues']


def test_literal_unknown_angle_bracket_text_is_retained():
    assert parse_ocr('Use <controller> then < 12 V')['text'] == 'Use <controller> then < 12 V'
    assert parse_ocr('<Controller>12 V</Controller>')['text'] == '<Controller>12 V</Controller>'


def test_free_text_without_technical_values_is_not_certified_by_empty_checks():
    result = compare_ocr('A label', 'Unrelated added prose')
    assert not result['technical_checks_applicable']
    assert result['technical_checks_passed'] is None
    assert result['requires_review']
