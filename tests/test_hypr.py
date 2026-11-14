import unittest

from magic_piano.hypr import (
    Hyprland,
    HyprlandKeyboard,
    Window,
    lua_string,
    parse_selector,
)


class FakeClient:
    def __init__(self, windows=()):
        self.calls = []
        self._windows = list(windows)

    def eval(self, code):
        self.calls.append(code)

    def windows(self):
        return list(self._windows)


def window(name, class_name="org.vinegarhq.Sober", title="Sober"):
    return Window(address=name, class_name=class_name, title=title)


class SelectorTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_selector("class:foo"), ("class", "foo"))
        self.assertEqual(parse_selector("title:Sober"), ("title", "Sober"))
        self.assertEqual(parse_selector("address:0xabc"), ("address", "0xabc"))
        self.assertEqual(parse_selector("foo"), ("class", "foo"))
        self.assertEqual(parse_selector("weird:value"), ("class", "weird:value"))

    def test_lua_string_escapes(self):
        self.assertEqual(lua_string('a"b\\c'), '"a\\"b\\\\c"')
        self.assertEqual(lua_string("Микки"), '"Микки"')

    def test_find_matches_class_first(self):
        hypr = Hyprland.__new__(Hyprland)
        hypr.windows = lambda: [
            window("0x1", "kitty", "Sober"),
            window("0x2", "org.vinegarhq.Sober", "Sober"),
        ]
        self.assertEqual(hypr.find("class:org.vinegarhq.Sober").address, "0x2")
        self.assertEqual(hypr.find("title:Sober").address, "0x1")
        self.assertIsNone(hypr.find("class:missing"))


class KeyboardTest(unittest.TestCase):
    def test_snippet_targets_class(self):
        client = FakeClient()
        keyboard = HyprlandKeyboard("class:org.vinegarhq.Sober", client=client)
        keyboard.press("q", True)
        code = client.calls[0]
        self.assertIn('v.class=="org.vinegarhq.Sober"', code)
        self.assertIn('mods="SHIFT"', code)
        self.assertIn('key="q"', code)
        self.assertIn('state="down"', code)
        self.assertIn("window=w", code)

    def test_white_key_has_no_mods(self):
        client = FakeClient()
        keyboard = HyprlandKeyboard("title:Sober", client=client)
        keyboard.press("3", False)
        code = client.calls[0]
        self.assertIn('mods=""', code)
        self.assertIn("v.title", code)

    def test_focused_mode_omits_window(self):
        client = FakeClient()
        keyboard = HyprlandKeyboard(None, client=client)
        keyboard.press("1", False)
        self.assertNotIn("window", client.calls[0])

    def test_release_sends_up_once(self):
        client = FakeClient()
        keyboard = HyprlandKeyboard("class:X", client=client)
        keyboard.press("1", True)
        keyboard.release("1", True)
        keyboard.release("1", True)  # already released: ignored
        self.assertEqual(len(client.calls), 2)
        self.assertIn('state="up"', client.calls[1])

    def test_release_all_releases_held_keys(self):
        client = FakeClient()
        keyboard = HyprlandKeyboard("class:X", client=client)
        keyboard.press("1", True)
        keyboard.press("3", False)
        keyboard.release_all()
        self.assertEqual(len(client.calls), 4)
        self.assertIn('state="up"', client.calls[2])
        self.assertIn('state="up"', client.calls[3])
        self.assertEqual(keyboard._held, {})

    def test_address_selector(self):
        client = FakeClient()
        keyboard = HyprlandKeyboard("address:0x55", client=client)
        keyboard.press("a", False)
        self.assertIn('v.address=="0x55"', client.calls[0])


if __name__ == "__main__":
    unittest.main()
