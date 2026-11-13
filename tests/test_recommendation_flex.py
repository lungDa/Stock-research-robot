from app.services.recommendation_flex import recommendation_flex


def test_ten_bubbles_two_buttons_and_round_per_stock():
    items=[{'symbol':f'{2300+i}.TW','name':f'公司{i}','score':90-i,
            'relaxation_round':i%3} for i in range(12)]
    result=recommendation_flex(items,'https://example.com/')
    assert result['type']=='flex'
    bubbles=result['contents']['contents']
    assert len(bubbles)==10
    assert '放寬輪次：0' in bubbles[0]['body']['contents'][2]['text']
    assert '放寬輪次：1' in bubbles[1]['body']['contents'][2]['text']
    assert [x['action']['label'] for x in bubbles[0]['footer']['contents']]==[
        '詳細分析','開啟股海燈塔']
    assert bubbles[0]['footer']['contents'][0]['action']['uri'].endswith('?symbol=2300.TW')


def test_fail_closed_for_bad_url_or_empty_input():
    assert recommendation_flex([], 'https://example.com') is None
    assert recommendation_flex([{'symbol':'2330.TW'}], 'http://example.com') is None
    assert recommendation_flex([{'symbol':'2330.TW'}], 'https://user:secret@example.com') is None


def test_text_is_bounded_and_query_encoded():
    result=recommendation_flex([{'symbol':'2330.TW&x=1','name':'a'*200}],
                               'https://example.com')
    bubble=result['contents']['contents'][0]
    assert len(bubble['body']['contents'][0]['text'])<60
    assert '%26' in bubble['footer']['contents'][0]['action']['uri']
