import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QT = (ROOT / "scripts/recomp/runtime/app/linux/qt_ui.cpp").read_text(encoding="utf-8")
SDL = (ROOT / "scripts/recomp/runtime/nvn/vulkan/src/nvn/vulkan/device.c").read_text(encoding="utf-8")


class FullscreenKeyTests(unittest.TestCase):
    """The Qt window (Windows and Linux) must toggle borderless full screen with F11 and Alt+Enter, work with the menu bar hidden,
    and give the screen back to the game: these are source checks because the window needs a display to run."""

    def test_qt_window_binds_f11_and_alt_enter_as_application_shortcuts(self):
        keys = re.search(r'for \(const char \*key : \{([^}]*)\}\)', QT).group(1)
        for key in ("F11", "Alt+Return", "Alt+Enter", "Ctrl+F"):
            self.assertIn('"%s"' % key, keys)
        self.assertIn("Qt::ApplicationShortcut", QT)   # menu shortcuts die with the hidden menu bar

    def test_full_screen_hides_the_menu_bar_and_leaving_it_brings_it_back(self):
        body = QT[QT.index("void setFullscreen(bool on)"):]
        body = body[:body.index("\n    }")]
        self.assertIn("showFullScreen()", body)
        self.assertIn("showNormal()", body)
        self.assertIn("menuBar()->setVisible(!on)", body)

    def test_the_mouse_pointer_is_hidden_in_full_screen_except_for_the_on_screen_keyboard(self):
        cursor = QT[QT.index("void updateCursor()"):]
        cursor = cursor[:cursor.index("\n    }")]
        self.assertIn("isFullScreen() && !swkbd_ui_active()", cursor)
        self.assertIn("Qt::BlankCursor", cursor)
        self.assertIn("rw_->setCursor", cursor)   # the Vulkan window is its own native window and has its own pointer
        self.assertIn("updateCursor();", QT[QT.index("void setFullscreen(bool on)"):QT.index("void runScript")])

    def test_a_fixed_window_size_leaves_full_screen_through_the_same_path(self):
        size = QT[QT.index("void setSize(int w, int h)"):]
        self.assertIn("setFullscreen(false)", size[:size.index("resize(")])

    def test_the_sdl_window_toggles_with_alt_enter_too(self):
        self.assertIn("k == SDLK_F11 || (k == SDLK_RETURN && (e.key.mod & SDL_KMOD_ALT))", SDL)
        self.assertIn("SDL_SetWindowFullscreen(window", SDL)

    def test_the_game_can_start_in_full_screen(self):
        self.assertIn('qEnvironmentVariableIntValue("BDSP_FULLSCREEN") > 0', QT)


if __name__ == "__main__":
    unittest.main()
