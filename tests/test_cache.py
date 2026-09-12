from livescreen_translator.cache import TranslationCache


def test_put_get_and_normalization():
    c = TranslationCache(10)
    c.put("你好  世界", "Hello world")
    assert c.get("你好 世界") == "Hello world"
    assert c.get(" 你好\n世界 ") == "Hello world"
    assert "你好 世界" in c
    assert c.hits == 2 and c.misses == 0


def test_miss_returns_none():
    c = TranslationCache(10)
    assert c.get("x") is None
    assert c.misses == 1


def test_lru_eviction():
    c = TranslationCache(2)
    c.put("a", "A"); c.put("b", "B")
    assert c.get("a") == "A"
    c.put("c", "C")
    assert c.get("b") is None
    assert c.get("a") == "A" and c.get("c") == "C"
    assert len(c) == 2


def test_ignores_empty():
    c = TranslationCache(5)
    c.put("", "x"); c.put("a", "")
    assert len(c) == 0


def test_clear():
    c = TranslationCache(5); c.put("a", "A"); c.clear()
    assert len(c) == 0


def test_get_similar():
    c = TranslationCache(10)
    c.put("请输入您的名称", "Please enter your name")
    assert c.get_similar("请输入您的名称。", 0.8) == "Please enter your name"
    assert c.get_similar("完全不同的文字", 0.8) is None
