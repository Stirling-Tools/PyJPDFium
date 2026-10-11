import pytest

from pyjpdfium import TextLine, TextWord, errors
from pyjpdfium.textlayer import write_text_layer


def one_word(text):
    box = (0.0, 0.0, 100.0, 50.0)
    return [TextLine(box, (TextWord(text, box),))]


# Both are refused before the native library is needed: it would truncate or reject them.
@pytest.mark.parametrize("text", ["a\x00b", "\ud800"])
def test_text_that_cannot_cross_the_c_abi_is_refused_in_python(tmp_path, text):
    with pytest.raises(errors.InvalidArgumentError):
        write_text_layer(tmp_path / "x.pdf", one_word(text), image_size=(100, 100), dpi=300)


def test_models_are_frozen():
    word = TextWord("a", (0, 0, 1, 1))
    with pytest.raises(AttributeError):
        word.text = "b"  # type: ignore[misc]
