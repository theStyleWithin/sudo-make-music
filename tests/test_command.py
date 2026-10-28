from sudo_make_music.command import COMMAND, allowed_input, is_command


def test_phrase_matches_with_forgiving_case_and_spacing():
    assert COMMAND == "sudo make music"
    assert is_command("sudo make music") and is_command("  Sudo  Make   MUSIC ")


def test_anything_else_is_rejected():
    for bad in ("", "sudo", "sudo make music now", "sudo make music; rm -rf /", "sudo make musi", "make music",
                "$(sudo make music)", "sudo make music\nls"):
        assert not is_command(bad), bad


def test_input_filter_keeps_only_letters_and_spaces():
    assert allowed_input("sudo make music") == "sudo make music"
    assert allowed_input("rm -rf / ; $(x) | `y` && z\n") == "rm rf   x  y  z"
