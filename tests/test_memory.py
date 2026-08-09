"""记忆检索：相似度、时近与重要性影响排序。"""

from machiety.agents.memory import MemoryStream


def test_retrieve_relevance():
    m = MemoryStream()
    m.add("田里的谷物丰收了", tick=10, importance=4.0)
    m.add("我与朋友讨论了远方", tick=12, importance=4.0)
    m.add("干旱让庄稼枯萎，饥饿蔓延", tick=14, importance=6.0)
    results = m.retrieve("饥饿与粮食", tick=15, k=2)
    texts = [r.text for r in results]
    assert any("饥饿" in t or "谷物" in t for t in texts)


def test_core_memory_promotion():
    m = MemoryStream()
    m.add("我目睹了一场神迹", tick=5, importance=9.0)
    assert len(m.core) == 1
    m.add("今天天气不错", tick=6, importance=2.0)
    assert len(m.observations) == 1


def test_observation_limit():
    m = MemoryStream()
    for i in range(60):
        m.add(f"事件{i}", tick=i, importance=2.0)
    assert len(m.observations) <= 50


def test_roundtrip():
    m = MemoryStream()
    m.add("一段记忆", tick=3, importance=8.0)
    data = m.to_dict()
    m2 = MemoryStream.from_dict(data)
    assert len(m2.core) == 1 and m2.core[0].text == "一段记忆"
