# Neon Ping-Pong
# Copyright (C) 2026  Goodarz Mehr

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

'''
Neon Ping-Pong

First to 11 points, win by 2.

Modes: 1 player (you vs the computer) or 2 players (P1 W/S, P2 ↑/↓).

Controls: T switch mode (menu), P/Esc pause, Space start/skip serve,
R restart, 1/2/3/4/5 difficulty, M mute.
'''

import os
import sys
import math
import array
import random
import pygame

# Configuration
WIDTH, HEIGHT = 1600, 1200   # window size (px)
FPS = 60
SIDE_MARGIN = 40             # distance of paddles from the left/right walls
                             # (px)
PADDLE_W, PADDLE_H = 16, 160 # paddle size (px)
PADDLE_SPEED = 1200.0        # player paddle speed (px/s)
BALL_R = 16                  # ball radius (px)
BALL_SPEED = 640.0           # initial ball speed (px/s)
BALL_MAX_SPEED = 6400.0      # maximum ball speed (px/s)
BALL_ACCEL = 1.05            # ball acceleration (5% speed increase per paddle hit)
WIN_SCORE = 11               # first to 11, win by 2
MAX_BOUNCE_ANGLE = 60.0      # maximum bounce angle (degrees off the horizontal)
SERVE_DELAY = 3.0            # countdown duration before the serve (seconds)
SHAKE_ON_SCORE = 11.0        # screen-shake intensity on scoring
TRAIL_LEN = 64               # length of the ball trail
GLOW_RADIUS = 32             # glow radius around paddles (px)

# State machine
MENU, SERVE, PLAY, PAUSE, GAME_OVER = range(5)

# Neon palette
BG_TOP = (10, 10, 24)
BG_BOTTOM = (24, 12, 44)
NET_COLOR = (96, 128, 168)
PLAYER_COLOR = (64, 224, 240)
COMPUTER_COLOR = (240, 92, 220)
BALL_COLOR = (240, 240, 240)
DIM = (148, 158, 196)
GOLD = (240, 214, 96)

# Difficulty levels
AI_PROFILES = {
    1: {'name': 'Easy', 'speed': 320.0, 'lead': 1.0, 'wander': 160.0},
    2: {'name': 'Medium', 'speed': 480.0, 'lead': 0.8, 'wander': 120.0},
    3: {'name': 'Hard', 'speed': 640.0, 'lead': 0.6, 'wander': 80.0},
    4: {'name': 'Expert', 'speed': 960.0, 'lead': 0.4, 'wander': 40.0},
    5: {'name': 'Impossible', 'speed': 1120.0, 'lead': 0.2, 'wander': 0.0}
}


