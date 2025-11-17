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
PADDLE_CONTROL_AREA_FACTOR = 1 / 3


class NetworkManager(EventDispatcher):
    """Manages network communication for the Pong game with updated UDP socket API."""

    __events__ = (
        'on_opponent_found',
        'on_game_data_update',
        'on_game_status_update',
        'on_score_update',
        'on_game_init',
    )

    def __init__(self, player_name):
        super().__init__()
        self.me = player_name

        # Get IP address using new API
        ipv4_list, ipv6_list = helper_ip.get_ip_addresses()
        self.ip = ipv4_list[0] if ipv4_list else "127.0.0.1"
        self.port = random.randint(2000, 20000)

        self.sd_type = "pong"
        self.listener = None

        # Initialize UDP socket
        self.udp = helper_udp.UDPSocketClass(recv_port=self.port)

        # Keys
        self.pub_key = self.udp._encryption.enc_public_key
        self.sign_key = self.udp._encryption.sign_public_key
        self.addr_opponent = None

        # Multicast message
        self.mc_msg = {
            "addr": (self.ip, self.port),
            "name": player_name,
            "enc_key": self.pub_key,
            "sign_key": self.sign_key,
            "type": self.sd_type,
        }
        self.publisher = helper_multicast.VaultMultiPublisher()

        # Connect UDP receiving signal
        self.udp.udp_recv_data.connect(self._handle_udp_data)

        # Mapping of received keys → events
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
            "game_over": "on_game_status_update",
            "sync_ready": "on_sync_complete",
            "sync_ack": "on_sync_complete",
        }

    # -----------------------
    # Opponent handling
    # -----------------------

    def update_opponent_ip(self, addr, enc_key=None, sign_key=None):
        """Update opponent address and encryption keys."""
        self.addr_opponent = addr

        # IMPORTANT: Set keys BEFORE adding peer!
        if enc_key and sign_key:
            self.udp._encryption.update_peer_keys(addr, enc_key, sign_key)
            logger.info(f"Updated encryption keys for {addr}")
        else:
            logger.warning(f"update_opponent_ip called without keys for {addr}")

        # Now add peer - encryption will be available
        if not self.udp.has_peer(addr):
            self.udp.add_peer(addr)
            logger.info(f"Added peer {addr} - encryption ready")
        else:
            logger.debug(f"Peer {addr} already exists, keys updated")

    # -----------------------
    # Multicast discovery
    # -----------------------

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
        try:
            if self.listener:
                self.listener.recv_signal.disconnect(self._handle_multicast_message)
                self.listener.stop()
            self.publisher.stop()
            logger.info("Stopped opponent search")
        except Exception as e:
            logger.warning(f"Error stopping search: {e}")

    # -----------------------
    # Sending data
    # -----------------------

    def send_game_data(self, data):
        """Send game data via UDP."""
        msg = json.dumps(data)
        logger.info(f"Sending data: {msg[:100]}...")

        if not self.addr_opponent:
            logger.warning("No opponent address set")
            return

        try:
            self.udp.send_data(msg, self.addr_opponent)
        except Exception as e:
            logger.error(f"Failed to send data: {e}")

    # -----------------------
    # Event definitions (no handlers!)
    # -----------------------

    def on_opponent_found(self, msg):
        pass

    def on_game_data_update(self, msg):
        pass

    def on_game_status_update(self, msg):
        pass

    def on_score_update(self, msg):
        pass

    def on_game_init(self, msg):
        pass

    def on_sync_complete(self, msg):
        pass

    # -----------------------
    # Multicast message handler
    # -----------------------

    def _handle_multicast_message(self, msg):
        """Process incoming multicast announcement."""
        if msg.get("name") == self.me:
            return
        if msg.get("type") != self.sd_type:
            return

        # Extract opponent data
        server_ip, server_port = msg.get("addr")
        enemy_name = msg.get("name")

        enc_key = msg.get("enc_key") or msg.get("key")
        sign_key = msg.get("sign_key", "")

        if not enc_key:
            logger.warning(f"No encryption key in message from {enemy_name}")
            return

        server_addr = (server_ip, server_port)
        self.update_opponent_ip(server_addr, enc_key, sign_key)

        # Send init message
        init_msg = {
            "init": {
                "ip": self.ip,
                "port": self.port,
                "enc_key": self.pub_key,
                "sign_key": self.sign_key,
                "name": self.me,
            }
        }
        self.send_game_data(init_msg)

        self.publisher.stop()

        logger.info(f"Found opponent: {enemy_name}")
        enemy = {"name": enemy_name}
        self.dispatch("on_opponent_found", enemy)

    # -----------------------
    # UDP message handler
    # -----------------------

    def _handle_udp_data(self, data, addr):
        """Process incoming UDP data."""
        logger.info(f"Received data from {addr}: {data[:100]}...")

        try:
            if isinstance(data, bytes):
                data_dict = json.loads(data.decode("utf-8"))
            else:
                data_dict = json.loads(data)
        except Exception as e:
            logger.error(f"Failed to parse JSON data: {e}")
            return

        for key, value in data_dict.items():

            if key == "init":
                client_addr = (value.get("ip", addr[0]),
                               value.get("port", addr[1]))

                enc_key = value.get("enc_key") or value.get("key")
                sign_key = value.get("sign_key", "")

                if enc_key:
                    self.update_opponent_ip(client_addr, enc_key, sign_key)

                self.dispatch("on_game_init", value)
                return

            event_name = self.event_map.get(key)
            if event_name:
                self.dispatch(event_name, {key: value})
            else:
                logger.warning(f"Unknown data key received: {key}")

    # -----------------------
    # Cleanup
    # -----------------------

    def cleanup(self):
        """Cleanup resources on shutdown."""
        self.stop_search_for_opponent()

        if self.udp:
            try:
                self.udp.stop()
            except Exception as e:
                logger.error(f"Error stopping UDP socket: {e}")


