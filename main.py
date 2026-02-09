import flet as ft
import asyncio
import aiohttp
import struct
import random
import socket
import traceback

# ==========================================
# ⚙️ НАСТРОЙКИ (ВСТАВЬ СВОИ ДАННЫЕ ТУТ)
# ==========================================
TOKEN = "GARDEN_MASTER_251184psv"  # <-- ТВОЙ ТОКЕН
SERVER_URL = "https://izba-art.ru/api/v1/sync" # <-- ТВОЙ URL
LOCAL_PORT = 1090
# ==========================================

# Глобальные переменные для управления состоянием
RUNNING = False
TRACTOR_TASK = None

# Очереди и потоки (из твоего скрипта)
tunnel_queue = asyncio.Queue()
streams = {}
pending_streams = {}
next_stream_id = 1

async def main(page: ft.Page):
    # --- 1. НАСТРОЙКА ИНТЕРФЕЙСА ---
    page.title = "Tractor V2.6 Mobile"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#000000"
    page.padding = 10
    # Отключаем общий скролл страницы, скроллить будем только логи
    page.scroll = None 
    
    # Контейнер для логов
    logs_column = ft.Column(scroll=ft.ScrollMode.AUTO, auto_scroll=True)
    
    logs_container = ft.Container(
        content=logs_column,
        expand=True, # Занимает все свободное место
        bgcolor="#111111",
        border=ft.border.all(1, "#333333"),
        border_radius=10,
        padding=10,
    )

    def log(msg, color="white"):
        t = "LOG" # Можно добавить время, но на телефоне места мало
        # no_wrap=False заставляет текст переноситься, а не улетать вправо
        text_element = ft.Text(f"> {msg}", color=color, size=12, font_family="monospace", no_wrap=False, selectable=True)
        logs_column.controls.append(text_element)
        
        # Чистим старые логи (бережем память телефона)
        if len(logs_column.controls) > 100:
            logs_column.controls.pop(0)
        page.update()

    # --- 2. ЛОГИКА ТРАКТОРА (ТВОЙ КОД С ПК) ---

    async def tunnel_sender(ws):
        try:
            while RUNNING:
                packet = await tunnel_queue.get()
                await ws.send_bytes(packet)
                tunnel_queue.task_done()
        except asyncio.CancelledError: pass
        except Exception: pass

    async def heartbeat_loop(ws):
        """Задача Аритмии"""
        try:
            while RUNNING:
                sleep_time = random.randint(20, 140) # Как в твоем оригинале
                await asyncio.sleep(sleep_time)
                
                junk_size = random.randint(10, 50)
                junk = random.randbytes(junk_size)
                
                packet = struct.pack('!IB', 0, 3) + junk
                log(f"💓 Heartbeat ({junk_size}b)", "pink")
                await ws.send_bytes(packet)
        except asyncio.CancelledError: pass
        except Exception: pass

    async def tunnel_receiver(ws):
        try:
            async for msg in ws:
                if not RUNNING: break
                if msg.type == aiohttp.WSMsgType.BINARY:
                    if len(msg.data) < 5: continue
                    stream_id = struct.unpack('!I', msg.data[:4])[0]
                    cmd = msg.data[4]
                    
                    if cmd == 0:
                        if stream_id in pending_streams: pending_streams[stream_id].set()
                    elif cmd == 1:
                        if stream_id in streams: await streams[stream_id].put(msg.data[5:])
                    elif cmd == 2:
                        if stream_id in streams: await streams[stream_id].put(None)
        except Exception as e:
            pass

    async def handle_socks_client(reader, writer):
        global next_stream_id
        stream_id = next_stream_id
        next_stream_id += 1
        
        streams[stream_id] = asyncio.Queue()
        connected_event = asyncio.Event()
        pending_streams[stream_id] = connected_event

        try:
            # SOCKS5 Handshake
            await reader.read(262)
            writer.write(b"\x05\x00")
            await writer.drain()
            
            data = await reader.read(4096)
            if not data or len(data) < 7: return
            
            if data[3] == 1: 
                addr = ".".join(map(str, data[4:8]))
                port = struct.unpack('!H', data[8:10])[0]
            elif data[3] == 3: 
                l = data[4]
                addr = data[5:5+l].decode()
                port = struct.unpack('!H', data[5+l:7+l])[0]
            else: return

            log(f"🔗 Connect: {addr}:{port}", "cyan")

            packet = struct.pack('!IBB', stream_id, 0, len(addr)) + addr.encode() + struct.pack('!H', port)
            await tunnel_queue.put(packet)

            try:
                await asyncio.wait_for(connected_event.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                return

            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()

            async def local_reader():
                try:
                    while RUNNING:
                        d = await reader.read(16384)
                        if not d: break
                        await tunnel_queue.put(struct.pack('!IB', stream_id, 1) + d)
                    await tunnel_queue.put(struct.pack('!IB', stream_id, 2))
                except: pass

            async def local_writer():
                try:
                    while RUNNING:
                        d = await streams[stream_id].get()
                        if d is None: break
                        writer.write(d)
                        await writer.drain()
                except: pass

            await asyncio.gather(local_reader(), local_writer())

        except Exception as e:
            pass
        finally:
            if stream_id in streams: del streams[stream_id]
            if stream_id in pending_streams: del pending_streams[stream_id]
            try: writer.close()
            except: pass

    # --- 3. ГЛАВНЫЙ ЦИКЛ ЗАПУСКА ---
    async def start_engine():
        global RUNNING
        server = None
        session = None
        
        try:
            # Запускаем локальный SOCKS сервер
            server = await asyncio.start_server(handle_socks_client, '127.0.0.1', LOCAL_PORT)
            log(f"🚜 TRACTOR STARTED on port {LOCAL_PORT}", "green")
            
            session = aiohttp.ClientSession()
            
            while RUNNING:
                try:
                    log(f"Connecting to {SERVER_URL}...", "yellow")
                    async with session.ws_connect(SERVER_URL, headers={"Authorization": TOKEN}, ssl=False) as ws:
                        log("✅ Tunnel ESTABLISHED!", "green")
                        log("Включай Telegram Proxy: 127.0.0.1:1090", "green")
                        
                        sender = asyncio.create_task(tunnel_sender(ws))
                        receiver = asyncio.create_task(tunnel_receiver(ws))
                        heart = asyncio.create_task(heartbeat_loop(ws))
                        
                        # Ждем, пока одна из задач не упадет или не будет отменена
                        await asyncio.wait(
                            [sender, receiver, heart], 
                            return_when=asyncio.FIRST_COMPLETED
                        )
                        
                        # Если вылетели - отменяем остальные
                        for task in [sender, receiver, heart]:
                            if not task.done(): task.cancel()
                            
                except Exception as e:
                    if RUNNING:
                        log(f"Connection lost: {e}", "red")
                        log("Retry in 5s...", "grey")
                        await asyncio.sleep(5)
                    else:
                        break # Если нажали стоп - выходим
                        
        except Exception as e:
            log(f"Critical Error: {e}", "red")
        finally:
            if server: server.close()
            if session: await session.close()
            log("🛑 Engine Stopped.", "red")

    # --- 4. УПРАВЛЕНИЕ КНОПКОЙ ---
    async def on_click(e):
        global RUNNING, TRACTOR_TASK
        
        if not RUNNING:
            # ЗАПУСК
            RUNNING = True
            btn.text = "STOP SYSTEM"
            btn.bgcolor = "#990000"
            page.update()
            # Запускаем Engine как задачу asyncio
            TRACTOR_TASK = asyncio.create_task(start_engine())
        else:
            # ОСТАНОВКА
            RUNNING = False
            btn.text = "STOPPING..."
            btn.disabled = True
            page.update()
            
            if TRACTOR_TASK:
                TRACTOR_TASK.cancel()
                try:
                    await TRACTOR_TASK
                except asyncio.CancelledError:
                    pass
            
            btn.text = "ACTIVATE"
            btn.bgcolor = "#222222"
            btn.disabled = False
            page.update()

    # --- 5. СБОРКА UI ---
    btn = ft.ElevatedButton(
        "ACTIVATE", 
        on_click=on_click, 
        bgcolor="#222222", 
        color="white", 
        width=200, 
        height=50
    )

    page.add(
        ft.Column(
            [
                ft.Container(height=20),
                ft.Icon(ft.icons.SHIELD_MOON, size=60, color="cyan"),
                ft.Text("Arrhythmia V2.6", size=20, weight="bold"),
                ft.Container(height=20),
                btn,
                ft.Container(height=20),
                ft.Text("SYSTEM LOGS:", color="grey"),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER
        ),
        logs_container # Логи занимают все оставшееся место
    )

# Запускаем как async приложение
ft.app(target=main)