class Sound:
    '''Tiny chiptune blips built from raw square/sine samples.'''
    def __init__(self):
        self.enabled = False

        try:
            pygame.mixer.init()

            self.enabled = pygame.mixer.get_init() is not None
        except pygame.error:
            pass

        self._cache = {}

    @staticmethod
    def _to_sound(samples: list[float]) -> pygame.mixer.Sound:
        '''
        Convert floats in [-1, 1] to a Sound, matching the mixer's channel
        count (mono samples are duplicated for a stereo mixer).

        Args:
            samples: list of floats in [-1, 1] (one sample per frame).
        
        Returns:
            Sound object.
        '''
        _, _, channels = pygame.mixer.get_init()

        out = array.array('h')

        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32767)

            out.append(v)

            if channels > 1:
                out.append(v)

        return pygame.mixer.Sound(buffer=out.tobytes())

    @staticmethod
    def _tone_samples(freq: float, dur: float, vol: float, wave: str, slide: float = 0.0) -> list[float]:
        '''
        Raw samples of one tone with an optional pitch slide and a linear
        fade-out envelope.

        Args:
            freq: starting frequency (Hz).
            dur: duration (seconds).
            vol: volume (0.0 to 1.0).
            wave: 'sine' or 'square'.
            slide: frequency change over the duration (Hz).

        Returns:
            samples: list of sound samples (one sample per frame).
        '''
        rate = 48000
        n = max(1, int(rate * dur))

        samples = []

        for i in range(n):
            t = i / rate

            f = freq + slide * (i / n)

            s = math.sin(2 * math.pi * f * t)

            v = s if wave == 'sine' else (1.0 if s >= 0 else -1.0) * 0.45

            samples.append(v * vol * (1 - i / n))

        return samples

    def _cached(self, key: str, samples: list[float]) -> pygame.mixer.Sound:
        '''
        Convert samples to a Sound, storing it in the cache under key.
        
        Args:
            key: cache key.
            samples: list of sound samples (one sample per frame).
        
        Returns:
            snd: Sound object.
        '''
        snd = self._to_sound(samples)

        self._cache[key] = snd

        return snd

    def _tone(
        self,
        key: str,
        freq: float,
        dur: float,
        vol: float = 0.5,
        wave: str = 'square',
        slide: float = 0.0
    ) -> pygame.mixer.Sound | None:
        '''
        Build and cache a Sound of one tone with an optional pitch slide.
        
        Args:
            key: cache key.
            freq: starting frequency (Hz).
            dur: duration (seconds).
            vol: volume (0.0 to 1.0).
            wave: 'sine' or 'square'.
            slide: frequency change over the duration (Hz).

        Returns:
            Sound object, or None if audio is disabled.
        '''
        if not self.enabled:
            return None

        if key in self._cache:
            return self._cache[key]

        return self._cached(key, self._tone_samples(freq, dur, vol, wave, slide))

    def _seq(
        self,
        key: str,
        notes: list[tuple[float, float]],
        vol: float = 0.5,
        wave: str = 'square'
    ) -> pygame.mixer.Sound | None:
        '''
        Concatenate a list of (freq, dur) notes into one Sound.
        
        Args:
            key: cache key.
            notes: list of (frequency, duration) tuples.
            vol: volume (0.0 to 1.0).
            wave: 'sine' or 'square'.

        Returns:
            Sound object, or None if audio is disabled. 
        '''
        if not self.enabled:
            return None

        if key in self._cache:
            return self._cache[key]

        samples = []

        for f, d in notes:
            samples.extend(self._tone_samples(f, d, vol, wave))

        return self._cached(key, samples)

    def _play(self, snd: pygame.mixer.Sound | None):
        '''
        Play a sound if audio is enabled.
        
        Args:
            snd: Sound object, or None if audio is disabled.
        '''
        if self.enabled and snd is not None:
            snd.play()

    def paddle(self):
        '''Play the paddle-hit blip.'''
        self._play(self._tone('paddle', 520, 0.06, 0.5, 'square'))

    def wall(self):
        '''Play the wall-bounce blip.'''
        self._play(self._tone('wall', 300, 0.05, 0.4, 'square'))

    def score(self):
        '''Play the two-note score jingle.'''
        self._play(self._seq('score', [(392, 0.09), (262, 0.16)], 0.45))

    def win(self):
        '''Play the ascending win fanfare.'''
        notes = [(523, 0.09), (659, 0.09), (784, 0.09), (1047, 0.28)]

        self._play(self._seq('win', notes, 0.5))

    def lose(self):
        '''Play the descending lose jingle.'''
        notes = [(392, 0.12), (311, 0.12), (233, 0.28)]

        self._play(self._seq('lose', notes, 0.5))

    def serve(self):
        '''Play the serve-launch blip.'''
        self._play(self._tone('serve', 660, 0.07, 0.35, 'sine'))

    def toggle(self) -> bool:
        '''
        Toggle audio on/off.
        
        Returns:
            The new audio state.
        '''
        self.enabled = not self.enabled

        return self.enabled


class Particles:
    '''Simple spark system. Add bursts, update, and draw as fading circles.'''
    def __init__(self):
        # Items: [x, y, vx, vy, life, max_life, color, size].
        self.items = []

    def burst(
        self,
        x: float,
        y: float,
        color: tuple[int, int, int],
        count: int = 14,
        speed: float = 260.0,
        size: float = 3.0,
    ):
        '''
        Spawn a burst of sparks at (x, y).
        
        Args:
            x, y: center of the burst.
            color: RGB color of the sparks.
            count: number of sparks to spawn.
            speed: initial speed of the sparks (px/s).
            size: radius of the sparks (px).
        '''
        for _ in range(count):
            a = random.uniform(0, math.tau)

            s = random.uniform(0.3, 1.0) * speed

            life = random.uniform(0.25, 0.6)

            self.items.append([x, y, math.cos(a) * s, math.sin(a) * s, life, life, color, random.uniform(1.5, size)])

    def update(self, dt: float):
        '''
        Advance sparks by dt seconds and drop the dead ones.
        
        Args:
            dt: time step (seconds).
        '''
        for p in self.items:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[2] *= 0.92
            p[3] *= 0.92
            p[4] -= dt

        self.items = [p for p in self.items if p[4] > 0]

    def draw(self, surf: pygame.Surface):
        '''
        Draw all sparks as fading circles.
        
        Args:
            surf: surface to draw on.
        '''
        for p in self.items:
            alpha = max(0.0, p[4] / p[5])

            r = max(1, int(p[7] * alpha))

            c = (
                min(255, int(p[6][0] * alpha + 40)),
                min(255, int(p[6][1] * alpha + 40)),
                min(255, int(p[6][2] * alpha + 40)),
            )

            pygame.draw.circle(surf, c, (int(p[0]), int(p[1])), r)


