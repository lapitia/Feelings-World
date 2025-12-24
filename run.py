from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from kivy.config import Config
Config.set("kivy", "exit_on_escape", "1")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.animation import Animation
from kivy.graphics import Color, RoundedRectangle, PushMatrix, PopMatrix, Rotate

EffectValue = Union[int, List[int]]


@dataclass
class CardDef:
    id: str
    weight: int
    require_flags: List[str]
    forbid_flags: List[str]
    effects_left: Dict[str, EffectValue]
    effects_right: Dict[str, EffectValue]
    set_flags_left: List[str]
    set_flags_right: List[str]
    clear_flags_left: List[str]
    clear_flags_right: List[str]


@dataclass
class GameState:
    stats: Dict[str, int]
    flags: set[str] = field(default_factory=set)
    turn: int = 0
    last_card_id: Optional[str] = None


class Translator:
    def __init__(self, translations_dir: str = "translations"):
        self.dir = translations_dir
        self.lang = "en"
        self.data: Dict[str, str] = {}

    def load(self, lang: str) -> None:
        path = os.path.join(self.dir, f"{lang}.json")
        with open(path, "r", encoding="utf-8") as f:
            self.data = json.load(f)
        self.lang = lang

    def t(self, key: str, *args) -> str:
        s = self.data.get(key, key)
        return s.format(*args) if args else s


def clamp(x: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, x))


def roll(v: EffectValue) -> int:
    if isinstance(v, list) and len(v) == 2:
        return random.randint(int(v[0]), int(v[1]))
    return int(v)


class StatRow(BoxLayout):
    def __init__(self, label_text: str, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None, height=dp(28), spacing=dp(8), **kwargs)
        self.name = Label(text=label_text, size_hint_x=None, width=dp(110))
        self.bar = ProgressBar(max=100, value=50)
        self.value_label = Label(text="50", size_hint_x=None, width=dp(55))
        self.add_widget(self.name)
        self.add_widget(self.bar)
        self.add_widget(self.value_label)

    def set_value(self, v: int) -> None:
        self.bar.value = v
        self.value_label.text = str(v)


