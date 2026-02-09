import flet as ft
import socket
import threading
import time
import traceback
import sys

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ---
# Флаг работы сервера. Если False — потоки должны остановиться.
SERVER_RUNNING = False
# Порт для входящих подключений (SOCKS5 для Telegram)
LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 1090

def main(page: ft.Page):
    # --- 1. НАСТРОЙКА ИНТЕРФЕЙСА (ВИЗУАЛ) ---
    page.title = "Arrhythmia Pro"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10
    page.scroll = ft.ScrollMode.AUTO
    
    # Чтобы на мобильных клавиатура не перекрывала поля (на будущее)
    page.window_width = 360
    page.window_height = 800

    # --- ЭЛЕМЕНТЫ УПРАВЛЕНИЯ ---
    
    # Статус (Красный/Зеленый)
    status_indicator = ft.Container(
        width=15, height=15, border_radius=15, bgcolor="red"
    )
    status_text = ft.Text("SYSTEM OFFLINE", color="red", weight="bold")
    
    # Поле логов (Консоль прямо в приложении)
    # Используем ListView, чтобы он сам скроллился вниз
    logs_view = ft.ListView(
        expand=True, 
        spacing=2, 
        padding=10, 
        auto_scroll=True,
        height=300
    )
    
    logs_container = ft.Container(
        content=logs_view,
        bgcolor="#111111",
        border=ft.border.all(1, "#333333"),
        border_radius=10,
        padding=5,
        margin=ft.margin.only(top=10)
    )

    # Функция безопасного логгирования (чтобы не крашилось из других потоков)
    def log(message, color="white"):
        timestamp = time.strftime("%H:%M:%S")
        logs_view.controls.append(
            ft.Text(f"[{timestamp}] {message}", color=color, size=12, font_family="monospace")
        )
        # Ограничим историю логов (чтобы память не забивалась)
        if len(logs_view.controls) > 100:
            logs_view.controls.pop(0)
        page.update()

    # --- 2. ЛОГИКА СЕТИ (СЕРДЦЕ ТРАКТОРА) ---

    def run_proxy_server():
        global SERVER_RUNNING
        
        log(f"⚡ Запуск ядра сети...", "yellow")
        
        server_socket = None
        try:
            # Создаем сокет
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Разрешаем повторное использование порта (чтобы не ждать при перезапуске)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Пытаемся занять порт
            try:
                server_socket.bind((LISTEN_HOST, LISTEN_PORT))
            except OSError as e:
                log(f"⛔ Ошибка порта: {e}", "red")
                log("Возможно, порт занят другим приложением.", "red")
                reset_ui_to_stopped()
                return

            server_socket.listen(5)
            server_socket.settimeout(1.0) # Тайм-аут 1 сек, чтобы проверять флаг остановки

            log(f"✅ УСПЕХ: Слушаю {LISTEN_HOST}:{LISTEN_PORT}", "green")
            log("➡️ Настрой Telegram на этот адрес!", "cyan")

            while SERVER_RUNNING:
                try:
                    # Ждем подключения (максимум 1 сек, потом цикл повторяется)
                    client_socket, addr = server_socket.accept()
                    
                    # КТО-ТО ПОСТУЧАЛСЯ!
                    log(f"🔗 Входящее: {addr[0]}:{addr[1]}", "blue")
                    
                    # Здесь будет логика обработки трафика.
                    # Пока просто закрываем, подтверждая соединение.
                    # В будущем сюда вставим туннелирование.
                    client_socket.close()
                    
                except socket.timeout:
                    # Это нормально, просто проверяем, не нажали ли СТОП
                    continue
                except Exception as e:
                    log(f"⚠️ Ошибка цикла: {e}", "orange")

        except Exception as e:
            log(f"🔥 КРИТИЧЕСКИЙ СБОЙ: {traceback.format_exc()}", "red")
        
        finally:
            # Всегда закрываем ресурсы при выходе
            if server_socket:
                server_socket.close()
            log("🛑 Сервер остановлен.", "red")

    # --- 3. УПРАВЛЕНИЕ UI ---

    def reset_ui_to_stopped():
        global SERVER_RUNNING
        SERVER_RUNNING = False
        status_indicator.bgcolor = "red"
        status_text.value = "SYSTEM OFFLINE"
        status_text.color = "red"
        btn_start.text = "ACTIVATE"
        btn_start.bgcolor = "#222222"
        btn_start.disabled = False
        page.update()

    def toggle_server(e):
        global SERVER_RUNNING
        
        if not SERVER_RUNNING:
            # ЗАПУСК
            SERVER_RUNNING = True
            
            # Меняем UI
            status_indicator.bgcolor = "#00ff00" # Ярко-зеленый
            status_text.value = "SYSTEM ACTIVE"
            status_text.color = "#00ff00"
            btn_start.text = "DEACTIVATE"
            btn_start.bgcolor = "#550000" # Темно-красный
            page.update()
            
            # Запускаем поток (Thread), чтобы экран не завис
            t = threading.Thread(target=run_proxy_server, daemon=True)
            t.start()
            
        else:
            # ОСТАНОВКА
            log("Остановка процессов...", "yellow")
            SERVER_RUNNING = False
            # UI обновится сам, когда поток завершится, но для красоты меняем сразу
            status_indicator.bgcolor = "orange"
            status_text.value = "STOPPING..."
            status_text.color = "orange"
            btn_start.disabled = True # Блокируем кнопку пока не остановится
            page.update()
            
            # Даем потоку 1.5 секунды на завершение и сбрасываем UI
            def delayed_reset():
                time.sleep(1.5)
                reset_ui_to_stopped()
            
            threading.Thread(target=delayed_reset, daemon=True).start()

    # Кнопка запуска
    btn_start = ft.ElevatedButton(
        text="ACTIVATE",
        width=200,
        height=50,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=8),
            bgcolor="#222222",
            color="white",
        ),
        on_click=toggle_server
    )

    # --- 4. СБОРКА ЭКРАНА ---
    
    header = ft.Row(
        [
            ft.Icon(ft.icons.SHIELD_MOON, size=40, color="cyan"),
            ft.Text("Arrhythmia", size=25, weight="bold")
        ], 
        alignment=ft.MainAxisAlignment.CENTER
    )
    
    status_row = ft.Row(
        [status_indicator, status_text],
        alignment=ft.MainAxisAlignment.CENTER
    )

    # Добавляем всё на страницу
    page.add(
        ft.Column(
            [
                ft.Container(height=20),
                header,
                ft.Container(height=20),
                status_row,
                ft.Container(height=30),
                btn_start,
                ft.Container(height=30),
                ft.Text("SYSTEM LOGS:", size=12, color="grey"),
                logs_container,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER
        )
    )
    
    log("System initialized.", "grey")

# Запуск приложения
ft.app(target=main)
