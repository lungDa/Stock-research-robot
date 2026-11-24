import pytest
from sqlalchemy import event

from app.db import engine, get, put, put_many


def test_batch_replaces_existing_and_inserts_new_documents():
    put('existing', {'before': 1})
    put_many({'existing': {'after': 2}, 'new': {'name': '台股'}})
    assert get('existing') == {'after': 2}
    assert get('new') == {'name': '台股'}


def test_failure_in_second_batch_rolls_back_first_batch():
    def reject_last_batch(connection, cursor, statement, parameters, context, executemany):
        if 'key:080' in parameters:
            raise RuntimeError('write interrupted')

    event.listen(engine, 'before_cursor_execute', reject_last_batch)
    try:
        with pytest.raises(RuntimeError, match='write interrupted'):
            put_many({f'key:{index:03}': index for index in range(81)})
    finally:
        event.remove(engine, 'before_cursor_execute', reject_last_batch)
    assert get('key:000') is None
