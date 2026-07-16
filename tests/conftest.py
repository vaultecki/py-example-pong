import os

# Must be set before Kivy is imported (main.py imports it), so the graphics
# core picks a headless backend instead of trying to open a real window.
os.environ.setdefault("KIVY_NO_ARGS", "1")
os.environ.setdefault("KIVY_NO_FILELOG", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
