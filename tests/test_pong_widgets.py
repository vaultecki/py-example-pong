import pytest

import main


class TestPaddleBounce:
    def _paddle_and_ball(self):
        paddle = main.PongPaddle()
        paddle.pos = (0, 0)
        paddle.size = (25, 200)

        ball = main.PongBall()
        ball.size = (50, 50)
        return paddle, ball

    def test_no_bounce_without_collision(self):
        paddle, ball = self._paddle_and_ball()
        ball.pos = (1000, 1000)
        ball.velocity = (5, 0)

        assert paddle.bounce_ball(ball) is False
        assert ball.velocity == [5, 0]

    def test_bounce_reverses_and_accelerates_positive_velocity(self):
        paddle, ball = self._paddle_and_ball()
        ball.pos = (0, 0)
        ball.velocity = (5, 2)

        collided = paddle.bounce_ball(ball)

        offset = (ball.center_y - paddle.center_y) / (paddle.height / 2)
        assert collided is True
        assert ball.velocity == pytest.approx([-5.5, 2 + offset])

    def test_bounce_reverses_and_accelerates_negative_velocity(self):
        paddle, ball = self._paddle_and_ball()
        ball.pos = (0, 0)
        ball.velocity = (-5, 2)

        collided = paddle.bounce_ball(ball)

        offset = (ball.center_y - paddle.center_y) / (paddle.height / 2)
        assert collided is True
        assert ball.velocity == pytest.approx([5.5, 2 + offset])

    def test_bounce_does_not_exceed_max_ball_speed(self):
        paddle, ball = self._paddle_and_ball()
        ball.pos = (0, 0)
        ball.velocity = (main.MAX_BALL_SPEED, 0)

        paddle.bounce_ball(ball)

        assert abs(ball.velocity[0]) <= main.MAX_BALL_SPEED


class TestBallMove:
    def test_move_advances_position_by_velocity(self):
        ball = main.PongBall()
        ball.pos = (10, 20)
        ball.velocity = (3, -4)

        ball.move()

        assert ball.pos == [13, 16]


class TestDetermineGameOwner:
    def test_lexicographically_smaller_name_owns_game(self):
        assert main.PongGame._determine_game_owner(None, "alice", "bob") is True
        assert main.PongGame._determine_game_owner(None, "bob", "alice") is False
