import json
import requests
import time
import threading
from dataclasses import dataclass
from typing import List, Tuple, Optional
from pathlib import Path
from PIL import Image, ImageChops
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QTimer


API_BASE_URL = 'http://20.55.21.76:5006'
SAVE_FILE = Path("saved_info.json")
UPDATE_INTERVAL = 60
CLICK_INTERVAL = 15
MAX_RETRIES = 5


@dataclass
class URLInfo:
    url: str
    interval: int
    source_type: str


class APIClient:
    @staticmethod
    def get_aniversarios() -> List[URLInfo]:
        for retry in range(MAX_RETRIES):
            try:
                response = requests.get(f'{API_BASE_URL}/aniversario')
                if response.status_code == 200:
                    data = response.json()
                    return [URLInfo(url=item[0], interval=item[1], source_type=item[2]) for item in data]
            except Exception as e:
                print(f"Erro na API (tentativa {retry + 1}/{MAX_RETRIES}): {e}")
            time.sleep(min(60, 2 ** retry))
        return []


    @staticmethod
    def get_screenshot(url: str, source_type: str) -> Optional[bytes]:
        try:
            response = requests.post(f'{API_BASE_URL}/screenshot', 
                                     json={'url': url, 'source': source_type})
            if response.status_code == 200:
                return response.content
        except Exception as e:
            print(f"Erro ao obter screenshot: {e}")
        return None


class DataManager:
    @staticmethod
    def load_saved_info() -> List[URLInfo]:
        try:
            return [URLInfo(**item) for item in json.loads(SAVE_FILE.read_text())]
        except (FileNotFoundError, json.JSONDecodeError):
            return []


    @staticmethod
    def save_info(urls: List[URLInfo]) -> None:
        try:
            SAVE_FILE.write_text(json.dumps([item.__dict__ for item in urls], indent=4))
        except Exception as e:
            print(f"Erro ao salvar informações: {e}")


class ImageProcessor:
    @staticmethod
    def process_image(image: Image.Image, source_type: str) -> Image.Image:
        if source_type == 'manual':
            image = ImageProcessor._crop_white_borders(image)
            image = ImageProcessor._crop_bottom_40px(image)
        return image


    @staticmethod
    def _crop_white_borders(img: Image.Image) -> Image.Image:
        bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        return img.crop(bbox) if bbox else img


    @staticmethod
    def _crop_bottom_40px(img: Image.Image) -> Image.Image:
        width, height = img.size
        return img.crop((0, 0, width, height - 40))


class ImageWindow(QMainWindow):
    def __init__(self, urls: List[URLInfo], update_callback):
        super().__init__()
        self.urls = urls
        self.update_callback = update_callback
        self.current_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_image_dash)
        self.setup_ui()

    def setup_ui(self):
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setWindowState(Qt.WindowFullScreen)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.showFullScreen()
        self.update_image_dash()

    def update_image_dash(self):
        url_info = self.urls[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.urls)

        image_data = APIClient.get_screenshot(url_info.url, url_info.source_type)
        if image_data:
            image = Image.open(io.BytesIO(image_data))
            image = ImageProcessor.process_image(image, url_info.source_type)
            image.save("current_image.png")

            pixmap = QPixmap("current_image.png")
            self.label.setPixmap(pixmap.scaled(
                self.label.size(),
                Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation
            ))

            self.timer.start(url_info.interval * 1000)

    def start_update_thread(self):
        self.update_thread = threading.Thread(target=self.periodic_update, daemon=True)
        self.update_thread.start()

    def periodic_update(self):
        while True:
            new_urls = self.update_callback()
            if new_urls != self.urls:
                self.urls = new_urls
                DataManager.save_info(self.urls)
            time.sleep(UPDATE_INTERVAL)


class TerminalClient:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.running = True
        self.urls = self.initialize_urls()
        self.start_update_thread()
        self.main_loop()

    def initialize_urls(self) -> List[URLInfo]:
        saved_info = DataManager.load_saved_info()
        api_info = APIClient.get_aniversarios()
        return api_info or saved_info

    def start_update_thread(self):
        self.update_thread = threading.Thread(target=self.periodic_update, daemon=True)
        self.update_thread.start()

    def periodic_update(self):
        while self.running:
            new_urls = APIClient.get_aniversarios()
            if new_urls != self.urls:
                self.urls = new_urls
                DataManager.save_info(self.urls)
            time.sleep(UPDATE_INTERVAL)

    def main_loop(self):
        while self.running:
            key = self.stdscr.getch()
            if key == ord('q'):
                self.running = False
                DataManager.save_info(self.urls)


if __name__ == "__main__":
    curses.wrapper(TerminalClient)
