"""Read current-year EPS from the TPEx fourth-quarter financial summary."""
import math
import re

SOURCE = 'https://www.tpex.org.tw/storage/statistic/financial/O_{year}Q4.xls'
PROVENANCE = 'TPEx_Q4_financial_summary'
REPORT_SHEETS = ('國內上櫃公司', '第一上櫃公司')


def parse_workbook(raw, year, retrieved_on):
    """Return full-year EPS keyed by stock code, with report provenance."""
    import xlrd

    if year >= retrieved_on.year:
        raise ValueError('TPEx report year must have ended')
    workbook = xlrd.open_workbook(file_contents=raw)
    rows = {}
    seen = set()
    period = f'{year - 1911}年1-12月'
    source = {
        'url': SOURCE.format(year=year),
        'as_of': retrieved_on.isoformat(),
        'unit': 'TWD_PER_SHARE',
        'provenance': PROVENANCE,
        'basis': 'reported_full_year_EPS',
    }
    for name in REPORT_SHEETS:
        sheet = workbook.sheet_by_name(name)
        headers = sheet.row_values(4)
        periods = sheet.row_values(6)
        columns = [
            index for index, label in enumerate(headers)
            if str(label).splitlines()[0:1] == ['每股稅後純益']
            and str(periods[index]).splitlines()[0:1] == [period]
        ]
        if len(columns) != 1 or '公司名稱' not in str(headers[0]):
            raise ValueError('TPEx report is missing verified code and current-year EPS columns')
        for index in range(8, sheet.nrows):
            code = sheet.cell_value(index, 0)
            if isinstance(code, float) and code.is_integer():
                code = str(int(code))
            if not re.fullmatch(r'[0-9]{4}', str(code)):
                continue
            if code in seen:
                raise ValueError('TPEx report contains a duplicate stock code')
            seen.add(code)
            cell = sheet.cell(index, columns[0])
            if cell.ctype != xlrd.XL_CELL_NUMBER or not math.isfinite(cell.value):
                continue
            rows[code] = {
                'eps': cell.value,
                'currency': 'TWD',
                'as_of': retrieved_on.isoformat(),
                'period_start': f'{year}-01-01',
                'period_end': f'{year}-12-31',
                'field_sources': {'eps': dict(source)},
            }
    if not rows:
        raise ValueError('TPEx report contains no verified full-year EPS')
    return rows


def fetch_year(year, today):
    """Fetch one market-wide workbook within bounded network and size budgets."""
    import time

    import requests

    from app.providers.bounded_http import ResourceLimitError

    deadline = time.monotonic() + 20
    with requests.get(
        SOURCE.format(year=year), stream=True, timeout=(10, 8), allow_redirects=False
    ) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('TPEx report did not return a workbook directly')
        data = bytearray()
        for chunk in response.iter_content(16384):
            if time.monotonic() >= deadline or len(data) + len(chunk) > 2_000_000:
                raise ResourceLimitError('TPEx workbook exceeded download budget')
            data.extend(chunk)
    return parse_workbook(bytes(data), year, today)
