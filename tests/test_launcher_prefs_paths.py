"""What may be kept in a player's settings slot, and under what key.

The slot is a JSON blob on someone's account that the launcher writes into, so the key is
checked rather than trusted: a fixed set of files a player edits in the game, optionally
prefixed by the server they belong to.
"""

from apps.api.app.services.launcher_prefs_service import (
    is_allowed_config_path,
    split_config_path,
)


def test_bare_paths_are_the_ones_the_launcher_wrote_before_servers_were_separate():
    assert is_allowed_config_path("options.txt")
    assert split_config_path("options.txt") == (None, "options.txt")


def test_a_server_may_keep_its_own_copy():
    # The same account plays packs of different Minecraft versions; one slot for all of
    # them restored the last server's keys onto the next one.
    assert is_allowed_config_path("voidrp/options.txt")
    assert split_config_path("origins/config/iris.properties") == (
        "origins",
        "config/iris.properties",
    )


def test_the_graphics_files_a_pack_can_ship_are_allowed():
    for path in (
        "config/embeddium-options.json",
        "config/sodium-options.json",
        "config/iris.properties",
    ):
        assert is_allowed_config_path(path), path


def test_anything_else_is_refused():
    for path in (
        "../../etc/passwd",
        "evil/../options.txt",
        "options.txt/../x",
        "VOIDRP/options.txt",          # a slug is lower case
        "config/server.properties",
        "",
    ):
        assert not is_allowed_config_path(path), path
