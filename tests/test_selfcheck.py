from sudo_make_music import selfcheck


def test_selfcheck_passes_with_mock_engines(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_MAKE_MUSIC_HOME", str(tmp_path))
    ok, lines = selfcheck.run()
    text = "\n".join(lines)
    assert ok, text
    assert "SELFCHECK PASSED" in text and "[ok]   mock song + mp3 export" in text
    assert "[ok]   voice library + talk mode" in text


def test_selfcheck_cli_writes_report_and_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("SUDO_MAKE_MUSIC_HOME", str(tmp_path))
    report = tmp_path / "report.txt"
    assert selfcheck.main(str(report)) == 0
    assert "SELFCHECK PASSED" in report.read_text()
