from pyjpdfium import OcrLine, OcrResult


def result(*lines):
    return OcrResult(image_size=(1000, 800), dpi=(300.0, 300.0), profile="p", lines=lines)


def line(text, polygon):
    return OcrLine(text, polygon, 0.99, 0.9)


def test_box_bounds_a_rotated_polygon():
    assert line("a", ((10, 20), (110, 15), (112, 45), (12, 50))).box == (10, 15, 112, 50)


def test_text_lines_keep_each_line_whole():
    r = result(line("hello world", ((10, 10), (200, 10), (200, 40), (10, 40))),
               line("   ", ((10, 50), (20, 50), (20, 60), (10, 60))),
               line("next", ((10, 70), (60, 70), (60, 90), (10, 90))))
    text_lines = r.text_lines()
    # Word geometry is absent: a line is one word over its box, never split evenly.
    assert [tl.words[0].text for tl in text_lines] == ["hello world", "next"]
    assert text_lines[0].words[0].box == text_lines[0].box == (10, 10, 200, 40)
    # The polygon places the line, so rotated or skewed lines keep their slope.
    quad = ((10, 10), (200, 10), (200, 40), (10, 40))
    assert text_lines[0].quad == text_lines[0].words[0].quad == quad
    assert r.text == "hello world\n   \nnext"
