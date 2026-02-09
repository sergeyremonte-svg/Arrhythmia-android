import flet as ft
import asyncio
import aiohttp
import struct
import random
import socket
import traceback

# ==========================================
# ⚙️ НАСТРОЙКИ СЕТИ (ВСТАВЬ СВОИ ДАННЫЕ)
# ==========================================
TOKEN = "11111"  # <-- ТВОЙ ТОКЕН
SERVER_URL = "https://izba-art.ru/api/v1/sync" # <-- ТВОЙ URL
LOCAL_PORT = 1090
# ==========================================

# Глобальные переменные состояния
RUNNING = False
TRACTOR_TASK = None

# Словари для потоков (как в твоем ПК скрипте)
streams = {}
pending_streams = {}
next_stream_id = 1
tunnel_queue = None # Будет создан внутри main

async def main(page: ft.Page):
    # --- 0. НАСТРОЙКА ANDROID ---
    # Важно! Запрещаем телефону уходить в глубокий сон, пока приложение открыто
    page.platform = ft.PagePlatform.ANDROID
    page.keep_awake = True 
    
    # --- 1. ВИЗУАЛ (БЕЗОПАСНЫЙ СТАРТ) ---
    page.title = "Tractor Ultimate"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#000000"
    page.padding = 10
    page.scroll = None 
    
    # Инициализация очереди сообщений (строго внутри loop)
    global tunnel_queue
    tunnel_queue = asyncio.Queue()

    # Логгер
    logs_column = ft.Column(scroll=ft.ScrollMode.AUTO, auto_scroll=True)
    logs_container = ft.Container(
        content=logs_column,
        expand=True,
        bgcolor="#0a0a0a",
        border=ft.border.all(1, "#333333"),
        border_radius=8,
        padding=10,
    )

    def log(msg, color="white"):
        # Логируем безопасно для UI
        try:
            text = ft.Text(f"> {msg}", color=color, size=11, font_family="monospace", no_wrap=False, selectable=True)
            logs_column.controls.append(text)
            if len(logs_column.controls) > 80: # Чистим память
                logs_column.controls.pop(0)
            page.update()
        except: pass

    # --- 2. ЯДРО ТРАКТОРА (ТВОЙ PROTOCOL) ---

    async def tunnel_sender(ws):
        """Отправка данных из очереди в WebSocket"""
        try:
            while RUNNING:
                packet = await tunnel_queue.get()
                await ws.send_bytes(packet)
                tunnel_queue.task_done()
        except asyncio.CancelledError: pass
        except Exception as e: log(f"Sender Error: {e}", "red")

    async def heartbeat_loop(ws):
        """Аритмия: шлет мусор, чтобы держать канал"""
        try:
            while RUNNING:
                sleep_time = random.randint(20, 140)
                await asyncio.sleep(sleep_time)
                
                junk_size = random.randint(10, 50)
                junk = random.randbytes(junk_size)
                
                # Пакет Heartbeat [ID=0, CMD=3]
                packet = struct.pack('!IB', 0, 3) + junk
                log(f"💓 Pulse ({junk_size}b)", "pink")
                await ws.send_bytes(packet)
        except asyncio.CancelledError: pass
        except Exception: pass

    async def tunnel_receiver(ws):
        """Прием данных из WebSocket"""
        try:
            async for msg in ws:
                if not RUNNING: break
                if msg.type == aiohttp.WSMsgType.BINARY:
                    if len(msg.data) < 5: continue
                    # Распаковка заголовка
                    stream_id = struct.unpack('!I', msg.data[:4])[0]
                    cmd = msg.data[4]
                    
                    if cmd == 0:   # Connected
                        if stream_id in pending_streams: pending_streams[stream_id].set()
                    elif cmd == 1: # Data
                        if stream_id in streams: await streams[stream_id].put(msg.data[5:])
                    elif cmd == 2: # Closed
                        if stream_id in streams: await streams[stream_id].put(None)
        except Exception as e:
            log(f"Receiver Error: {e}", "red")

    async def handle_socks_client(reader, writer):
        """Обработка подключения Telegram (SOCKS5)"""
        global next_stream_id
        stream_id = next_stream_id
        next_stream_id += 1
        
        streams[stream_id] = asyncio.Queue()
        connected_event = asyncio.Event()
        pending_streams[stream_id] = connected_event

        peer = writer.get_extra_info('peername')
        
        try:
            # 1. SOCKS5 Auth Handshake
            # Читаем приветствие (версия + методы)
            await reader.read(256) 
            # Отвечаем: Версия 5, Метод 0 (No Auth)
            writer.write(b"\x05\x00")
            await writer.drain()
            
            # 2. SOCKS5 Request
            data = await reader.read(4096)
            if not data or len(data) < 7: return
            
            # Парсим адрес назначения
            if data[3] == 1: # IPv4
                addr = ".".join(map(str, data[4:8]))
                port = struct.unpack('!H', data[8:10])[0]
            elif data[3] == 3: # Domain
                l = data[4]
                addr = data[5:5+l].decode()
                port = struct.unpack('!H', data[5+l:7+l])[0]
            else: return # IPv6 не поддерживаем пока

            log(f"🔗 Telegram -> {addr}:{port}", "cyan")

            # Шлем команду "Connect" в туннель
            packet = struct.pack('!IBB', stream_id, 0, len(addr)) + addr.encode() + struct.pack('!H', port)
            await tunnel_queue.put(packet)

            # Ждем подтверждения от сервера
            try:
                await asyncio.wait_for(connected_event.wait(), timeout=8.0)
            except asyncio.TimeoutError:
                log(f"timeout {stream_id}", "red")
                return

            # Отвечаем Telegram'у: "Всё ок, соединение установлено"
            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()

            # 3. Пересылка данных (Duplex)
            async def telegram_reader():
                try:
                    while RUNNING:
                        d = await reader.read(16384)
                        if not d: break
                        # Упаковка данных [ID, CMD=1, DATA]
                        await tunnel_queue.put(struct.pack('!IB', stream_id, 1) + d)
                    # Команда закрытия [ID, CMD=2]
                    await tunnel_queue.put(struct.pack('!IB', stream_id, 2))
                except: pass

            async def telegram_writer():
                try:
                    while RUNNING:
                        d = await streams[stream_id].get()
                        if d is None: break
                        writer.write(d)
                        await writer.drain()
                except: pass

            await asyncio.gather(telegram_reader(), telegram_writer())

        except Exception:
            pass
        finally:
            # Уборка мусора
            if stream_id in streams: del streams[stream_id]
            if stream_id in pending_streams: del pending_streams[stream_id]
            try: writer.close()
            except: pass

    # --- 3. ГЛАВНЫЙ ЦИКЛ (ENGINE) ---
    
    async def start_engine():
        global RUNNING
        server = None
        session = None
        
        try:
            # Запускаем локальный SOCKS сервер
            server = await asyncio.start_server(handle_socks_client, '127.0.0.1', LOCAL_PORT)
            log(f"🚜 TRACTOR ACTIVE: 127.0.0.1:{LOCAL_PORT}", "green")
            
            session = aiohttp.ClientSession()
            
            while RUNNING:
                try:
                    log(f"Connecting to Cloud...", "yellow")
                    # Подключение к WebSocket
                    async with session.ws_connect(SERVER_URL, headers={"Authorization": TOKEN}, ssl=False) as ws:
                        log("✅ CLOUD CONNECTED!", "green")
                        
                        # Запускаем задачи обслуживания туннеля
                        sender = asyncio.create_task(tunnel_sender(ws))
                        receiver = asyncio.create_task(tunnel_receiver(ws))
                        heart = asyncio.create_task(heartbeat_loop(ws))
                        
                        await asyncio.wait(
                            [sender, receiver, heart], 
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        
                        for t in [sender, receiver, heart]:
                            if not t.done(): t.cancel()
                                
                except Exception as e:
                    if RUNNING:
                        log(f"Link Error: {e}. Retry...", "red")
                        await asyncio.sleep(5)
                    else: break
                        
        except Exception as e:
            log(f"CRITICAL: {e}", "red")
        finally:
            if server: server.close()
            if session: await session.close()
            log("🛑 ENGINE STOPPED", "red")

    # --- 4. КНОПКА И ИНТЕРФЕЙС ---

    async def on_click(e):
        global RUNNING, TRACTOR_TASK
        if not RUNNING:
            RUNNING = True
            btn.text = "STOP SYSTEM"
            btn.bgcolor = "#880000"
            page.update()
            TRACTOR_TASK = asyncio.create_task(start_engine())
        else:
            RUNNING = False
            btn.text = "STOPPING..."
            btn.disabled = True
            page.update()
            
            if TRACTOR_TASK:
                TRACTOR_TASK.cancel()
                try: await TRACTOR_TASK
                except: pass
            
            btn.text = "ACTIVATE"
            btn.bgcolor = "#222222"
            btn.disabled = False
            page.update()

    btn = ft.ElevatedButton("ACTIVATE", on_click=on_click, bgcolor="#222222", color="white", width=200, height=50)

    # Заголовок и сборка
    try:
        page.add(
            ft.Column([
                ft.Container(height=30),
                ft.Row([
                    ft.Icon(ft.icons.SHIELD_SHARP, size=40, color="cyan"),
                    ft.Text("ARRHYTHMIA", size=20, weight="bold", font_family="monospace"),
                ], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(height=20),
                btn,
                ft.Container(height=20),
                ft.Text("UPLINK STATUS:", color="grey", size=10),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            logs_container
        )
    except Exception as e:
        page.add(ft.Text(f"UI BUILD ERROR: {e}", color="red"))

# Запускаем через Flet (он сам создаст Loop)
ft.app(target=main)