class CardWidget(FloatLayout):
    angle = NumericProperty(0.0)

    def __init__(self, on_decide, tr: Translator, **kwargs):
        super().__init__(**kwargs)
        self.on_decide = on_decide
        self.tr = tr
        self.card_id: Optional[str] = None
        self._touch_start_x = 0.0
        self._card_start_center_x = 0.0
        self._swipe_threshold = 0.0
        self._max_tilt_deg = 12.0

        with self.canvas.before:
            PushMatrix()
            self._rot = Rotate(angle=0, axis=(0, 0, 1), origin=self.center)
            self._bg_color = Color(0.12, 0.12, 0.14, 1)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])

        with self.canvas.after:
            PopMatrix()

        self.bind(pos=self._sync_canvas, size=self._sync_canvas, angle=self._sync_angle)

        self.title = Label(
            text="",
            bold=True,
            font_size="22sp",
            size_hint=(1, None),
            height=dp(40),
            pos_hint={"center_x": 0.5, "top": 0.95},
        )

        self.prompt = Label(
            text="",
            font_size="18sp",
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=dp(230),
            pos_hint={"center_x": 0.5, "center_y": 0.55},
        )

        self.hint = Label(
            text=self.tr.t("ui.drag_hint"),
            font_size="18sp",
            halign="center",
            valign="middle",
            size_hint=(1, None),
            height=dp(30),
            pos_hint={"center_x": 0.5, "y": 0.10},
        )

        self.add_widget(self.title)
        self.add_widget(self.prompt)
        self.add_widget(self.hint)

        self.prompt.bind(size=self._sync_prompt_text)
        self._sync_prompt_text()
        self.bind(size=self._sync_hint_text)

    def _sync_prompt_text(self, *args):
        self.prompt.text_size = (self.width * 0.85, None)

    def _sync_hint_text(self, *args):
        if self.hint.text != self.tr.t("ui.drag_hint"):
            self.hint.text_size = (self.width * 0.90, None)
        else:
            self.hint.text_size = (None, None)

    def _sync_canvas(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._rot.origin = self.center

    def _sync_angle(self, *args):
        self._rot.angle = float(self.angle)

    def set_card(self, card_id: str):
        self.card_id = card_id
        self.title.text = self.tr.t(f"card.{card_id}.character")
        self.prompt.text = self.tr.t(f"card.{card_id}.prompt")
        self.hint.text = self.tr.t("ui.drag_hint")
        self.hint.text_size = (None, None)

        self._bg_color.rgba = (0.12, 0.12, 0.14, 1)
        self.angle = 0.0

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)

        Animation.cancel_all(self, "center_x", "center_y", "angle")
        self._touch_start_x = float(touch.x)
        self._card_start_center_x = float(self.center_x)
        self._swipe_threshold = Window.width * 0.22
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_move(touch)

        dx = float(touch.x) - self._touch_start_x
        self.center_x = self._card_start_center_x + dx

        t = max(-1.0, min(1.0, dx / (Window.width * 0.35)))
        self.angle = self._max_tilt_deg * t

        if self.card_id:
            if dx < -self._swipe_threshold * 0.35:
                self.hint.text = f"{self.tr.t('ui.left')}: {self.tr.t(f'card.{self.card_id}.left')}"
                self.hint.text_size = (self.width * 0.90, None)
                self._bg_color.rgba = (0.55, 0.22, 0.22, 1)

            elif dx > self._swipe_threshold * 0.35:
                self.hint.text = f"{self.tr.t('ui.right')}: {self.tr.t(f'card.{self.card_id}.right')}"
                self.hint.text_size = (self.width * 0.90, None)
                self._bg_color.rgba = (0.18, 0.40, 0.25, 1)

            else:
                self.hint.text = self.tr.t("ui.drag_hint")
                self.hint.text_size = (None, None)
                self._bg_color.rgba = (0.12, 0.12, 0.14, 1)

        return True

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)

        touch.ungrab(self)
        dx = float(touch.x) - self._touch_start_x

        if abs(dx) >= self._swipe_threshold:
            direction = "R" if dx > 0 else "L"
            target_x = Window.width + self.width if direction == "R" else -self.width
            anim = Animation(x=target_x, duration=0.12) + Animation(angle=0.0, duration=0.01)
            anim.bind(on_complete=lambda *a: self.on_decide(direction))
            anim.start(self)
        else:
            Animation(center_x=self._card_start_center_x, angle=0.0, duration=0.10).start(self)
            self._bg_color.rgba = (0.12, 0.12, 0.14, 1)
            self.hint.text = self.tr.t("ui.drag_hint")
            self.hint.text_size = (None, None)

        return True


class EndScreen(FloatLayout):
    def __init__(self, tr: Translator, title: str, body: str, final_stats_line: str, on_restart, on_menu, on_quit, **kwargs):
        super().__init__(**kwargs)
        t = Label(
            text=f"[b]{title}[/b]\n\n{body}\n\n{final_stats_line}",
            markup=True,
            font_size="18sp",
            halign="center",
            valign="middle",
            size_hint=(0.92, 0.65),
            pos_hint={"center_x": 0.5, "top": 0.92},
        )
        t.bind(size=lambda inst, val: setattr(inst, "text_size", val))
        self.add_widget(t)

        buttons = BoxLayout(
            orientation="horizontal",
            size_hint=(0.92, None),
            height=dp(52),
            spacing=dp(12),
            pos_hint={"center_x": 0.5, "y": 0.08},
        )

        b_restart = Button(text=tr.t("ui.restart"))
        b_menu = Button(text=tr.t("ui.back_menu"))
        b_quit = Button(text=tr.t("ui.quit"))

        b_restart.bind(on_release=lambda *a: on_restart())
        b_menu.bind(on_release=lambda *a: on_menu())
        b_quit.bind(on_release=lambda *a: on_quit())

        buttons.add_widget(b_restart)
        buttons.add_widget(b_menu)
        buttons.add_widget(b_quit)
        self.add_widget(buttons)


