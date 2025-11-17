# Copyright [2025] [ecki]
# SPDX-License-Identifier: Apache-2.0

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import (NumericProperty, ReferenceListProperty, ObjectProperty,
                             BooleanProperty, StringProperty)
from kivy.uix.widget import Widget
from kivy.vector import Vector

import logging
import json
import random

import include.multicast.vault_multicast as helper_multicast
import include.udp.vault_ip as helper_ip
import include.udp.vault_udp_socket as helper_udp

from kivy.event import EventDispatcher

logger = logging.getLogger(__name__)


MAX_BALL_SPEED = 38
POINTS_TO_WIN = 10
PADDLE_MOVE_SPEED = 80
BALL_START_SPEED = 6
PADDLE_CONTROL_AREA_FACTOR = 1/3


class NetworkManager(EventDispatcher):
    """Manages network communication for the Pong game with updated UDP socket API."""

    __events__ = ('on_opponent_found', 'on_game_data_update', 'on_game_status_update',
                  'on_score_update', 'on_game_init')

    def __init__(self, player_name):
        super().__init__()
        self.me = player_name

        # Get IP address using new API
        ipv4_list, ipv6_list = helper_ip.get_ip_addresses()
        self.ip = ipv4_list[0] if ipv4_list else "127.0.0.1"
        self.port = random.randint(2000, 20000)

        self.sd_type = "pong"
        self.listener = helper_multicast.VaultMultiListener()

        # Initialize UDP socket with new API
        self.udp = helper_udp.UDPSocketClass(recv_port=self.port)

        # Get public keys from encryption manager
        self.pub_key = self.udp._encryption.enc_public_key
        self.sign_key = self.udp._encryption.sign_public_key
        self.addr_opponent = None

        # Multicast publisher and listener
        self.mc_msg = {
            "addr": (self.ip, self.port),
            "name": player_name,
            "enc_key": self.pub_key,
            "sign_key": self.sign_key,
            "type": self.sd_type
        }
        self.publisher = helper_multicast.VaultMultiPublisher()

        # Connect signal with new API
        self.udp.udp_recv_data.connect(self._handle_udp_data)

        # Mapping von Daten-Keys zu Event-Namen
        self.event_map = {
            "score_pl1": "on_score_update",
            "score_pl2": "on_score_update",
            "pad_pos": "on_game_data_update",
            "ball_vel": "on_game_data_update",
            "ball_pos": "on_game_data_update",
            "pause": "on_game_status_update",
            "win_size": "on_game_status_update",
            "reset_scores": "on_game_status_update",
            "game_close": "on_game_status_update",
        }

    def update_opponent_ip(self, addr, enc_key=None, sign_key=None):
        """Update opponent address and keys using new API."""
        self.addr_opponent = addr

        # Add peer to UDP socket
        if not self.udp.has_peer(addr):
            self.udp.add_peer(addr)
            logger.info(f"Added peer {addr}")

        # Update encryption keys if provided
        if enc_key and sign_key:
            self.udp._encryption.update_peer_keys(addr, enc_key, sign_key)
            logger.debug(f"Updated keys for {addr}")

    def start_search_for_opponent(self):
        """Start multicast search for opponents."""
        self.listener = helper_multicast.VaultMultiListener()
        self.listener.start()
        self.listener.recv_signal.connect(self._handle_multicast_message)
        self.publisher.update_message(json.dumps(self.mc_msg))
        self.publisher.start()
        logger.info("Started opponent search")

    def stop_search_for_opponent(self):
        """Stop multicast search."""
        self.listener.recv_signal.disconnect(self._handle_multicast_message)
        self.listener.stop()
        self.publisher.stop()
        logger.info("Stopped opponent search")

    def send_game_data(self, data):
        """Send game data via UDP with new API."""
        msg = json.dumps(data)
        logger.info(f"Sending data: {msg[:100]}...")

        if self.addr_opponent:
            try:
                # Use new send API - automatically encrypts if keys available
                self.udp.send_data(msg, self.addr_opponent)
            except Exception as e:
                logger.error(f"Failed to send data: {e}")
        else:
            logger.warning("No opponent address set")

    def on_opponent_found(self, *args):
        pass

    def on_game_data_update(self, *args):
        pass

    def on_game_status_update(self, *args):
        pass

    def on_score_update(self, *args):
        pass

    def on_game_init(self, *args):
        pass

    def _handle_multicast_message(self, msg):
        """Process incoming multicast messages with updated key handling."""
        if not msg.get("name", self.me) == self.me and msg.get("type", "error") == self.sd_type:
            # Extract connection info
            server_ip = msg.get("addr")[0]
            server_port = msg.get("addr")[1]
            enemy_name = msg.get("name")

            # Get encryption keys (new format)
            enc_key = msg.get("enc_key") or msg.get("key")  # Fallback for old format
            sign_key = msg.get("sign_key", "")

            if not enc_key:
                logger.warning(f"No encryption key in message from {enemy_name}")
                return

            # Update opponent info
            server_addr = (server_ip, server_port)
            self.update_opponent_ip(addr=server_addr, enc_key=enc_key, sign_key=sign_key)

            # Send initial connection message
            init_msg = {
                "init": {
                    "ip": self.ip,
                    "port": self.port,
                    "enc_key": self.pub_key,
                    "sign_key": self.sign_key,
                    "name": self.me
                }
            }
            self.send_game_data(init_msg)

            # Stop searching
            self.publisher.stop()

            # Inform game
            logger.info(f"Found opponent: {enemy_name}")
            opponent_data = {"name": enemy_name}
            self.dispatch('on_opponent_found', opponent_data)

    def _handle_udp_data(self, data, addr):
        """Process incoming UDP data with improved error handling."""
        logger.info(f"Received data from {addr}: {data[:100]}...")

        try:
            # Data is already a string from the new UDP API
            if isinstance(data, bytes):
                data_dict = json.loads(data.decode("utf-8"))
            else:
                data_dict = json.loads(data)
        except Exception as e:
            logger.error(f"Failed to parse JSON data: {e}")
            return

        # Handle init message
        for key, value in data_dict.items():
            if key == "init":
                client_ip = value.get("ip", addr[0])
                client_port = value.get("port", addr[1])
                client_addr = (client_ip, client_port)

                # Get keys (support both old and new format)
                enc_key = value.get("enc_key") or value.get("key")
                sign_key = value.get("sign_key", "")

                if enc_key:
                    self.update_opponent_ip(addr=client_addr, enc_key=enc_key, sign_key=sign_key)

                self.dispatch("on_game_init", value)
                return

            # Dispatch other events
            event_name = self.event_map.get(key)
            if event_name:
                self.dispatch(event_name, {key: value})
            else:
                logger.warning(f"Unknown data key received: {key}")

    def cleanup(self):
        """Cleanup resources on shutdown."""
        self.stop_search_for_opponent()
        if self.udp:
            try:
                self.udp.stop()
            except Exception as e:
                logger.error(f"Error stopping UDP socket: {e}")


