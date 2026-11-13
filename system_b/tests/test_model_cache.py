"""Model answers are kept between runs (2026-11-13)."""

from system_b.gift import model_cache


def test_an_answer_is_kept_and_read_back(tmp_path, monkeypatch):
    monkeypatch.setattr(model_cache, "PATH", tmp_path / "model-cache.json")
    monkeypatch.setattr(model_cache, "_mem", None)
    assert model_cache.get("fit", "construction", "lead:1") is None
    model_cache.put("fit", "construction", "lead:1", value=True)
    model_cache.flush()
    monkeypatch.setattr(model_cache, "_mem", None)          # a new run reads the file
    assert model_cache.get("fit", "construction", "lead:1") is True
