import pytest
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder

import main


class FakeNetwork:
    """Stand-in for NetworkManager: no real sockets/threads, just a place
    to bind events and record outgoing messages."""

    def __init__(self, player_name):
        self.me = player_name
        self.addr_opponent = None
        self.sent = []

    def bind(self, **kwargs):
        pass

    def start_search_for_opponent(self):
        pass

    def stop_search_for_opponent(self):
        pass

    def send_game_data(self, data):
        self.sent.append(data)

    def cleanup(self):
        pass


@pytest.fixture(scope="module", autouse=True)
def load_kv():
    Builder.load_file("pong.kv")


@pytest.fixture
def game(monkeypatch):
    monkeypatch.setattr(main, "NetworkManager", FakeNetwork)
    instance = main.PongGame()
    Window.add_widget(instance)
    instance.game_owner = True
    instance.enemy_name = "Bob"

    yield instance

    if instance._update_event is not None:
        instance._update_event.cancel()
    Window.remove_widget(instance)


def test_reconnect_does_not_double_schedule_update(game):
    game.init_game_connection()

    calls = []
    original_update = game.update

    def counting_update(dt):
        calls.append(1)
        return original_update(dt)

    game.update = counting_update

    # Simulate a disconnect/reconnect cycle re-entering init_game_connection().
    game.init_game_connection()
    Clock.tick()

    assert len(calls) == 1


def test_network_reset_scores_re_serves_ball(game):
    game.init_game_connection()
    game.ball.pos = [9999, 9999]

    game.on_game_status_update(game.network, {"reset_scores": True})

    assert list(game.ball.center) == list(game.center)


def test_button_reset_re_serves_ball_when_game_over(game):
    game.init_game_connection()
    game.is_connected = True
    game.is_synchronized = True
    game.game_over = True
    game.player1.score = main.POINTS_TO_WIN
    game.ball.pos = [9999, 9999]

    game.on_press_pause_play()

    assert list(game.ball.center) == list(game.center)
    assert {"reset_scores": True}.items() <= game.network.sent[-1].items()