class PongPaddle(Widget):
    """Paddle class for Pong game."""
    score = NumericProperty(0)
    name = ObjectProperty("searching...")

    def bounce_ball(self, ball, acceleration=0.5):
        """Bounce and accelerate the ball if it collides the paddle."""
        if self.collide_widget(ball):
            vx, vy = ball.velocity
            if 0 < vx + acceleration < MAX_BALL_SPEED:
                vx += acceleration
            elif 0 > vx - acceleration > -MAX_BALL_SPEED:
                vx -= acceleration

            offset = (ball.center_y - self.center_y) / (self.height / 2)
            bounced = Vector(-1 * vx, vy)
            ball.velocity = bounced.x, bounced.y + offset
            return True
        return False


class PongBall(Widget):
    """Ball class for Pong game."""
    velocity_x = NumericProperty(0)
    velocity_y = NumericProperty(0)
    velocity = ReferenceListProperty(velocity_x, velocity_y)
    control_mode = ObjectProperty(None)
    end_game_text = ObjectProperty(None)

    def move(self):
        """Move the ball to next position in current direction."""
        self.pos = Vector(*self.velocity) + self.pos


class PongGame(Widget):
    ball = ObjectProperty(None)
    player1 = ObjectProperty(None)
    player2 = ObjectProperty(None)

    is_connected = BooleanProperty(False)
    game_owner = BooleanProperty(True)
    pause = BooleanProperty(False)
    game_message = StringProperty("")
    is_synchronized = BooleanProperty(False)
    sync_state = StringProperty("waiting")  # waiting, ready, synchronized

    def __init__(self):
        """Initialize the Pong game."""
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
            on_game_init=self.on_game_init,
            on_sync_complete=self.on_sync_complete
        )
        self.network.start_search_for_opponent()

        # Game state variables
        self.is_connected = False
        self.sym_init = False
        self.game_owner = True
        self.game_over = False
        self.is_synchronized = False
        self.sync_state = "waiting"

        self.ball.end_game_text = "Searching for opponent..."
        self.pause = True  # Start paused until synchronized
        self.win_size_pl1 = [800, 600]

        self.enemy = None
        self.me = None

        self.all_controllers = ["mix", "mouse", "keyboard"]
        self.ball.control_mode = self.all_controllers[0]

        logger.info("Welcome {} - let's play pong".format(self.pl_name))

        # Keyboard setup
        self.keyboard = Window.request_keyboard(self.keyboard_closed, self)
        Window.bind(on_request_close=self._on_window_close)

    def _on_window_close(self, *args):
        """Proper cleanup on window close."""
        self.stop_thread(*args)
        self.network.cleanup()
        return False

    def _determine_game_owner(self, my_name, enemy_name):
        """Determine game owner consistently on both sides."""
        # Lexicographic comparison ensures same result on both clients
        return my_name < enemy_name

    def init_game_connection(self):
        """Initialize the game after successful connection."""
        if self.game_owner:
            self.enemy = self.player2
            self.me = self.player1

            # Synchronize window size
            win_size = self.get_root_window().size
            msg = {"win_size": [win_size[0], win_size[1]]}
            self.network.send_game_data(msg)

        else:
            self.enemy = self.player1
            self.me = self.player2

            # Set default ball position and velocity
            self.ball.pos = [729.0, 275.0]
            self.ball.velocity = [-6.5, 0]

        # Set player names
        self.me.name = "You: {}".format(self.pl_name)
        self.enemy.name = "Enemy: {}".format(self.enemy_name)

        logger.debug(f"Enemy: {self.enemy_name}, Game owner: {self.game_owner}")

        # Bind keyboard and window events
        self.keyboard.bind(on_key_down=self.on_keyboard_down)
        Window.bind(on_resize=self.on_resize_window)

        self.serve_ball()
        Clock.schedule_interval(self.update, 1.0 / 60.0)

        # Start synchronization process
        self.start_synchronization()

    def serve_ball(self, vel=(6, 0)):
        """Serve the ball from center."""
        self.ball.center = self.center
        self.ball.velocity = vel

    def start_synchronization(self):
        """Start the synchronization process."""
        logger.info("Starting synchronization process")
        self.sync_state = "ready"
        self.ball.end_game_text = "Synchronizing..."
        self.pause = True

        # Send sync_ready message
        msg = {"sync_ready": True}
        self.network.send_game_data(msg)
        logger.debug("Sent sync_ready signal")

    def complete_synchronization(self):
        """Complete synchronization and start game."""
        if not self.is_synchronized:
            self.is_synchronized = True
            self.sync_state = "synchronized"
            self.pause = False
            self.ball.end_game_text = ""
            logger.info("Synchronization complete - Game started!")

            # Show brief "READY!" message
            self.ball.end_game_text = "READY!"
            Clock.schedule_once(lambda dt: setattr(self.ball, 'end_game_text', ''), 1.5)

    def update(self, dt):
        """Update game state (called 60 times per second)."""
        if self.pause or not self.is_synchronized:
            return

        self.ball.move()
        self._check_paddle_collisions()
        self._check_wall_collisions()
        self._check_scoring()

        if self.is_connected:
            self._send_paddle_update()

    def _send_paddle_update(self):
        """Send paddle position only if it changed."""
        if self.me and self.me.pos != self.last_sent_pos:
            self.last_sent_pos = self.me.pos[:]
            msg = {"pad_pos": self.me.pos}
            self.network.send_game_data(msg)

    def _check_paddle_collisions(self):
        """Check and handle paddle collisions."""
        bounce_pl1 = self.player1.bounce_ball(self.ball)
        bounce_pl2 = self.player2.bounce_ball(self.ball)

        if bounce_pl1 or bounce_pl2:
            if self.game_owner:
                msg = {"ball_vel": self.ball.velocity, "ball_pos": self.ball.pos}
                self.network.send_game_data(msg)

    def _check_wall_collisions(self):
        """Check and handle wall collisions."""
        if (self.ball.y < self.y) or (self.ball.top > self.top):
            self.ball.velocity_y *= -1

    def _check_scoring(self):
        """Check if a player scored."""
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

    # -----------------------
    # Event handlers
    # -----------------------

    def on_sync_complete(self, instance, data):
        """Handle synchronization messages."""
        logger.debug(f"Sync message received: {data}")

        if "sync_ready" in data and data["sync_ready"]:
            # Opponent is ready
            logger.info("Opponent is ready for sync")

            if self.sync_state == "waiting":
                # We haven't sent our ready signal yet
                self.sync_state = "ready"
                msg = {"sync_ready": True}
                self.network.send_game_data(msg)
                logger.debug("Sent sync_ready in response")

            if self.sync_state == "ready":
                # Both are ready, send acknowledgment
                logger.info("Both players ready - sending ack")
                msg = {"sync_ack": True}
                self.network.send_game_data(msg)
                self.complete_synchronization()

        elif "sync_ack" in data and data["sync_ack"]:
            # Received acknowledgment
            logger.info("Received sync acknowledgment")
            if self.sync_state == "ready":
                self.complete_synchronization()

    def on_score_update(self, instance, data):
        """Handle score updates from opponent."""
        if "score_pl1" in data:
            self.player1.score = data["score_pl1"]
            self.check_player_win(self.player1)
        elif "score_pl2" in data:
            self.player2.score = data["score_pl2"]
            self.check_player_win(self.player2)

    def on_game_data_update(self, instance, data):
        """Handle game data updates (paddle, ball)."""
        if "pad_pos" in data:
            self.enemy.pos = data["pad_pos"]
        elif "ball_vel" in data:
            self.ball.velocity = data["ball_vel"]
        elif "ball_pos" in data:
            if data["ball_pos"] != self.ball.pos:
                self.ball.pos = data["ball_pos"]

    def on_game_status_update(self, instance, data):
        """Handle game status updates (pause, reset, close, game_over)."""
        if "reset_scores" in data:
            self.player1.score = 0
            self.player2.score = 0
            self.pause = False
            self.game_over = False
            self.ball.end_game_text = ""
            self.is_synchronized = True  # Keep synchronized on reset
            return

        if "game_close" in data:
            self.player1.score = 0
            self.player2.score = 0
            self.pause = True
            self.is_connected = False
            self.game_over = False
            self.is_synchronized = False
            self.sync_state = "waiting"
            self.ball.end_game_text = "Enemy left - Searching..."
            self.network.start_search_for_opponent()
            return

        if "game_over" in data:
            self.game_over = True
            self.pause = True
            winner = data.get("winner")
            if winner == "player1" and self.me == self.player1:
                self.ball.end_game_text = "You won!!!"
            elif winner == "player2" and self.me == self.player2:
                self.ball.end_game_text = "You won!!!"
            else:
                self.ball.end_game_text = "You lost"
            return

        if "pause" in data:
            self.pause = data["pause"]

    def on_game_init(self, instance, data):
        """Handle game init message (we are SERVER)."""
        if not self.is_connected:
            self.sym_init = True
            client_name = data.get("name", "anonymous")
            self.enemy_name = client_name

            # Determine owner consistently
            self.game_owner = self._determine_game_owner(self.pl_name, self.enemy_name)

            self.init_game_connection()
            self.is_connected = True
            self.network.stop_search_for_opponent()

    def on_opponent_found(self, instance, msg):
        """Handle opponent found via multicast (we are CLIENT)."""
        self.enemy_name = msg.get("name")
        logger.debug(f"Opponent found: {self.enemy_name}")

        # Determine owner consistently
        self.game_owner = self._determine_game_owner(self.pl_name, self.enemy_name)

        self.is_connected = True
        self.init_game_connection()
        self.network.stop_search_for_opponent()

    def check_player_win(self, player):
        """Check if a player has won."""
        if player.score >= POINTS_TO_WIN:
            self.game_over = True
            self.pause = True

            if player == self.me:
                self.ball.end_game_text = "You won!!!"
                # Notify opponent
                if self.is_connected and self.game_owner:
                    winner_id = "player1" if player == self.player1 else "player2"
                    msg = {"game_over": True, "winner": winner_id}
                    self.network.send_game_data(msg)
            else:
                self.ball.end_game_text = "You lost"

    # -----------------------
    # Input handlers
    # -----------------------

    def on_touch_move(self, touch):
        """Handle mouse movement for paddle control."""
        if self.ball.control_mode in ["mouse", "mix"]:
            if self.me == self.player1:
                if touch.x < (self.width * PADDLE_CONTROL_AREA_FACTOR):
                    self.move_paddle(self.me, touch.y)
            elif self.me == self.player2:
                if touch.x > self.width - (self.width * PADDLE_CONTROL_AREA_FACTOR):
                    self.move_paddle(self.me, touch.y)

    def on_keyboard_down(self, keyboard, keycode, text, modifiers):
        """Handle keyboard input for paddle control."""
        # Allow paddle control even during sync (for testing position)
        if self.ball.control_mode in ["keyboard", "mix"]:
            if keycode[1] in ['w', "up"]:
                self.move_paddle(self.me, self.me.center_y + PADDLE_MOVE_SPEED)
            elif keycode[1] in ['s', "down"]:
                self.move_paddle(self.me, self.me.center_y - PADDLE_MOVE_SPEED)

        # Pause only works after synchronization
        if keycode[1] == "p" and self.is_synchronized:
            self.switch_pause_play()

        # Reset after game over
        if keycode[1] == "r" and self.game_over:
            self.player1.score = 0
            self.player2.score = 0
            self.game_over = False
            self.pause = False
            self.ball.end_game_text = ""
            self.serve_ball()
            if self.is_connected:
                msg = {"reset_scores": True}
                self.network.send_game_data(msg)

        return True

    def keyboard_closed(self):
        """Unbind keyboard."""
        if self.keyboard:
            self.keyboard.unbind(on_key_down=self.on_keyboard_down)
            self.keyboard = None

    def move_paddle(self, paddle, goal_pos):
        """Move paddle within window boundaries."""
        upper_pos = goal_pos + paddle.height / 2
        lower_pos = goal_pos - paddle.height / 2

        paddle.center_y = goal_pos

        if upper_pos >= self.height:
            paddle.center_y = self.height - paddle.height / 2
        elif lower_pos <= 0:
            paddle.center_y = 0 + paddle.height / 2

    def switch_pause_play(self):
        """Toggle pause state and notify opponent (only when synchronized)."""
        if not self.is_synchronized:
            logger.warning("Cannot pause - game not synchronized yet")
            return

        self.pause = not self.pause

        if self.is_connected:
            msg = {"pause": self.pause}
            self.network.send_game_data(msg)

    def on_pause(self, instance, value):
        """React to pause property changes."""
        if value and not self.game_over:
            self.game_message = "PAUSE"
        else:
            self.game_message = ""

    def on_press_pause_play(self):
        """Handle pause/play button press."""
        if not self.is_synchronized and not self.game_over:
            logger.warning("Cannot pause - game not synchronized yet")
            return

        self.pause = not self.pause

        msg = {"pause": self.pause}

        # Reset if game is over
        if self.player1.score >= POINTS_TO_WIN or self.player2.score >= POINTS_TO_WIN:
            self.player1.score = 0
            self.player2.score = 0
            self.game_over = False
            self.ball.end_game_text = ""
            msg["reset_scores"] = True

        if self.is_connected:
            self.network.send_game_data(msg)

    def on_press_control_mode(self):
        """Cycle through control modes."""
        current_index = self.all_controllers.index(self.ball.control_mode)
        self.ball.control_mode = self.all_controllers[current_index - 1]

    def on_resize_window(self, win, w, h):
        """Handle window resize."""
        if self.game_owner:
            msg = {"win_size": [w, h]}
            self.network.send_game_data(msg)
        else:
            self.get_root_window().size = self.win_size_pl1

    def stop_thread(self, *args):
        """Stop all threads when game closes."""
        logger.debug("Stopping game threads")

        if self.is_connected and self.network.addr_opponent:
            try:
                msg = {"game_close": True}
                self.network.send_game_data(msg)
            except Exception as e:
                logger.error(f"Failed to send close message: {e}")

        self.network.cleanup()


class PongApp(App):
    def __init__(self, **kwargs):
        """Pong game built with Kivy."""
        super().__init__(**kwargs)

    def build(self):
        game = PongGame()
        return game


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    PongApp().run()