def make_glow(
    color: tuple[int, int, int],
    w: int,
    h: int,
    radius: int,
    alpha: int = 160,
    corner: int = 7,
) -> pygame.Surface:
    '''
    Pre-render a soft glow around a rectangle. One translucent rounded
    rectangle per pixel of radius, with alpha fading quadratically from the
    rectangle's edge (brightest). Rectangles are drawn outer-most first so
    each pixel's alpha fades smoothly instead of stacking into a flat block.

    Args:
        color: RGB color of the glow.
        w, h: width and height of the rectangle (px).
        radius: glow radius (px).
        alpha: maximum alpha at the rectangle's edge (0 - 255).
        corner: corner radius of the inner rectangle (px).
    
    Returns:
        surf: Surface with the glow.
    '''
    surf = pygame.Surface((w + radius * 2, h + radius * 2), pygame.SRCALPHA)

    for d in range(radius, -1, -1):
        a = int(alpha * (1 - d / radius) ** 2)

        inset = radius - d

        pygame.draw.rect(
            surf, (*color, a),
            pygame.Rect(inset, inset, w + 2 * d, h + 2 * d),
            border_radius=corner + d,
        )

    return surf


class Paddle:
    '''
    Vertical paddle with a pre-rendered glow.

    Args:
        x: x coordinate of the paddle's edge nearest to the wall.
        color: RGB color of the paddle.
        is_player: which side the paddle is on (True =left side).
        is_human: whether the paddle is controlled from the keyboard.
    '''
    def __init__(
        self,
        x: int,
        color: tuple[int, int, int],
        is_player: bool,
        is_human: bool = True,
    ):
        self.x = x
        self.y = HEIGHT / 2
        self.color = color
        self.is_player = is_player
        self.is_human = is_human

        self.glow = make_glow(color, PADDLE_W, PADDLE_H, GLOW_RADIUS)

        self._clamp()

    @property
    def front_x(self) -> float:
        '''x coordinate of the paddle face that hits the incoming ball.'''
        return self.x + PADDLE_W / 2 if self.is_player else self.x - PADDLE_W / 2

    def _clamp(self):
        '''
        Clamp y coordinate of the paddle inside the screen and update
        top/bottom.
        '''
        self.y = max(PADDLE_H / 2, min(HEIGHT - PADDLE_H / 2, self.y))
        self.top = self.y - PADDLE_H / 2
        self.bottom = self.y + PADDLE_H / 2

    def center(self):
        '''Snap back to vertical center (used at the start of each serve).'''
        self.y = HEIGHT / 2

        self._clamp()

    def update(self, dt: float, direction: int = 0):
        '''
        Move a human paddle by direction (-1/0/+1) for dt seconds.

        Args:
            dt: time step (seconds).
            direction: movement direction (-1, 0, or 1).
        '''
        if self.is_human:
            self.y += direction * PADDLE_SPEED * dt

        self._clamp()

    def move_toward(self, target: float, speed: float, dt: float):
        '''
        Close in on target at up to speed px/s (computer steering).

        Args:
            target: target y coordinate to move toward.
            speed: maximum speed (px/s).
            dt: time step (seconds).
        '''
        diff = target - self.y

        self.y += max(-speed * dt, min(speed * dt, diff))

        self._clamp()


class Ball:
    '''Ping-pong ball with a trail of fading circles.'''
    def __init__(self):
        # Create the ball at the center of the screen, at rest.
        self.x = WIDTH / 2
        self.y = HEIGHT / 2
        self.vx = 0.0
        self.vy = 0.0
        self.speed = BALL_SPEED
        self.trail = []

    def reset(self):
        '''
        Return the ball to the center of the screen, at rest, clearing the
        trail.
        '''
        self.x = WIDTH / 2
        self.y = HEIGHT / 2
        self.vx = self.vy = 0.0
        self.speed = BALL_SPEED
        self.trail.clear()

    def launch(self, toward_player: bool):
        '''
        Serve at a random vertical angle, toward the given side.

        Args:
            toward_player: True to serve toward the player, False otherwise.
        '''
        angle = math.radians(random.uniform(-25, 25))

        self.speed = BALL_SPEED

        dx = -1.0 if toward_player else 1.0

        self.vx = dx * self.speed * math.cos(angle)
        self.vy = self.speed * math.sin(angle)

        self.trail.clear()

    def bounce_paddle(self, paddle: Paddle):
        '''
        Deflect off a paddle, angle depends on where the ball hit.

        Args:
            paddle: the paddle the ball bounced off of.
        '''
        rel = (self.y - paddle.y) / (PADDLE_H / 2)
        rel = max(-1.0, min(1.0, rel))

        angle = math.radians(rel * MAX_BOUNCE_ANGLE)

        self.speed = min(BALL_MAX_SPEED, self.speed * BALL_ACCEL)

        dx = 1.0 if paddle.is_player else -1.0

        self.vx = dx * self.speed * math.cos(angle)
        self.vy = self.speed * math.sin(angle)

    def update(self, dt: float):
        '''
        Update the ball's position based on its velocity and record the trail.

        Args:
            dt: time step (seconds).
        '''
        self.x += self.vx * dt
        self.y += self.vy * dt

        self.trail.append((self.x, self.y))

        if len(self.trail) > TRAIL_LEN:
            self.trail.pop(0)

    def predict_y_at(self, x_target: float) -> float:
        '''
        Predict the y coordinate where the ball will cross a target x
        coordinate, accounting for wall bounces.

        Args:
            x_target: x coordinate to predict the crossing y for.

        Returns:
            Predicted y coordinate where the ball crosses the target x
                coordinate.
        '''
        if self.vx == 0:
            return HEIGHT / 2

        t = (x_target - self.x) / self.vx

        if t < 0:
            return self.y

        y = self.y + self.vy * t

        # Fold y into [0, HEIGHT] using reflections off the walls.
        span = 2 * HEIGHT

        y = y % span

        if y > HEIGHT:
            y = span - y

        return y


