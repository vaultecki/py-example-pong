from main import PongApp
import logging


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
game = PongApp()
game.run()
