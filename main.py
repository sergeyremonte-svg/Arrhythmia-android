import flet as ft
import sys
import threading
import time
import socket
import traceback

# Глобальные переменные
SERVER_RUNNING = False
LISTEN_PORT = 1090

def main(page: ft.Page):
    # 1. СРАЗУ РИСУЕМ НАСТРОЙКИ СТРАНИЦЫ
    page.title = "Arrhythmia Safe"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#000000"
    page.padding = 20
    page.window_width = 360
    page.window_height = 800
    page.scroll = ft.ScrollMode.AUTO

    # 2. ЭЛЕМЕНТЫ ЛОГОВ (ЧТОБЫ ВИДЕТЬ ОШИБКИ)
    logs_view = ft.Column(spacing=2)
    
    # Функция записи в лог (безопасная)
    def log(msg, color="white"):
        t = time.strftime("%H:%M:%S")
        logs_view.controls.append(ft.Text(f"[{t}] {msg}", color=color, size=12, font_family="monospace"))
        # Чистим старые логи
        if len(logs_view.controls) > 50:
            logs_view.controls.pop(0)
        page.update()

    # 3. ФУНКЦИЯ СЕРВЕРА (ВНУТРИ ЗАЩИТЫ)
    def run_server():
        global SERVER_RUNNING
        host = '127.0.0.1'
        
        log("Запуск сервера...", "yellow")
        
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, LISTEN_PORT))
            s.listen(1)
            s.settimeout(2.0)
            
            log(f"✅ УСПЕХ! Порт {LISTEN_PORT}", "green")
            
            while SERVER_RUNNING:
                try:
                    conn, addr = s.accept()
                    log(f"Соединение: {addr}", "cyan")
                    conn.close()
                except socket.timeout:
                    continue
                except Exception as e:
                    log(f"Ошибка цикла: {e}", "orange")
            
            s.close()
            log("Сервер остановлен", "red")
            
        except PermissionError:
            log("⛔ НЕТ ПРАВ НА ПОРТ!", "red")
            log("Попробуй порт > 1024", "red")
            SERVER_RUNNING = False
        except Exception as e:
            log(f"🔥 КРИТИЧЕСКАЯ ОШИБКА:\n{e}", "red")
            SERVER_RUNNING = False
        
        # Обновляем кнопку при остановке
        btn.text = "ACTIVATE"
        btn.bgcolor = "#333333"
        page.update()

    # 4. КНОПКА
    def on_click(e):
        global SERVER_RUNNING
        if not SERVER_RUNNING:
            SERVER_RUNNING = True
            btn.text = "STOP"
            btn.bgcolor = "#990000"
            page.update()
            threading.Thread(target=run_server, daemon=True).start()
        else:
            SERVER_RUNNING = False
            btn.text = "STOPPING..."
            page.update()

    btn = ft.ElevatedButton("ACTIVATE", on_click=on_click, bgcolor="#333333", color="white", width=200)

    # 5. ГЛАВНАЯ СБОРКА (ОЧЕНЬ ПРОСТАЯ)
    try:
        page.add(
            ft.Text("Arrhythmia System", size=20, weight="bold", color="blue"),
            ft.Divider(),
            btn,
            ft.Divider(),
            ft.Text("System Logs:", color="grey"),
            ft.Container(content=logs_view, height=400, border=ft.border.all(1, "#333333"), padding=10),
        )
        log("Интерфейс загружен.", "green")
        
    except Exception as e:
        page.add(ft.Text(f"UI ERROR: {e}", color="red"))

# ЗАПУСК
ft.app(target=main)
