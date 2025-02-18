import json
import curses
import requests
import sys
import io
import time
import threading
from dataclasses import dataclass
from typing import List, Tuple, Optional
from pathlib import Path
from PIL import Image, ImageChops
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QTimer
import pyautogui



# ConfiguraÃ§Ãµes globais
API_BASE_URL = 'http://20.55.21.76:5006'
SAVE_FILE = Path("saved_info.json")
UPDATE_INTERVAL = 60  # segundos
CLICK_INTERVAL = 15  # segundos
MAX_RETRIES = 5



@dataclass
class URLInfo:
    url: str
    interval: int
    source_type: str



class APIClient:
    @staticmethod
    def get_aniversarios() -> List[Tuple[str, int, str]]:
        """ObtÃ©m dados de aniversÃ¡rios da API com retry exponencial."""
        for retry in range(MAX_RETRIES):
            try:
                response = requests.get(f'{API_BASE_URL}/aniversario')
                if response.status_code == 200:
                    return response.json()
            except Exception as e:
                print(f"Erro na API (tentativa {retry + 1}/{MAX_RETRIES}): {e}")
            time.sleep(min(60, 2 ** retry))
        return []



    @staticmethod
    def get_screenshot(url: str, source_type: str) -> Optional[bytes]:
        """ObtÃ©m screenshot da URL especificada."""
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
    def load_saved_info() -> List[Tuple[str, int, str]]:
        """Carrega informaÃ§Ãµes salvas do arquivo JSON."""
        try:
            return json.loads(SAVE_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []



    @staticmethod
    def save_info(urls: List[Tuple[str, int, str]]) -> None:
        """Salva informaÃ§Ãµes no arquivo JSON."""
        try:
            SAVE_FILE.write_text(json.dumps(urls, indent=4))
        except Exception as e:
            print(f"Erro ao salvar informaÃ§Ãµes: {e}")



class ImageProcessor:
    @staticmethod
    def process_image(image: Image.Image, source_type: str) -> Image.Image:
        """Processa a imagem baseado no tipo de fonte."""
        if source_type == 'manual':
            image = ImageProcessor._crop_white_borders(image)
            image = ImageProcessor._crop_bottom_40px(image)
        return image



    @staticmethod
    def _crop_white_borders(img: Image.Image) -> Image.Image:
        bg = Image.new(img.mode, img.size, img.getpixel((0,0)))
        diff = ImageChops.difference(img, bg)
        bbox = diff.getbbox()
        return img.crop(bbox) if bbox else img



    @staticmethod
    def _crop_bottom_40px(img: Image.Image) -> Image.Image:
        width, height = img.size
        return img.crop((0, 0, width, height - 40))



class ImageWindow(QMainWindow):
    def __init__(self, urls: List[Tuple[str, int, str]], update_callback):
        super().__init__()
        self.urls = urls
        self.update_callback = update_callback
        self.current_index = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_image_dash)
        self.setup_ui()
        self.start_update_thread()



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
        url, interval, source_type = self.urls[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.urls)



        image_data = APIClient.get_screenshot(url, source_type)
        if image_data:
            image = Image.open(io.BytesIO(image_data))
            image = ImageProcessor.process_image(image, source_type)
            image.save("current_image.png")

            pixmap = QPixmap("current_image.png")
            self.label.setPixmap(pixmap.scaled(
                self.label.size(), 
                Qt.IgnoreAspectRatio, 
                Qt.SmoothTransformation
            ))

            self.timer.start(interval * 1000)



    def start_update_thread(self):
        self.update_thread = threading.Thread(target=self.periodic_update, daemon=True)
        self.update_thread.start()



    def periodic_update(self):
        while True:
            new_urls = self.update_callback()
            if new_urls != self.urls:
                self.urls = [url for url in self.urls if url[2] != 'excel']
                if new_urls:
                    self.urls.extend(new_urls)
                DataManager.save_info(self.urls)
            time.sleep(UPDATE_INTERVAL)



class MouseController(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True



    def run(self):
        while self.running:
            screen_width, screen_height = pyautogui.size()
            pyautogui.click(screen_width // 2, screen_height - 1)
            time.sleep(CLICK_INTERVAL)



class TerminalClient:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.running = True
        self.urls = self.initialize_urls()
        self.start_update_thread()
        self.main_loop()



    def initialize_urls(self) -> List[Tuple[str, int, str]]:
        saved_info = DataManager.load_saved_info()
        api_info = APIClient.get_aniversarios()
        return api_info or saved_info



    def display_urls(self):
        self.stdscr.clear()
        self.stdscr.addstr(0, 0, "URLs e Intervalos (segundos):")

        for i, (url, interval, source_type) in enumerate(self.urls, 1):
            self.stdscr.addstr(i, 0, 
                f"{i}. URL: {url}, Intervalo: {interval}, Source Type: {source_type}")

        self.stdscr.addstr(len(self.urls) + 2, 0, 
            "a: adicionar URL, s: iniciar, r: remover URL, q: sair")
        self.stdscr.refresh()



    def start_update_thread(self):
        self.update_thread = threading.Thread(target=self.periodic_update, daemon=True)
        self.update_thread.start()



    def periodic_update(self):
        while self.running:
            new_urls = APIClient.get_aniversarios()
            if new_urls != self.urls:
                self.urls = [url for url in self.urls if url[2] != 'excel']
                if new_urls:
                    self.urls.extend(new_urls)
                DataManager.save_info(self.urls)
                self.display_urls()
            time.sleep(UPDATE_INTERVAL)



    def start_showing_urls(self):
        mouse_controller = MouseController()
        mouse_controller.start()



        app = QApplication(sys.argv)
        window = ImageWindow(self.urls, APIClient.get_aniversarios)
        sys.exit(app.exec())



    def main_loop(self):
        self.display_urls()
        while self.running:
            key = self.stdscr.getch()
            if key == ord('a'):
                self.add_url()
            elif key == ord('s'):
                self.start_showing_urls()
            elif key == ord('r'):
                self.remove_url()
            elif key == ord('q'):
                self.running = False
                DataManager.save_info(self.urls)



    def add_url(self):
        url = self.get_input("Digite a URL:")
        interval = int(self.get_input("Digite o intervalo em segundos:"))
        source_type = self.get_input("Digite o tipo de fonte (excel/manual):")
        self.urls.append((url, interval, source_type))
        DataManager.save_info(self.urls)
        self.display_urls()



    def remove_url(self):
        index = int(self.get_input("Digite o nÃºmero da URL para remover:")) - 1
        if 0 <= index < len(self.urls):
            del self.urls[index]
            self.stdscr.addstr(len(self.urls) + 3, 0, "URL removida com sucesso!")
            DataManager.save_info(self.urls)
        else:
            self.stdscr.addstr(len(self.urls) + 3, 0, "NÃºmero de URL invÃ¡lido.")
        self.display_urls()



    def get_input(self, prompt):
        self.stdscr.clear()
        self.stdscr.addstr(0, 0, prompt)
        self.stdscr.refresh()
        curses.echo()
        user_input = self.stdscr.getstr(1, 0).decode("utf-8")
        curses.noecho()
        return user_input



if __name__ == "__main__":
    curses.wrapper(TerminalClient)