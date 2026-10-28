"""Тесты без интернета: крошечная случайная BERT-модель создаётся прямо в тесте."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")

from ml.embeddings import encode_texts  # noqa: E402


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory):
    d = tmp_path_factory.mktemp("tiny")
    chars = list("абвгдеёжзийклмнопрстуфхцчшщъыьэюя .,!?")
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"] + chars + ["##" + c for c in chars if c != " "]
    (d / "vocab.txt").write_text("\n".join(vocab), encoding="utf-8")
    tok = transformers.BertTokenizerFast(vocab_file=str(d / "vocab.txt"), do_lower_case=True)
    tok.save_pretrained(d)
    cfg = transformers.BertConfig(vocab_size=len(vocab), hidden_size=16, num_hidden_layers=1,
                                  num_attention_heads=2, intermediate_size=32, max_position_embeddings=64)
    torch.manual_seed(0)
    transformers.BertModel(cfg).save_pretrained(d)
    return str(d)


TEXTS = ["яма на дороге", "не горит фонарь", "мусор во дворе", "яма на дороге"]


def test_shape_and_norm(tiny_model):
    e = encode_texts(TEXTS, model_name=tiny_model, batch_size=2, max_length=16)
    assert e.shape == (4, 16)
    assert np.allclose(np.linalg.norm(e, axis=1), 1, atol=1e-4)


def test_same_text_same_vector_and_batch_independent(tiny_model):
    a = encode_texts(TEXTS, model_name=tiny_model, batch_size=1, max_length=16)
    b = encode_texts(TEXTS, model_name=tiny_model, batch_size=4, max_length=16)
    assert np.allclose(a[0], a[3], atol=1e-5)
    assert np.allclose(a, b, atol=1e-4)


def test_mean_pooling_differs_from_cls(tiny_model):
    c = encode_texts(TEXTS, model_name=tiny_model, pooling="cls", max_length=16)
    m = encode_texts(TEXTS, model_name=tiny_model, pooling="mean", max_length=16)
    assert not np.allclose(c, m)


def test_cache_is_used(tiny_model, tmp_path):
    a = encode_texts(TEXTS, model_name=tiny_model, cache_dir=str(tmp_path), max_length=16)
    assert len(list(tmp_path.glob("emb_*.npy"))) == 1
    b = encode_texts(TEXTS, model_name=tiny_model, cache_dir=str(tmp_path), max_length=16)
    assert np.array_equal(a, b)


def test_bad_pooling():
    with pytest.raises(ValueError):
        encode_texts(["а"], pooling="max")
