import hashlib

import pytest

from pyjpdfium import cli, errors
from pyjpdfium.profiles import read_profile, verify_profile


def fake_profile(directory, content=b"model bytes"):
    directory.mkdir()
    (directory / "det.onnx").write_bytes(content)
    digest = hashlib.sha256(b"model bytes").hexdigest()
    (directory / "profile.txt").write_text(
        f"format 1\nid tiny\nfile detector det.onnx {digest} https://example.invalid/det.onnx\n",
        encoding="utf-8",
    )
    return directory


def test_a_matching_profile_verifies(tmp_path):
    profile = verify_profile(fake_profile(tmp_path / "p"))
    assert profile.id == "tiny" and [f.name for f in profile.files] == ["det.onnx"]


def test_a_changed_file_is_named(tmp_path):
    directory = fake_profile(tmp_path / "p", content=b"other bytes")
    assert read_profile(directory).id == "tiny"  # parsing alone does not hash
    with pytest.raises(errors.InvalidArgumentError, match="det.onnx does not match"):
        verify_profile(directory)


def test_a_directory_without_a_manifest_is_refused(tmp_path):
    with pytest.raises(errors.InvalidArgumentError, match="profile.txt"):
        verify_profile(tmp_path)


def test_fonts_needs_no_native_code(capsys):
    assert cli.main(["fonts"]) == 0
    assert capsys.readouterr().out.startswith("glyphless")


def test_models_reports_a_bad_profile(tmp_path, capsys):
    assert cli.main(["models", str(tmp_path)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_usage_errors_exit_2():
    with pytest.raises(SystemExit) as raised:
        cli.main(["render"])
    assert raised.value.code == 2
