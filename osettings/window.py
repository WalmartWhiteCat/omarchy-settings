"""Main window: sidebar of sections, lazily built pages, toasts and "Restore all"."""

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .core import DEFAULT_THEME, confirm
from .pages_keys import AutostartPage, KeysPage, leave_capture
from .pages_look import BackgroundPage, ColorsPage, RulesPage, ThemePage, WindowsPage
from .pages_system import (AppsPage, BarPage, CursorPage, DisplaysPage, InputPage, NightLightPage, PowerPage,
                           TextPage)
from .store import Store

SECTIONS = [
    ("Appearance", [ThemePage, ColorsPage, BackgroundPage, WindowsPage, RulesPage]),
    ("Display", [DisplaysPage, NightLightPage, TextPage, CursorPage]),
    ("Input", [InputPage, KeysPage]),
    ("System", [BarPage, PowerPage, AppsPage, AutostartPage]),
]
# Theme near the end (slowest, and it picks a wallpaper), then that theme's first stock wallpaper.
RESET_ORDER = ["windows", "rules", "displays", "input", "keys", "autostart", "nightlight", "text", "cursor",
               "power", "bar", "colors", "theme", "background"]

CSS = """
.keycap { font-family: monospace; font-size: 0.9em; padding: 2px 8px; border-radius: 6px;
          background: alpha(currentColor, 0.08); border: 1px solid alpha(currentColor, 0.15); }
.sidebar-heading { font-size: 0.8em; font-weight: bold; opacity: 0.6; margin: 12px 12px 4px; }
"""


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Omarchy Settings", default_width=1040, default_height=760)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.store = Store(self.on_store_result)
        self.store.sync_file()
        self.toasts = Adw.ToastOverlay()
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.classes = {}

        sidebar = Gtk.ListBox(selection_mode=Gtk.SelectionMode.BROWSE)
        sidebar.add_css_class("navigation-sidebar")
        headings = {}
        for section, classes in SECTIONS:
            for i, cls in enumerate(classes):
                self.classes[cls.key] = cls
                box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6)
                box.append(Gtk.Image.new_from_icon_name(cls.icon))
                box.append(Gtk.Label(label=cls.title, xalign=0))
                row = Gtk.ListBoxRow(child=box)
                row.key = cls.key
                sidebar.append(row)
                if i == 0:
                    headings[row] = section
        sidebar.set_header_func(lambda row, _before: row.set_header(self.heading(headings[row]))
                                if row in headings else row.set_header(None))
        sidebar.connect("row-selected", lambda _l, r: r and self.select(r.key))
        self.sidebar = sidebar

        side_view = Adw.ToolbarView()
        side_view.add_top_bar(Adw.HeaderBar(show_title=False))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, child=sidebar)
        side_view.set_content(scroller)

        self.content = Adw.NavigationPage(title="Theme")
        content_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append("Restore all defaults…", "win.reset-all")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))
        action = Gio.SimpleAction.new("reset-all", None)
        action.connect("activate", lambda *_: self.confirm_reset_all())
        self.add_action(action)
        content_view.add_top_bar(header)
        content_view.set_content(self.stack)
        self.content.set_child(content_view)

        self.split = Adw.NavigationSplitView(sidebar=Adw.NavigationPage(title="Settings", child=side_view),
                                             content=self.content, min_sidebar_width=220)
        self.toasts.set_child(self.split)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(self.split, "collapsed", True)
        self.add_breakpoint(bp)
        self.connect("close-request", lambda *_: leave_capture() or False)
        sidebar.select_row(sidebar.get_row_at_index(0))

    @staticmethod
    def heading(text):
        label = Gtk.Label(label=text.upper(), xalign=0)
        label.add_css_class("sidebar-heading")
        return label

    # ------------------------------------------------------------ pages

    def page(self, key):
        """The page for `key`, building it on first use."""
        page = self.stack.get_child_by_name(key)
        if page is None:
            page = self.classes[key](self)
            self.stack.add_named(page, key)
        return page

    def select(self, key):
        row = self.sidebar.get_selected_row()
        if row is None or row.key != key:
            i = 0
            while (r := self.sidebar.get_row_at_index(i)) is not None:
                if r.key == key:
                    self.sidebar.select_row(r)  # re-enters select() through row-selected
                    return
                i += 1
        page = self.page(key)
        self.stack.set_visible_child(page)
        self.content.set_title(page.get_title())
        self.split.set_show_content(True)

    def replace_page(self, key, page):
        old = self.stack.get_child_by_name(key)
        visible = old is not None and self.stack.get_visible_child() is old
        if old is not None:
            self.stack.remove(old)
        self.stack.add_named(page, key)
        if visible:
            self.stack.set_visible_child(page)

    def theme_changed(self):
        """A theme switch changes the palette and wallpaper list: refresh those pages if built."""
        for key in ("colors", "background"):
            if self.stack.get_child_by_name(key) is not None:
                self.replace_page(key, self.classes[key](self))

    # ------------------------------------------------------------ restore all

    def confirm_reset_all(self):
        confirm(self, "Restore all defaults?",
                f"Everything this app controls goes back to Omarchy's defaults: the {DEFAULT_THEME} theme and its "
                "wallpaper, theme colors, window look, app rules, displays, night light, keyboard and mouse, "
                "keybindings, startup items, fonts, cursor, bar, idle and notifications. Installed themes, added "
                "wallpapers, bar widgets and default apps are kept.",
                self.reset_all, label="Restore all")

    def reset_all(self):
        steps = list(RESET_ORDER)

        def next_step():
            if not steps:
                self.toast("All settings restored to defaults")
                return
            key = steps.pop(0)
            try:
                self.page(key).reset(lambda: GLib.idle_add(lambda: next_step() and False))
            except Exception as e:  # keep going; report what failed
                self.toast(f"{key}: {e}")
                next_step()

        next_step()

    # ------------------------------------------------------------ feedback

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(str(text)), timeout=3))

    def busy(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=2))

    def on_store_result(self, errors):
        if errors:
            self.toast(f"Hyprland config: {errors.splitlines()[0][:160]}")


class SettingsApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="org.omarchy.Settings", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        win = self.props.active_window or SettingsWindow(self)
        win.present()