class PongPaddle(Widget):
    """Paddle class for "Pong" game"""
    score = NumericProperty(0)
    name = ObjectProperty("searching...")

    def bounce_ball(self, ball, acceleration=0.5):
        """Bounce and accelerate the ball if it collides the paddle, top or bottom
            :param ball: ball of game "Pong"
            :type ball: PongBall
            :param acceleration: acceleration rate
            :type acceleration: float
            :return: true if collided and accelerated, false if not collided
            :rtype: bool
        """
        if self.collide_widget(ball):
            vx, vy = ball.velocity
            if 0 < vx + acceleration < MAX_BALL_SPEED:
                vx += acceleration

            elif 0 > vx - acceleration > -MAX_BALL_SPEED:
                vx -= acceleration

            offset = (ball.center_y - self.center_y) / (self.height / 2)
            bounced = Vector(-1 * vx, vy)
            vel = bounced
            ball.velocity = vel.x, vel.y + offset
            return True
        return False


class PongBall(Widget):
    """Ball class for "Pong" game"""
    velocity_x = NumericProperty(0)
    velocity_y = NumericProperty(0)
    velocity = ReferenceListProperty(velocity_x, velocity_y)
    control_mode = ObjectProperty(None)
    end_game_text = ObjectProperty(None)

    def move(self):
        """Move the ball to next position in current direction"""
        self.pos = Vector(*self.velocity) + self.pos


