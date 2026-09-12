from livescreen_translator.ocr import TextBlock, merge_lines, parse_paddle_result


POLY = [[10, 10], [110, 10], [110, 40], [10, 40]]


def test_parse_v2_nested_format():
    raw = [[[POLY, ("开始游戏", 0.95)], [POLY, ("Start", 0.99)], [POLY, ("低分", 0.2)]]]
    blocks = parse_paddle_result(raw, min_confidence=0.5)
    assert [b.text for b in blocks] == ["开始游戏"]
    b = blocks[0]
    assert (b.x, b.y, b.width, b.height) == (10, 10, 100, 30)


def test_parse_v2_flat_format():
    raw = [[POLY, ("你好", 0.9)]]
    assert parse_paddle_result(raw)[0].text == "你好"


def test_parse_v3_dict_format():
    raw = [{"rec_texts": ["你好", "abc"], "rec_scores": [0.9, 0.9], "rec_polys": [POLY, POLY]}]
    blocks = parse_paddle_result(raw)
    assert len(blocks) == 1 and blocks[0].text == "你好"


def test_parse_empty():
    assert parse_paddle_result(None) == []
    assert parse_paddle_result([None]) == []
    assert parse_paddle_result([[]]) == []


def test_merge_lines_merges_adjacent():
    a = TextBlock("第一行", 0.9, 10, 10, 200, 20)
    b = TextBlock("第二行", 0.9, 12, 34, 190, 20)
    c = TextBlock("远处", 0.9, 400, 300, 50, 20)
    merged = merge_lines([c, b, a])
    assert len(merged) == 2
    assert merged[0].text == "第一行第二行"
    assert merged[0].height == 44