class GameRoot(BoxLayout):
    def __init__(self, tr: Translator, deck: Dict, **kwargs):
        super().__init__(orientation="vertical", padding=dp(12), spacing=dp(10), **kwargs)
        self.tr = tr
        self.deck = deck
        self.stats = list(deck["stats"])
        self.max_turns = int(deck["max_turns"])
        self.cards: List[CardDef] = [CardDef(**c) for c in deck["cards"]]
        self.gs = GameState(stats={k: 50 for k in self.stats})

        self.stats_box = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(28) * len(self.stats) + dp(10),
            spacing=dp(6),
        )

        self.stat_rows: Dict[str, StatRow] = {}
        for k in self.stats:
            row = StatRow(self.tr.t(f"stat.{k}"))
            self.stat_rows[k] = row
            self.stats_box.add_widget(row)

        self.message = Label(text=self.tr.t("ui.survive", self.max_turns), size_hint_y=None, height=dp(28))

        self.stage = FloatLayout()
        self.card = CardWidget(on_decide=self.decide, tr=self.tr, size_hint=(None, None), size=(dp(520), dp(420)))
        self.card.pos_hint = {"center_x": 0.5, "center_y": 0.5}
        self.stage.add_widget(self.card)

        self.add_widget(self.message)
        self.add_widget(self.stats_box)
        self.add_widget(self.stage)

        self.refresh_stats()
        self.next_card()

    def refresh_stats(self):
        for k in self.stats:
            self.stat_rows[k].set_value(self.gs.stats[k])

    def eligible_cards(self) -> List[CardDef]:
        out: List[CardDef] = []
        for c in self.cards:
            if c.id == self.gs.last_card_id:
                continue
            if any(f not in self.gs.flags for f in c.require_flags):
                continue
            if any(f in self.gs.flags for f in c.forbid_flags):
                continue
            out.append(c)
        return out or self.cards[:]

    def pick_card(self) -> CardDef:
        pool = self.eligible_cards()
        weights = [max(1, int(c.weight)) for c in pool]
        return random.choices(pool, weights=weights, k=1)[0]

    def next_card(self):
        c = self.pick_card()
        self.gs.last_card_id = c.id
        self.card.center = (Window.width / 2, Window.height / 2)
        self.card.x = (Window.width - self.card.width) / 2
        self.card.set_card(c.id)

    def apply_effects(self, effects: Dict[str, EffectValue]) -> None:
        for k, v in effects.items():
            if k in self.gs.stats:
                self.gs.stats[k] = clamp(self.gs.stats[k] + 1.5 * roll(v), 0, 100)

    def apply_flags(self, set_flags: List[str], clear_flags: List[str]) -> None:
        for f in set_flags:
            self.gs.flags.add(f)
        for f in clear_flags:
            self.gs.flags.discard(f)

    def check_ending(self) -> Optional[Tuple[str, str]]:
        s = self.gs.stats

        # fails
        if s["joy"] <= 0:
            return (self.tr.t("ending.JOY_LOW.title"), self.tr.t("ending.JOY_LOW.body"))
        if s["joy"] >= 100:
            return (self.tr.t("ending.JOY_HIGH.title"), self.tr.t("ending.JOY_HIGH.body"))
        if s["sadness"] <= 0:
            return (self.tr.t("ending.SADNESS_LOW.title"), self.tr.t("ending.SADNESS_LOW.body"))
        if s["sadness"] >= 100:
            return (self.tr.t("ending.SADNESS_HIGH.title"), self.tr.t("ending.SADNESS_HIGH.body"))
        if s["anger"] <= 0:
            return (self.tr.t("ending.ANGER_LOW.title"), self.tr.t("ending.ANGER_LOW.body"))
        if s["anger"] >= 100:
            return (self.tr.t("ending.ANGER_HIGH.title"), self.tr.t("ending.ANGER_HIGH.body"))
        if s["fear"] <= 0:
            return (self.tr.t("ending.FEAR_LOW.title"), self.tr.t("ending.FEAR_LOW.body"))
        if s["fear"] >= 100:
            return (self.tr.t("ending.FEAR_HIGH.title"), self.tr.t("ending.FEAR_HIGH.body"))
        if s["calm"] <= 0:
            return (self.tr.t("ending.CALM_LOW.title"), self.tr.t("ending.CALM_LOW.body"))
        if s["calm"] >= 100:
            return (self.tr.t("ending.CALM_HIGH.title"), self.tr.t("ending.CALM_HIGH.body"))

        # wins
        if self.gs.turn >= self.max_turns:
            if "resonance_ready" in self.gs.flags:
                return (self.tr.t("ending.RESONANCE.title"), self.tr.t("ending.RESONANCE.body"))
            return (self.tr.t("ending.HARMONY.title"), self.tr.t("ending.HARMONY.body"))

        return None

    def show_end(self, title: str, body: str):
        self.stage.clear_widgets()
        self.message.text = self.tr.t("ui.run_ended")
        s = self.gs.stats
        final_line = self.tr.t("ui.final_stats", s["joy"], s["sadness"], s["anger"], s["fear"], s["calm"])

        def restart():
            self.stage.clear_widgets()
            self.gs = GameState(stats={k: 50 for k in self.stats})
            self.refresh_stats()
            self.card = CardWidget(on_decide=self.decide, tr=self.tr, size_hint=(None, None), size=(dp(520), dp(420)))
            self.card.pos_hint = {"center_x": 0.5, "center_y": 0.5}
            self.stage.add_widget(self.card)
            self.message.text = self.tr.t("ui.survive", self.max_turns)
            self.next_card()

        def menu():
            app = App.get_running_app()
            if app:
                app.go_menu()

        def quit_game():
            app = App.get_running_app()
            if app:
                app.request_quit()

        self.stage.add_widget(EndScreen(self.tr, title, body, final_line, restart, menu, quit_game))

    def decide(self, direction: str):
        if not self.card.card_id:
            return

        cid = self.card.card_id
        c = next((x for x in self.cards if x.id == cid), None)
        if not c:
            return

        if direction == "L":
            self.apply_effects(c.effects_left)
            self.apply_flags(c.set_flags_left, c.clear_flags_left)
        else:
            self.apply_effects(c.effects_right)
            self.apply_flags(c.set_flags_right, c.clear_flags_right)

        self.gs.turn += 1
        self.refresh_stats()

        ending = self.check_ending()
        if ending:
            self.show_end(*ending)
            return

        self.message.text = self.tr.t("ui.turn", self.gs.turn, self.max_turns)
        self.next_card()


class LanguageScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        root = BoxLayout(orientation="vertical", padding=dp(18), spacing=dp(12))

        self.title = Label(text="", font_size="26sp", size_hint=(1, None), height=dp(56))
        root.add_widget(self.title)

        self.subtitle = Label(text="", font_size="18sp", size_hint=(1, None), height=dp(34))
        root.add_widget(self.subtitle)

        btns = BoxLayout(orientation="vertical", spacing=dp(10))
        self.b_en = Button(text="English", size_hint=(1, None), height=dp(54))
        self.b_pl = Button(text="Polski", size_hint=(1, None), height=dp(54))
        self.b_ru = Button(text="Русский", size_hint=(1, None), height=dp(54))

        self.b_en.bind(on_release=lambda *a: App.get_running_app().start_game("en"))
        self.b_pl.bind(on_release=lambda *a: App.get_running_app().start_game("pl"))
        self.b_ru.bind(on_release=lambda *a: App.get_running_app().start_game("ru"))

        btns.add_widget(self.b_en)
        btns.add_widget(self.b_pl)
        btns.add_widget(self.b_ru)
        root.add_widget(btns)

        self.add_widget(root)

    def on_pre_enter(self, *args):
        app = App.get_running_app()
        tr = app.tr
        self.title.text = tr.t("app.title") if tr.data else "FEELINGS WORLD"
        self.subtitle.text = tr.t("menu.choose_language") if tr.data else "Choose language"


class GameScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.container = BoxLayout()
        self.add_widget(self.container)

    def set_game(self, game_root: GameRoot):
        self.container.clear_widgets()
        self.container.add_widget(game_root)


class FeelingsApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.tr = Translator()
        self.deck: Dict = {}
        self.sm = ScreenManager()
        self.lang_screen = LanguageScreen(name="lang")
        self.game_screen = GameScreen(name="game")
        self.sm.add_widget(self.lang_screen)
        self.sm.add_widget(self.game_screen)

    def build(self):
        Window.clearcolor = (0.07, 0.07, 0.08, 1)
        Window.bind(on_request_close=self._on_request_close)
        self.load_deck()
        self.sm.current = "lang"
        return self.sm

    def load_deck(self):
        with open(os.path.join("data", "deck.json"), "r", encoding="utf-8") as f:
            self.deck = json.load(f)

    def start_game(self, lang: str):
        self.tr.load(lang)
        game = GameRoot(tr=self.tr, deck=self.deck)
        self.game_screen.set_game(game)
        self.sm.current = "game"

    def go_menu(self):
        self.sm.current = "lang"

    def _on_request_close(self, *args, **kwargs):
        self.request_quit()
        return True

    def request_quit(self):
        Clock.schedule_once(lambda dt: self.stop(), 0)
        Clock.schedule_once(lambda dt: Window.close(), 0)

    def on_stop(self):
        try:
            Window.close()
        except Exception:
            pass


FeelingsApp().run()