class PongGame(Widget):
    ball = ObjectProperty(None)
    player1 = ObjectProperty(None)
    player2 = ObjectProperty(None)

    # Diese ersetzen die Attribute in __init__
    is_connected = BooleanProperty(False)
    game_owner = BooleanProperty(True)
    pause = BooleanProperty(False)

    # Dieses Property steuert den Text im "End Game"-Label
    game_message = StringProperty("")

    def __init__(self):
        """Process of starting of the game:
        """
        super().__init__()
        self.last_sent_pos = [0, 0]
        self.pl_name = "Dave_{}".format(random.randint(1000000, 10000000))
        self.enemy_name = None

        self.network = NetworkManager(self.pl_name)
        self.network.bind(
            on_opponent_found=self.on_opponent_found,
            on_game_data_update=self.on_game_data_update,
            on_game_status_update=self.on_game_status_update,
            on_score_update=self.on_score_update,
            on_game_init=self.on_game_init
        )
        self.network.start_search_for_opponent()

        # variables
        self.is_connected = False
        self.sym_init = False
        self.game_owner = True

        self.ball.end_game_text = ""
        self.pause = False
        self.win_size_pl1 = [800, 600]

        self.enemy = None
        self.me = None
        self.game_over = None

        self.all_controllers = ["mix", "mouse", "keyboard"]
        self.ball.control_mode = self.all_controllers[0]

        logger.info("Welcome {} - let's play pong".format(self.pl_name))

        # keyboard press event
        self.keyboard = Window.request_keyboard(self.keyboard_closed, self)
        # window close event:
        Window.bind(on_request_close=self._on_window_close)

    def _on_window_close(self, *args):
        """Proper cleanup on window close."""
        self.stop_thread(*args)
        self.network.cleanup()
        return False

    def init_game_connection(self):
        """Initialize the game after successful connection"""
        if self.game_owner:
            self.enemy = self.player2
            self.me = self.player1

            # equalise window size
            win_size = self.get_root_window().size

            msg = {"win_size": [win_size[0], win_size[1]]}
            self.network.send_game_data(msg)

        else:
            self.enemy = self.player1
            self.me = self.player2

            # set default speed and pos by start
            self.ball.pos = [729.0, 275.0]
            self.ball.velocity = [-6.5, 0]

        # set player names
        self.me.name = "You: {}".format(self.pl_name)
        self.enemy.name = "Enemy: {}".format(self.enemy_name)

        logger.debug(f"enemy defined - {self.enemy_name}")
        logger.debug("game owner: {}".format(self.game_owner))

        # key pressed event
        self.keyboard.bind(on_key_down=self.on_keyboard_down)
        # window resized event
        Window.bind(on_resize=self.on_resize_window)

        self.serve_ball()
        Clock.schedule_interval(self.update, 1.0 / 60.0)

    def serve_ball(self, vel=(6, 0)):
        """Throw the ball from middle"""
        self.ball.center = self.center
        self.ball.velocity = vel

    def update(self, *args):
        """Update game"""
        # print(*args)
        if self.pause:
            return

        self.ball.move()
        self._check_paddle_collisions()
        self._check_wall_collisions()
        self._check_scoring()

        if self.is_connected:
            self._send_paddle_update()

    def _send_paddle_update(self):
        """Sendet die Paddel-Position, aber nur, wenn sie sich geändert hat."""
        if self.me and self.me.pos != self.last_sent_pos:
            self.last_sent_pos = self.me.pos[:]  # Wichtig: Eine Kopie speichern
            msg = {"pad_pos": self.me.pos}
            self.network.send_game_data(msg)

    def _check_paddle_collisions(self):
        bounce_pl1 = self.player1.bounce_ball(self.ball)
        bounce_pl2 = self.player2.bounce_ball(self.ball)

        if bounce_pl1 or bounce_pl2:
            if self.game_owner:
                msg = {"ball_vel": self.ball.velocity, "ball_pos": self.ball.pos}
                self.network.send_game_data(msg)

    def _check_wall_collisions(self):
        if (self.ball.y < self.y) or (self.ball.top > self.top):
            self.ball.velocity_y *= -1

    def _check_scoring(self):
        if self.ball.x < self.x - 10:
            if self.game_owner:
                self.player2.score += 1
                msg = {"score_pl2": self.player2.score}
                self.network.send_game_data(msg)
            self.check_player_win(self.player2)
            self.serve_ball(vel=(BALL_START_SPEED, 0))
        if self.ball.right > self.width + 10:
            if self.game_owner:
                self.player1.score += 1
                msg = {"score_pl1": self.player1.score}
                self.network.send_game_data(msg)
            self.check_player_win(self.player1)
            self.serve_ball(vel=(-BALL_START_SPEED, 0))

    def on_score_update(self, instance, data):
        if data.get("score_pl1", False):
            self.player1.score = data.get("score_pl1", False)
            self.check_player_win(self.player1)
            return
        if data.get("score_pl2", False):
            self.player2.score = data.get("score_pl2", False)
            self.check_player_win(self.player2)

    def on_game_data_update(self, instance, data):
        if data.get("pad_pos", False):
            self.enemy.pos = data.get("pad_pos", False)
            return
        if data.get("ball_vel", False):
            self.ball.velocity = data.get("ball_vel", False)
            return
        if data.get("ball_pos", False):
            value = data.get("ball_pos", False)
            if value != self.ball.pos:
                self.ball.pos = data.get("ball_pos", False)

    def on_game_status_update(self, instance, data):
        #if key == "win_size":
        #    self.win_size_pl1 = value
        #    self.get_root_window().size = value
        #    return
        if data.get("reset_scores", False):
            self.player1.score = 0
            self.player2.score = 0
            self.pause = False
            return
        if data.get("game_close", False):
            self.player1.score = 0
            self.player2.score = 0
            self.pause = True
            self.is_connected = False
            self.ball.end_game_text = "enemy left"
            self.network.start_search_for_opponent()
            return
        self.pause = data.get("pause", False)

    def on_game_init(self, instance, data):
        if not self.is_connected:
            self.sym_init = True
            # init name
            client_name = data.get("name", "anonymous")
            self.enemy_name = client_name
            # initialize game
            self.init_game_connection()
            self.is_connected = True
            self.network.stop_search_for_opponent()

    def on_opponent_found(self, instance, msg):
        """Listen to Multicast publisher
            :param msg: consists of ip, port, name, public key, type of connection
            :type msg: dict
        """
        self.enemy_name = msg.get("name")
        logger.debug(f"enemy found: {self.enemy_name} - instance: {instance}")

        # initialize game
        self.game_owner = False
        self.is_connected = True
        self.init_game_connection()
        self.network.stop_search_for_opponent()

    def check_player_win(self, player):
        """Check if player has certain points. If yes stop game.
            :param player: player
            :type player: PongBall
        """
        if player.score >= POINTS_TO_WIN:
            self.game_over = True
            self.pause = True
            if player == self.me:
                self.ball.end_game_text = "You won!!!"
            else:
                self.ball.end_game_text = "You lost"

    def on_touch_move(self, touch):
        """Move paddle if mouse moved
            :param touch: mouse pos
            :type touch: points
        """
        if self.ball.control_mode in ["mouse", "mix"]:
            if self.me == self.player1:
                if touch.x < (self.width * PADDLE_CONTROL_AREA_FACTOR):
                    self.move_paddle(self.me, touch.y)
            elif self.me == self.player2:
                if touch.x > self.width - (self.width * PADDLE_CONTROL_AREA_FACTOR):
                    self.move_paddle(self.me, touch.y)

    def on_keyboard_down(self, keyboard, keycode, text, modifiers):
        """Move paddle if keyboard buttons pressed
            :param keycode: button name
            :type keyboard: list
            :return: True
            :rtype: bool
        """
        move_speed = 80
        if self.ball.control_mode in ["keyboard", "mix"]:
            if keycode[1] in ['w', "up"]:
                self.move_paddle(paddle=self.me, goal_pos=self.me.center_y + PADDLE_MOVE_SPEED)
            elif keycode[1] in ['s', "down"]:
                self.move_paddle(paddle=self.me, goal_pos=self.me.center_y - PADDLE_MOVE_SPEED)

        if keycode[1] == "p":
            self.switch_pause_play()
            if (self.player1.score or self.player2.score) >= 10:
                self.player1.score = 0
                self.player2.score = 0
        return True

    def keyboard_closed(self):
        """Unbind keyboard"""
        self.keyboard.unbind(on_key_down=self.on_keyboard_down)
        self.keyboard = None

    def move_paddle(self, paddle, goal_pos):
        """Moves paddle according to the size of window in order paddle to not exit from window
            :param paddle: paddle
            :type paddle:PongPaddle
            :param goal_pos: goal position to move to
            :type goal_pos: float
        """
        # possible maximum upper position of paddle
        upper_pos = goal_pos + paddle.height / 2
        # possible maximum lower position of paddle
        lower_pos = goal_pos - paddle.height / 2

        # firstly set touch position to center of paddle
        paddle.center_y = goal_pos
        # avoid paddle to exit window borders
        if upper_pos >= self.height:
            paddle.center_y = self.height - paddle.height / 2
        elif lower_pos <= 0:
            paddle.center_y = 0 + paddle.height / 2

    def switch_pause_play(self):
        """Switch pause or play"""
        if not self.pause:
            self.set_pause(True)
        else:
            self.set_pause(False)

    def on_pause(self, instance, value):
        if value:
            # Das Spiel ist pausiert
            if not self.game_over:  # Prüfen, ob das Spiel nicht schon vorbei ist
                self.game_message = "PAUSE"
        else:
            # Das Spiel läuft weiter
            if not self.game_over:
                self.game_message = ""

    def on_press_pause_play(self):
        """Signal on press button "Pause_Play". Switch pause. Reset score if one of players reached certain point"""
        self.pause = not self.pause

        msg = {"pause": self.pause}
        if self.player1.score >= 10 or self.player2.score >= 10:
            self.player1.score = 0
            self.player2.score = 0
            msg = msg.update({"reset_scores": True})

        self.network.send_game_data(msg)

    def on_press_control_mode(self):
        """Signal on press button "Control mode". Changes control mode"""
        current_mode_index = self.all_controllers.index(self.ball.control_mode)
        self.ball.control_mode = self.all_controllers[current_mode_index - 1]

    def on_resize_window(self, win, w, h):
        """Signal on resize window size
            :param w: width of window after resizing
            :type w: float
            :param h: height of window after resizing
            :type h: float
        """
        if self.game_owner:
            msg = {"win_size": [w, h]}
            self.network.send_game_data(msg)
        else:
            self.get_root_window().size = self.win_size_pl1

    def stop_thread(self, *args):
        """Stop all threads if game is closed"""
        logger.debug("Stopping game threads")

        # Notify opponent
        if self.is_connected and self.network.addr_opponent:
            try:
                msg = {"game_close": True}
                self.network.send_game_data(msg)
            except Exception as e:
                logger.error(f"Failed to send close message: {e}")

        # Cleanup network
        self.network.cleanup()


class PongApp(App):
    def __init__(self, **kwargs):
        """Pong game. Build with Kivy"""
        super().__init__(**kwargs)

    def build(self):
        game = PongGame()
        return game


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    PongApp().run()
