from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import (NumericProperty, ReferenceListProperty, ObjectProperty)
from kivy.uix.widget import Widget
from kivy.vector import Vector

import json
import logging
import random
import include.multicast.vault_multicast as helper_multicast
import include.udp.vault_udp.vault_ip as helper_ip
import include.udp.vault_udp.vault_udp_socket as helper_udp


logger = logging.getLogger(__name__)


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
            if 0 < vx + acceleration < 38:
                vx += acceleration

            elif 0 > vx - acceleration > -38:
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

    def __init__(self):
        """Process of starting of the game:
             1. Each player starts multicast publisher and listener
               - publisher publishes his own data: ip, port, name, public key, type of connection
             2. One of the players automatically receives published data of another
               - creates key based on own private key and public key of publisher
               - starts udp connection to the publisher with his ip and port
               - sends init message to the publisher: own ip, port, pub_key and name
               - initialises the game
               - closes publisher and listener
             3. Another player receives init message sent through UDP
               - creates key based on own private key and received public key
               - starts udp connection
               - initialises the game
               - closes publisher and listener
        """
        super().__init__()
        self.pl_name = "Dave_{}".format(random.randint(1000000, 10000000))
        self.sd_type = "pong"
        self.enemy_name = None

        # ip and port settings
        self.ip = helper_ip.get_ips()[0][0]
        self.port = random.randint(2000, 20000)

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

        self.listener = helper_multicast.VaultMultiListener()
        self.listener.start()
        self.listener.recv_signal.connect(self.on_recv_listener)

        # initialize udp
        self.udp = helper_udp.UDPSocketClass(recv_port=self.port)
        self.pub_key = self.udp.pkse.public_key

        # multicast publisher and listener
        mc_msg = {"addr": (self.ip, self.port), "name": self.pl_name, "key": self.pub_key, "type": self.sd_type}
        self.publisher = helper_multicast.VaultMultiPublisher(message=json.dumps(mc_msg))

        logger.info("Welcome {} - let's play pong".format(self.pl_name))
        logger.debug("multicast started with msg: {}".format(mc_msg))

        # udp receive data event
        self.udp.udp_recv_data.connect(self.on_recv_data)
        # keyboard press event
        self.keyboard = Window.request_keyboard(self.keyboard_closed, self)
        # window close event:
        Window.bind(on_request_close=self.stop_thread)

    def init_game_connection(self):
        """Initialize the game after successful connection"""
        if self.game_owner:
            self.enemy = self.player2
            self.me = self.player1

            # equalise window size
            win_size = self.get_root_window().size

            msg = json.dumps({"win_size": [win_size[0], win_size[1]]})
            self.udp.send_data(msg)

        else:
            self.enemy = self.player1
            self.me = self.player2

            # set default speed and pos by start
            self.ball.pos = [729.0, 275.0]
            self.ball.velocity = [-6.5, 0]

        # set player names
        self.me.name = "You: {}".format(self.pl_name)
        self.enemy.name = "Enemy: {}".format(self.enemy_name)

        logger.info("enemy defined")
        logger.info("game owner: {}".format(self.game_owner))

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
        if not self.pause:
            self.ball.move()

        # bounce off paddles
        bounce_pl1 = self.player1.bounce_ball(self.ball)
        bounce_pl2 = self.player2.bounce_ball(self.ball)

        if bounce_pl1 or bounce_pl2:
            if self.game_owner:
                msg = {"ball_vel": self.ball.velocity, "ball_pos": self.ball.pos}
                self.udp.send_data(json.dumps(msg))

        # bounce ball off bottom or top
        if (self.ball.y < self.y) or (self.ball.top > self.top):
            self.ball.velocity_y *= -1

        # went off to a side to score point?
        if self.ball.x < self.x - 10:
            if self.game_owner:
                self.player2.score += 1
                msg = {"score_pl2": self.player2.score}
                self.udp.send_data(json.dumps(msg))
            self.check_player_win(self.player2)
            self.serve_ball(vel=(6, 0))
        if self.ball.right > self.width + 10:
            if self.game_owner:
                self.player1.score += 1
                msg = {"score_pl1": self.player1.score}
                self.udp.send_data(json.dumps(msg))
            self.check_player_win(self.player1)
            self.serve_ball(vel=(-6, 0))

    def on_recv_data(self, data, addr):
        """Receive data sent through UDP
            :param data: received data
            :type data: str
            :param addr: IP and Port of sender
            :type addr: list
        """
        # exception handling for json data missing
        try:
            data_dict = json.loads(data)
        except Exception as e:
            logger.warning("Warning: {}".format(e))
            data_dict = {}

        # exception handling for not iterable missing
        logger.debug("data recv {} from {}".format(data, addr))
        for key, value in data_dict.items():
            if key == "pad_pos":
                self.enemy.pos = value
            if key == "pause":
                self.set_pause(value)
            if key == "ball_vel":
                self.ball.velocity = value
            if key == "ball_pos" and not value == self.ball.pos:
                self.ball.pos = value
            if key == "win_size":
                self.win_size_pl1 = value
                self.get_root_window().size = value
            if key == "reset_scores":
                self.player1.score = 0
                self.player2.score = 0
            if key == "score_pl1":
                self.player1.score = value
                self.check_player_win(self.player1)
            if key == "score_pl2":
                self.player2.score = value
                self.check_player_win(self.player2)
            if key == "game_close":
                self.player1.score = 0
                self.player2.score = 0
                self.pause = True
                self.ball.end_game_text = "enemy left"
            if key == "init" and not self.is_connected:
                self.sym_init = True

                # received message multicast listener
                client_ip = value.get("ip", addr[0])
                client_port = value.get("port", addr[1])
                client_key = value.get("key", "")
                client_name = value.get("name", "")
                logger.debug("Enemy {} connected from [{}]:{}".format(client_name, client_ip, client_port))
                self.enemy_name = client_name

                # initialize udp and encryption
                self.udp.pkse.update_key(addr=(client_ip, client_port), key=client_key)
                self.udp.update_addr(addr=(client_ip, client_port))

                # initialize game
                self.init_game_connection()
                self.is_connected = True
                self.publisher.stop()
                self.listener.recv_signal.disconnect(self.on_recv_listener)
                self.listener.stop()

    def on_recv_listener(self, msg):
        """Listen to Multicast publisher
            :param msg: consists of ip, port, name, public key, type of connection
            :type msg: dict
        """
        if (not self.is_connected and not msg.get("name", self.pl_name) == self.pl_name and
                msg.get("type", "error") == self.sd_type):
            # received message from multicast
            server_ip = msg.get("addr")[0]
            server_port = msg.get("addr")[1]
            self.enemy_name = msg.get("name")

            # encryption
            server_key = msg.get("key")

            # udp
            msg = {"init": {"ip": self.ip, "port": self.port, "key": self.pub_key, "name": self.pl_name}}
            self.udp.update_addr(addr=(server_ip, server_port))
            self.udp.pkse.update_key(addr=(server_ip, server_port), key=server_key)
            self.udp.send_data(json.dumps(msg))

            # self.udp.sym_encryption.update_key(addr=(server_ip, server_port), key=self.key)
            logger.info("found server ip: {}; port: {}; multicast_msg: {}".format(server_ip, server_port, msg))

            # initialize game
            self.game_owner = False
            self.is_connected = True
            self.init_game_connection()
            self.listener.recv_signal.disconnect(self.on_recv_listener)
            self.listener.stop()
            self.publisher.stop()

    def check_player_win(self, player):
        """Check if player has certain points. If yes stop game.
            :param player: player
            :type player: PongBall
        """
        if player.score >= 10:
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
                if touch.x < self.width / 3:
                    self.move_paddle(self.me, touch.y)
            elif self.me == self.player2:
                if touch.x > self.width - self.width / 3:
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
                self.move_paddle(paddle=self.me, goal_pos=self.me.center_y + move_speed)
            elif keycode[1] in ['s', "down"]:
                self.move_paddle(paddle=self.me, goal_pos=self.me.center_y - move_speed)

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

        if paddle == self.me:
            msg = json.dumps({"pad_pos": self.me.pos})
            self.udp.send_data(msg)

    def switch_pause_play(self):
        """Switch pause or play"""
        if not self.pause:
            self.set_pause(True)
        else:
            self.set_pause(False)

    def set_pause(self, pause=False):
        """Set pause or play
            :param pause: if true-pause, if false-play
        """
        if pause:
            self.pause = True
            self.ball.end_game_text = "PAUSE"
        else:
            self.pause = False
            self.ball.end_game_text = ""

    def on_press_pause_play(self):
        """Signal on press button "Pause_Play". Switch pause. Reset score if one of players reached certain point"""
        self.switch_pause_play()

        msg = {"pause": self.pause}
        if self.player1.score >= 10 or self.player2.score >= 10:
            self.player1.score = 0
            self.player2.score = 0
            msg = msg | {"reset_scores": True}

        self.udp.send_data(json.dumps(msg))

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
            msg = json.dumps({"win_size": [w, h]})
            self.udp.send_data(msg)
        else:
            self.get_root_window().size = self.win_size_pl1

    def stop_thread(self, *args):
        """Stop all threads if game is closed"""
        logger.info("try to stop")
        msg = json.dumps({"game_close": True})
        self.udp.send_data(msg)

        self.listener.recv_signal.disconnect(self.on_recv_listener)
        self.listener.stop()
        self.publisher.stop()
        self.udp.udp_recv_data.disconnect(self.on_recv_data)

        self.udp.stop()


class PongApp(App):
    def __init__(self, **kwargs):
        """Pong game. Build with Kivy"""
        super().__init__(**kwargs)

    def build(self):
        game = PongGame()
        return game


if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)
    PongApp().run()
