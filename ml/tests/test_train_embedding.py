"""Сквозной прогон скрипта на крошечной случайной модели: проверяем, что всё запускается и пишет результаты."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
import torch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "appeals_synthetic.csv"


@pytest.mark.skipif(not DATA.exists(), reason="нет data/appeals_synthetic.csv")
def test_script_runs_end_to_end(tmp_path):
    chars = list("абвгдеёжзийклмнопрстуфхцчшщъыьэюя .,!?-0123456789abcdefghijklmnopqrstuvwxyz")
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"] + chars + ["##" + c for c in chars if c != " "]
    m = tmp_path / "tiny"
    m.mkdir()
    (m / "vocab.txt").write_text("\n".join(vocab), encoding="utf-8")
    transformers.BertTokenizerFast(vocab_file=str(m / "vocab.txt")).save_pretrained(m)
    cfg = transformers.BertConfig(vocab_size=len(vocab), hidden_size=16, num_hidden_layers=1,
                                  num_attention_heads=2, intermediate_size=32, max_position_embeddings=256)
    torch.manual_seed(0)
    transformers.BertModel(cfg).save_pretrained(m)

    out = tmp_path / "res"
    r = subprocess.run(
        [sys.executable, str(ROOT / "ml" / "train_embedding_clf.py"), "--data", str(DATA), "--out", str(out),
         "--models", str(tmp_path / "mod"), "--cache", str(tmp_path / "cache"), "--model-name", str(m),
         "--tag", "test_run"],
        capture_output=True, text=True, cwd=ROOT, timeout=900)
    assert r.returncode == 0, r.stderr[-2000:]
    res = json.loads((out / "test_run.json").read_text(encoding="utf-8"))
    assert set(res) == {"A_grouped", "B_heldout_subtopics", "C_random_leak"}
    for v in res.values():
        assert 0 <= v["test"]["macro_f1"] <= 1
        assert v["test"]["accuracy"] > v["dummy_majority"]["accuracy"] * 0.5
    assert (out / "cm_emb_A_grouped.png").exists()
