from app.services.v26_coverage_adapter import from_documents


def test_empty_neon_documents_do_not_claim_completeness():
    row = from_documents('2330.TW', {}, current_year=2026)
    assert row['complete_items'] == 0
    assert row['expected_items'] == 31
    assert row['verified'] is False
    assert row['missing_years']['cash_dividend_years'][0] == 2016


def test_existing_value_without_period_metadata_not_verified():
    docs = {'financial:official:2330.TW': {
        'rows': {'2025': {'eps': 12.5, 'source_url': 'https://example.org',
                          'unit': 'TWD_PER_SHARE'}}}}
    row = from_documents('2330.TW', docs, current_year=2026)
    assert row['complete_items'] == 0


def test_verified_period_metadata_counts_without_claiming_full_audit():
    docs = {'financial:official:2330.TW': {
        'rows': {'2025': {'eps': 12.5, 'source_url': 'https://example.org',
                          'unit': 'TWD_PER_SHARE', 'period_end': '2025-12-31'}}}}
    row = from_documents('2330.TW', docs, current_year=2026)
    assert row['complete_items'] == 1
    assert row['verified'] is False
    assert row['missing_years']['eps'] == [2021, 2022, 2023, 2024]


def test_reject_non_stock_symbol():
    import pytest
    with pytest.raises(ValueError):
        from_documents('0050.TW.EXTRA', {}, current_year=2026)
