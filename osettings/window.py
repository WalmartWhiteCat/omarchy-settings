"""Main window: sidebar of sections, lazily built pages, toasts and "Restore all"."""

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .binds import parse_default_binds
from .core import DEFAULT_THEME, confirm
from .pages_keys import AutostartPage, KeysPage, leave_capture
from .pages_look import BackgroundPage, ColorsPage, RulesPage, ThemePage, WindowsPage, undo_all_color_edits
from .pages_system import (AppsPage, BarPage, CursorPage, DisplaysPage, InputPage, NightLightPage, PowerPage,
                           TextPage)
from .pages_widgets import NotesPage
from .store import Store

SECTIONS = [
    ("Appearance", [ThemePage, ColorsPage, BackgroundPage, WindowsPage, RulesPage]),
    ("Display", [DisplaysPage, NightLightPage, TextPage, CursorPage]),
    ("Input", [InputPage, KeysPage]),
    ("System", [BarPage, PowerPage, AppsPage, AutostartPage]),
    ("Widgets", [NotesPage]),
]
# Theme near the end (slowest, and it picks a wallpaper), then that theme's first stock wallpaper.
PAGES = {cls.key for _, classes in SECTIONS for cls in classes}
RESET_ORDER = ["windows", "rules", "displays", "input", "keys", "autostart", "nightlight", "text", "cursor",
               "power", "bar", "notes", "colors", "theme", "background"]

CSS = """
.keycap { font-family: monospace; font-size: 0.9em; padding: 2px 8px; border-radius: 6px;
          background: alpha(currentColor, 0.08); border: 1px solid alpha(currentColor, 0.15); }
.sidebar-heading { font-size: 0.8em; font-weight: bold; opacity: 0.6; margin: 12px 12px 4px; }
"""


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app, page=None):
        """Opens on `page` (a page key), else the first page. Only that page is built."""
        super().__init__(application=app, title="Omarchy Settings", default_width=1040, default_height=760)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.store = Store(self.on_store_result)
        if not self.store.set_aside:
            # After a damaged settings.json, keep the last good Lua file until the user changes
            # something, rather than replacing it with an empty one at startup.
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
        self.connect("close-request", lambda *_: leave_capture(wait=True) or False)
        self.select(page if page in self.classes else SECTIONS[0][1][0].key)
        if self.store.load_warning:
            self.toast(self.store.load_warning)
        self.refresh_rebinds()

    def refresh_rebinds(self):
        """Keep changed shortcuts in step with Omarchy's binding files after an update."""
        if not self.store.binds["rebinds"]:
            return
        changed, dropped = self.store.refresh_rebinds(parse_default_binds())
        if changed:
            self.store.save_now()
        if dropped:
            self.toast(f"Omarchy no longer has {len(dropped)} shortcut(s) you had changed, so those changes "
                       f"were removed: {', '.join(dropped)[:120]}")

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
                "keybindings, startup items, fonts, cursor, bar, idle and notifications, and the Desktop Notes "
                "widget's look and place. Installed themes, added wallpapers, bar widgets, default apps and your "
                "notes are kept.",
                self.reset_all, label="Restore all")

    def reset_all(self):
        steps = list(RESET_ORDER)

        def next_step():
            if not steps:
                self.toast("All settings restored to defaults")
                return
            key = steps.pop(0)
            if key == "colors":
                # Every theme's edits, not just the current one's; the theme step that follows
                # applies the default theme from the restored files.
                undo_all_color_edits()
                return next_step()
            try:
                self.page(key).reset(lambda: GLib.idle_add(lambda: next_step() and False))
            except Exception as e:  # keep going; report what failed
                self.toast(f"{key}: {e}")
                next_step()

        next_step()

    # ------------------------------------------------------------ feedback

    def toast(self, text):
        text = str(text)
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6 if len(text) > 80 else 3))

    def busy(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=2))

    def on_store_result(self, errors):
        if errors:
            self.toast(f"Hyprland config: {errors.splitlines()[0][:160]}")


class SettingsApp(Adw.Application):
    def __init__(self):
        # Command lines reach the running instance, so `--page` works when the app is already open
        # (the Desktop Notes widget's settings button uses it).
        super().__init__(application_id="org.omarchy.Settings", flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("page", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
                             "Open on this page, e.g. notes", "KEY")

    def do_activate(self):
        (self.props.active_window or SettingsWindow(self)).present()

    # A first window opens straight on the page asked for, so the slow Theme page isn't built
    # just to be switched away from.
    def do_command_line(self, command_line):
        value = command_line.get_options_dict().lookup_value("page", GLib.VariantType.new("s"))
        key = value.get_string() if value else None
        note = None
        if key is not None and key not in PAGES:
            note, key = f"There's no settings page called “{key}”", None
        win = self.props.active_window
        if win is None:
            win = SettingsWindow(self, page=key)
        elif key:
            win.select(key)
        win.present()
        if note:
            win.toast(note)
        return 0