class Game:
    '''
    The game, which includes the state machine, physics, AI, input, and
    rendering.

    Args:
        screen: the display window (may be smaller than the canvas on small
            or high-scale-factor displays).
        sound: synthesized sound effects.
        smoke: if True, auto-quit after a few seconds (self-test).
    '''
    def __init__(self, screen: pygame.Surface, sound: Sound, smoke: bool = False):
        # self.display is the real window, self.screen is the fixed 1600x1200
        # canvas we draw on. They're the same surface when the window is
        # exactly 1600x1200, otherwise the canvas is scaled down onto the
        # window every frame in run().
        self.display = screen

        if screen.get_size() == (WIDTH, HEIGHT):
            self.screen = screen
        else:
            self.screen = pygame.Surface((WIDTH, HEIGHT))

        self.sound = sound
        self.smoke = smoke

        self.clock = pygame.time.Clock()

        # Entities.
        self.particles = Particles()
        self.player = Paddle(SIDE_MARGIN, PLAYER_COLOR, True)
        self.computer = Paddle(WIDTH - SIDE_MARGIN, COMPUTER_COLOR, False, is_human=False)
        self.ball = Ball()

        # Match state.
        self.state = MENU
        self.prev_state = MENU
        self.scores = [0, 0]
        self.difficulty = 2
        self.winner = None
        self.two_player = False

        # Serve and effects.
        self.serve_timer = 0.0
        self.serve_toward_player = True
        self.shake = 0.0
        self.run_time = 0.0

        # Computer steering state.
        self.computer_wander = 0.0
        self.computer_wander_timer = 0.0
        self.computer_react_timer = 0.0
        self._computer_incoming = False

        # Pre-rendered surfaces and fonts.
        self.background = self._make_background()
        self.ball_glow = self._make_ball_glow()

        self._trail_cache = {}

        self.fonts = {
            'big': pygame.font.SysFont('arial', 96, bold=True),
            'title': pygame.font.SysFont('arial', 64, bold=True),
            'mid': pygame.font.SysFont('arial', 32, bold=True),
            'small': pygame.font.SysFont('arial', 24),
        }

    @staticmethod
    def _make_background() -> pygame.Surface:
        '''
        Create the background, a vertical gradient with a faint vignette,
        pre-rendered once.

        Returns:
            bg: Surface with the background.
        '''
        bg = pygame.Surface((WIDTH, HEIGHT))

        for y in range(HEIGHT):
            t = y / HEIGHT

            c = (
                int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
            )

            pygame.draw.line(bg, c, (0, y), (WIDTH, y))

        # Subtle vignette.
        vig = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

        for i in range(24):
            a = int(2.2 * i)

            pygame.draw.rect(vig, (0, 0, 8, a), pygame.Rect(0, 0, WIDTH, HEIGHT), i)

        bg.blit(vig, (0, 0))

        return bg

    @staticmethod
    def _make_ball_glow() -> pygame.Surface:
        '''
        Create a pre-rendered radial glow around the ball (built once).
        
        Returns:
            glow: Surface with the radial glow.
        '''
        glow = pygame.Surface((BALL_R * 12, BALL_R * 12), pygame.SRCALPHA)

        for i in range(24, 0, -1):
            pygame.draw.circle(glow, (*BALL_COLOR, (24 - i) * 8), (BALL_R * 6, BALL_R * 6), BALL_R / 8 * i)

        return glow

    def _trail_surf(self, r: int, a: int) -> pygame.Surface:
        '''
        Draw a translucent circle for the ball trail.

        Args:
            r: circle radius (px).
            a: alpha (0 - 255).

        Returns:
            surf: Surface with the circle.
        '''
        surf = self._trail_cache.get((r, a))

        if surf is None:
            surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)

            pygame.draw.circle(surf, (*BALL_COLOR, a), (r, r), r)

            self._trail_cache[(r, a)] = surf

        return surf

    def start_match(self):
        '''Reset scores and start a fresh match with a random first serve.'''
        self.scores = [0, 0]
        self.winner = None

        self._begin_serve(random.choice([True, False]))

    def _begin_serve(self, toward_player: bool):
        '''
        Reset everything and start the serve countdown toward the desired
        side.

        Args:
            toward_player: True to serve toward the player, False otherwise.
        '''
        self.ball.reset()
        self.player.center()
        self.computer.center()

        self.serve_toward_player = toward_player
        self.serve_timer = SERVE_DELAY
        self.computer_wander = 0.0
        self._computer_incoming = False
        self.computer_react_timer = 0.0
        self.state = SERVE

    def _score(self, side: int):
        '''
        Award a point to the specified side (0 = player, 1 = computer).

        Args:
            side: scoring side (0 = player, 1 = computer).
        '''
        self.scores[side] += 1

        self.shake = SHAKE_ON_SCORE

        color = PLAYER_COLOR if side == 0 else COMPUTER_COLOR

        self.particles.burst(self.ball.x, self.ball.y, color, 26, 340.0, 4.0)
        self.sound.score()

        if self.scores[side] >= WIN_SCORE and self.scores[side] - self.scores[1 - side] >= 2:
            self.winner = side
            self.state = GAME_OVER

            if side == 0:
                self.sound.win()
            else:
                self.sound.lose() if not self.two_player else self.sound.win()
        else:
            self._begin_serve(toward_player=(side == 1))

    def handle_events(self) -> bool:
        '''
        Process pending events.
        
        Returns:
            False if the window is closed, True otherwise.
        '''
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return False

            if e.type == pygame.KEYDOWN:
                self._handle_key(e.key)

        return True

    def _handle_key(self, key: int):
        '''
        Dispatch a KEYDOWN by key to the matching handler.

        Args:
            key: pygame key constant from the KEYDOWN event.
        '''
        if key == pygame.K_m:
            self.sound.toggle()

        if key in (pygame.K_p, pygame.K_ESCAPE):
            self._handle_pause_key(key)

        if key in (pygame.K_SPACE, pygame.K_RETURN):
            self._handle_action_key()

        if key == pygame.K_r and self.state in (PLAY, PAUSE, GAME_OVER):
            self.start_match()

        if key == pygame.K_t and self.state == MENU:
            self.two_player = not self.two_player
            self.computer.is_human = self.two_player

        if self.state in (MENU, PLAY, PAUSE, GAME_OVER) and not self.two_player:
            self._handle_difficulty_key(key)

    def _handle_pause_key(self, key: int):
        '''
        Toggle pause; or go from the pause screen to the menu.

        Args:
            key: pygame key constant from the KEYDOWN event.
        '''
        if self.state == PLAY:
            self.prev_state = PLAY
            self.state = PAUSE
        elif self.state == PAUSE:
            if key == pygame.K_ESCAPE:
                self.state = MENU
            else:
                self.state = self.prev_state

    def _handle_action_key(self):
        '''
        Start, skip the serve countdown, return to the menu, or pause/resume
        the game.
        '''
        if self.state == MENU:
            self.start_match()
        elif self.state == GAME_OVER:
            self.state = MENU
        elif self.state == SERVE:
            # Skip the serve countdown.
            self.serve_timer = 0.0
        elif self.state == PAUSE:
            self._handle_pause_key(pygame.K_p)
        elif self.state == PLAY:
            self._handle_pause_key(pygame.K_p)

    def _handle_difficulty_key(self, key: int):
        '''
        Map the 1-5 keys to difficulty levels.

        Args:
            key: pygame key constant from the KEYDOWN event.
        '''
        if key == pygame.K_1:
            self._set_difficulty(1)
        elif key == pygame.K_2:
            self._set_difficulty(2)
        elif key == pygame.K_3:
            self._set_difficulty(3)
        elif key == pygame.K_4:
            self._set_difficulty(4)
        elif key == pygame.K_5:
            self._set_difficulty(5)

    def _set_difficulty(self, level: int):
        '''
        Change the difficulty, re-serve mid-match if needed.

        Args:
            level: new difficulty level (1 - 5).
        '''
        if self.difficulty != level:
            self.difficulty = level

            # Re-serve so the new AI applies fairly.
            if self.state == PLAY:
                self._begin_serve(self.serve_toward_player)

    def update(self, dt: float) -> bool:
        '''
        Advance the game by dt seconds.

        Args:
            dt: time step (seconds).

        Returns:
            False to quit, True otherwise.
        '''
        self.run_time += dt

        self.particles.update(dt)

        self.shake = max(0.0, self.shake - 30.0 * dt)

        if self.state == SERVE:
            self.serve_timer -= dt

            if not self.two_player:
                self._update_computer_idle(dt)

            if self.serve_timer <= 0:
                self.ball.launch(self.serve_toward_player)
                self.sound.serve()
                self.state = PLAY

        elif self.state == PLAY:
            keys = pygame.key.get_pressed()

            if self.two_player:
                # P1 (left): W/S · P2 (right): arrow keys.
                dir1 = (1 if keys[pygame.K_s] else 0) - (1 if keys[pygame.K_w] else 0)
                dir2 = (1 if keys[pygame.K_DOWN] else 0) - (1 if keys[pygame.K_UP] else 0)

                self.player.update(dt, dir1)
                self.computer.update(dt, dir2)
            else:
                direction = (
                    (1 if (keys[pygame.K_s] or keys[pygame.K_DOWN]) else 0)
                    - (1 if (keys[pygame.K_w] or keys[pygame.K_UP]) else 0)
                )

                self.player.update(dt, direction)
                self._update_computer(dt)

            self._update_ball(dt)

        if self.smoke and self.run_time > 5.0:
            return False

        return True

    def _update_computer_idle(self, dt: float):
        '''
        During the serve countdown the computer drifts gently toward center.

        Args:
            dt: time step (seconds).
        '''
        profile = AI_PROFILES[self.difficulty]

        self.computer.move_toward(HEIGHT / 2, profile['speed'] * 0.6, dt)

    def _update_computer(self, dt: float):
        '''
        Steer the computer. Predict incoming balls, drift home otherwise.

        Args:
            dt: time step (seconds).
        '''
        profile = AI_PROFILES[self.difficulty]

        ball = self.ball
        incoming = ball.vx > 0

        if incoming:
            if not self._computer_incoming:
                # Ball just turned toward the computer. The reaction clock
                # starts now.
                self.computer_react_timer = 0.0

            self._computer_incoming = True
            self.computer_react_timer += dt

            if self.computer_react_timer >= profile['lead']:
                # React and predict the crossing point, accounting for wall
                # bounces.
                target = ball.predict_y_at(self.computer.front_x - BALL_R)
            else:
                # Within the reaction delay. Track current ball position.
                target = ball.y

            # Aiming error, refreshed every ~0.4 s so it doesn't jitter.
            self.computer_wander_timer -= dt

            if self.computer_wander_timer <= 0:
                self.computer_wander = random.uniform(-profile['wander'], profile['wander'])
                self.computer_wander_timer = 0.4

            target += self.computer_wander
        else:
            self._computer_incoming = False

            # Ball moving away. Drift home to the center.
            target = HEIGHT / 2 + self.computer_wander * 0.4

        self.computer.move_toward(target, profile['speed'], dt)

    def _update_ball(self, dt: float):
        '''
        Move the ball in sub-steps. Calculate bounces, paddle hits, scoring.

        Args:
            dt: time step (seconds).
        '''
        ball = self.ball

        # Sub-step so a fast ball can't tunnel through a paddle or wall in
        # a single frame (keeps per-step movement under ~8 px).
        sp = math.hypot(ball.vx, ball.vy)
        steps = max(1, int(math.ceil(sp * dt / 8.0)))
        sdt = dt / steps

        for _ in range(steps):
            ball.update(sdt)

            # Wall bounces.
            if ball.y - BALL_R <= 0 and ball.vy < 0:
                ball.y = BALL_R
                ball.vy = -ball.vy
                self.particles.burst(ball.x, 0, NET_COLOR, 8, 180.0, 2.5)
                self.sound.wall()

            elif ball.y + BALL_R >= HEIGHT and ball.vy > 0:
                ball.y = HEIGHT - BALL_R
                ball.vy = -ball.vy
                self.particles.burst(ball.x, HEIGHT, NET_COLOR, 8, 180.0, 2.5)
                self.sound.wall()

            # Paddle collisions.
            if ball.vx < 0:
                p = self.player

                if (ball.x - BALL_R <= p.front_x 
                        and ball.x - BALL_R > p.front_x - PADDLE_W 
                        and p.top - BALL_R < ball.y < p.bottom + BALL_R):
                    ball.x = p.front_x + BALL_R
                    ball.bounce_paddle(p)
                    self.particles.burst(ball.x, ball.y, p.color, 12, 240.0, 3.0)
                    self.sound.paddle()

            elif ball.vx > 0:
                p = self.computer

                if (ball.x + BALL_R >= p.front_x
                        and ball.x + BALL_R < p.front_x + PADDLE_W
                        and p.top - BALL_R < ball.y < p.bottom + BALL_R):
                    ball.x = p.front_x - BALL_R
                    ball.bounce_paddle(p)
                    self.particles.burst(ball.x, ball.y, p.color, 12, 240.0, 3.0)
                    self.sound.paddle()

            # Scoring (changes state, so stop stepping immediately).
            if ball.x < -BALL_R * 2:
                self._score(1)

                return
            elif ball.x > WIDTH + BALL_R * 2:
                self._score(0)

                return

    def draw(self):
        '''Render the frame (world, HUD, and the state overlay).'''
        self.screen.blit(self.background, (0, 0))

        if self.shake > 0:
            ox = random.uniform(-self.shake, self.shake)
            oy = random.uniform(-self.shake, self.shake)

            self._draw_world(ox, oy)
        else:
            self._draw_world(0, 0)

        self._draw_hud()

        if self.state == MENU:
            self._draw_menu()
        elif self.state == SERVE:
            self._draw_serve_overlay()
        elif self.state == PAUSE:
            self._draw_pause()
        elif self.state == GAME_OVER:
            self._draw_game_over()

    def _draw_world(self, ox: float, oy: float):
        '''
        Draw the net, paddles, ball trail, ball, and particles.

        Args:
            ox: horizontal shake offset (px).
            oy: vertical shake offset (px).
        '''
        # Center net (dashed).
        for y in range(12, HEIGHT - 12, 28):
            pygame.draw.rect(self.screen, NET_COLOR, (WIDTH // 2 - 2, int(y + oy), 4, 16))

        # Paddles with glow.
        for p in (self.player, self.computer):
            rect = pygame.Rect(int(p.x - PADDLE_W / 2 + ox), int(p.top + oy), PADDLE_W, PADDLE_H)

            self.screen.blit(p.glow, (rect.x - GLOW_RADIUS, rect.y - GLOW_RADIUS))

            pygame.draw.rect(self.screen, p.color, rect, border_radius=7)

            core = (min(255, p.color[0] + 90), min(255, p.color[1] + 90), min(255, p.color[2] + 90))

            pygame.draw.rect(self.screen, core, (rect.x + 3, rect.y + 3, PADDLE_W - 6, PADDLE_H - 6), border_radius=5)

        # Ball trail.
        ball = self.ball

        if self.state in (PLAY, SERVE):
            for i, (tx, ty) in enumerate(ball.trail):
                f = (i + 1) / len(ball.trail)

                r = max(1, int(BALL_R * f * 0.8))

                a = int(140 * f)

                self.screen.blit(self._trail_surf(r, a), (int(tx + ox) - r, int(ty + oy) - r))

        # Ball with radial glow.
        if self.state in (PLAY, SERVE):
            self.screen.blit(self.ball_glow, (int(ball.x + ox) - BALL_R * 6, int(ball.y + oy) - BALL_R * 6))

            pygame.draw.circle(self.screen, BALL_COLOR, (int(ball.x + ox), int(ball.y + oy)), BALL_R)

        self.particles.draw(self.screen)

    def _draw_hud(self):
        '''Draw scores, side labels, and the footer control hint.'''
        f = self.fonts

        # Scores.
        for i, color in ((0, PLAYER_COLOR), (1, COMPUTER_COLOR)):
            s = f['big'].render(str(self.scores[i]), True, color)

            x = WIDTH // 2 + (-140 if i == 0 else 140)

            self.screen.blit(s, s.get_rect(center=(x, 64)))

        # Labels.
        left = 'Player 1' if self.two_player else 'You'

        ai_name = AI_PROFILES[self.difficulty]['name'].capitalize()

        right = 'Player 2' if self.two_player else f'Computer · {ai_name}'

        p = f['small'].render(left, True, PLAYER_COLOR)
        c = f['small'].render(right, True, COMPUTER_COLOR)

        self.screen.blit(p, p.get_rect(center=(WIDTH // 2 - 140, 128)))
        self.screen.blit(c, c.get_rect(center=(WIDTH // 2 + 140, 128)))

        # Footer hint.
        if self.two_player:
            hint = f['small'].render('P1 W/S · P2 ↑/↓ · P/Space/Enter/Esc pause · R restart · M mute', True, DIM)
        else:
            hint = f['small'].render(
                'W/S or ↑/↓ move · P/Space/Enter/Esc pause · R restart · 1/2/3/4/5 difficulty · M mute',
                True,
                DIM
            )

        self.screen.blit(hint, hint.get_rect(midbottom=(WIDTH // 2, HEIGHT - 10)))

    def _center_text(self, texts: list[tuple[str, str, tuple[int, int, int]]], y: int = HEIGHT // 2):
        '''
        Draw a vertical stack of (text, font_key, color) centered on x.

        Args:
            texts: list of (text, font key, RGB color) tuples, top to bottom.
            y: vertical center of the stack (px).
        '''
        gap = 14

        total = sum(self.fonts[fn].size(t)[1] for t, fn, _ in texts) + gap * (len(texts) - 1)

        y0 = y - total // 2

        for t, fn, color in texts:
            s = self.fonts[fn].render(t, True, color)

            self.screen.blit(s, s.get_rect(center=(WIDTH // 2, y0 + s.get_height() // 2)))

            y0 += s.get_height() + gap

    def _dim(self, alpha: int = 150):
        '''
        Blit a translucent dark overlay over the whole canvas.

        Args:
            alpha: overlay opacity (0 - 255).
        '''
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)

        overlay.fill((4, 5, 14, alpha))

        self.screen.blit(overlay, (0, 0))

    def _draw_menu(self):
        '''Draw the main menu with mode and control hints.'''
        self._dim(170)

        if self.two_player:
            mode = '2 players · local'
            controls = 'P1 W/S · P2 ↑/↓'
        else:
            mode = '1 player · you vs the computer'

            ai_name = AI_PROFILES[self.difficulty]['name']

            controls = f'W/S or ↑/↓ move · computer: {ai_name}'

        self._center_text(
            [
                ('NEON PING-PONG', 'title', BALL_COLOR),
                (mode, 'mid', DIM),
                (controls, 'small', DIM),
                ('', 'small', DIM),
                ('SPACE to play', 'mid', GOLD),
                ('T switch mode · first to 11 · win by 2', 'small', DIM),
            ],
            y=HEIGHT // 2 - 20
        )

    def _draw_serve_overlay(self):
        '''Draw the 'get ready' countdown before each serve.'''
        n = max(1, math.ceil(self.serve_timer))

        self._center_text([('GET READY', 'mid', DIM)], y=HEIGHT // 2 - 80)
        self._center_text([(str(n), 'title', BALL_COLOR)], y=HEIGHT // 2 + 80)

    def _draw_pause(self):
        '''Draw the pause overlay.'''
        self._dim(180)

        self._center_text([('PAUSED', 'title', BALL_COLOR), ('P/Space to resume · Esc for menu', 'small', DIM)])

    def _draw_game_over(self):
        '''Draw the winner, final score, and rematch hint.'''
        self._dim(190)

        if self.winner == 0:
            if self.two_player:
                title, color = 'PLAYER 1 WINS', PLAYER_COLOR
            else:
                title, color = 'YOU WIN!', PLAYER_COLOR
        elif self.two_player:
            title, color = 'PLAYER 2 WINS', COMPUTER_COLOR
        else:
            title, color = 'COMPUTER WINS', COMPUTER_COLOR

        self._center_text(
            [
                (title, 'title', color),
                (f'{self.scores[0]}  —  {self.scores[1]}', 'mid', BALL_COLOR),
                ('Space for menu · R to rematch', 'small', DIM),
            ],
            y=HEIGHT // 2 - 10
        )

    def run(self):
        '''
        Run the main loop (events, update, draw, present). Quits on QUIT/smoke.
        '''
        while True:
            if not self.handle_events():
                break

            dt = min(self.clock.tick(FPS) / 1000.0, 1 / 20)  # clamp long frames

            if not self.update(dt):
                break

            self.draw()

            if self.screen is not self.display:
                # Window is smaller than the canvas, so scale it down to fit.
                scaled = pygame.transform.smoothscale(self.screen, self.display.get_size())

                self.display.blit(scaled, (0, 0))

            pygame.display.flip()

        pygame.quit()


def main():
    smoke = '--smoke' in sys.argv

    if smoke:
        # Headless self-test, no real window/audio needed.
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

    pygame.init()

    # The game always renders at a fixed 1600x1200 canvas. We size the window
    # to fit the display: when the display is at least 1600x1200, use SCALED
    # so the window fills the screen while the game keeps its 1600x1200
    # resolution; otherwise (a small display, or a high scale-factor that
    # makes the usable area smaller than 1600x1200) make a plain window that
    # fits and scale the canvas down to it each frame.
    dw, dh = pygame.display.get_desktop_sizes()[0]

    if dw >= WIDTH and dh >= HEIGHT:
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.SCALED)
    else:
        fit = min(dw / WIDTH, dh / HEIGHT) * 0.9

        screen = pygame.display.set_mode((max(320, int(WIDTH * fit)), max(240, int(HEIGHT * fit))))

    pygame.display.set_caption('Neon Ping-Pong')

    sound = Sound()

    game = Game(screen, sound, smoke=smoke)

    if smoke:
        # Skip the menu so the self-test can evaluate serve/play/physics.
        game.start_match()

    game.run()


if __name__ == '__main__':
    main()
