import flet as ft
import asyncio
import aiohttp
import struct
import random
import socket

# ==========================================
# 🔧 КОНФИГУРАЦИЯ (БОЕВОЙ РЕЖИМ V2.6)
# ==========================================
TOKEN = "GARDEN_MASTER_251184psv"  # <--- ТВОЙ НОВЫЙ ПАРОЛЬ
SERVER_URL = "https://izba-art.ru/api/v1/sync"
LOCAL_PORT = 1090
APP_NAME = "Arrhythmia"
# ==========================================

# Глобальные переменные состояния
is_running = False
main_task = None
tunnel_queue = asyncio.Queue()
streams = {}
pending_streams = {}
next_stream_id = 1

# --- ЛОГИКА ТРАКТОРА (СЕТЕВАЯ ЧАСТЬ) ---

async def tunnel_sender(ws):
    """Отправляет пакеты из очереди в вебсокет"""
    while is_running:
        try:
            packet = await tunnel_queue.get()
            await ws.send_bytes(packet)
            tunnel_queue.task_done()
        except: break

async def heartbeat_loop(ws, log_func):
    """Аритмия: агрессивный пульс для мобильных сетей (3-15 сек)"""
    try:
        while is_running:
            sleep_time = random.randint(3, 15) # Мобильный режим
            await asyncio.sleep(sleep_time)
            junk_size = random.randint(10, 40)
            junk = random.randbytes(junk_size)
            # CMD=3 (Heartbeat)
            await ws.send_bytes(struct.pack('!IB', 0, 3) + junk)
            # log_func(f"💓 Thump... ({junk_size}b)", "grey") # Раскомментируй для отладки
    except: pass

async def tunnel_receiver(ws):
    """Читает данные из туннеля и раскидывает по потокам"""
    async for msg in ws:
        if not is_running: break
        if msg.type == aiohttp.WSMsgType.BINARY:
            try:
                if len(msg.data) < 5: continue
                stream_id = struct.unpack('!I', msg.data[:4])[0]
                cmd = msg.data[4]
                if cmd == 0 and stream_id in pending_streams:
                    pending_streams[stream_id].set()
                elif cmd == 1 and stream_id in streams:
                    await streams[stream_id].put(msg.data[5:])
                elif cmd == 2 and stream_id in streams:
                    await streams[stream_id].put(None)
            except: pass

async def handle_socks_client(reader, writer):
    """Обрабатывает входящие SOCKS5 соединения от приложений телефона"""
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
        
        # Парсим адрес назначения
        if data[3] == 1: # IPv4
            addr = socket.inet_ntop(socket.AF_INET, data[4:8])
            port = struct.unpack('!H', data[8:10])[0]
        elif data[3] == 3: # Domain
            l = data[4]
            addr = data[5:5+l].decode()
            port = struct.unpack('!H', data[5+l:7+l])[0]
        else: return

        # Шлем команду CONNECT (CMD=0) в туннель
        addr_bytes = addr.encode()
        packet = struct.pack('!IBB', stream_id, 0, len(addr_bytes)) + addr_bytes + struct.pack('!H', port)
        await tunnel_queue.put(packet)

        # Ждем подтверждения от сервера (таймаут 10с)
        try: await asyncio.wait_for(connected_event.wait(), timeout=10.0)
        except: return

        # Отвечаем клиенту, что все ОК
        writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await writer.drain()

        # Перекачка данных (Reader -> Tunnel, Tunnel -> Writer)
        async def local_reader():
            try:
                while is_running:
                    d = await reader.read(16384)
                    if not d: break
                    await tunnel_queue.put(struct.pack('!IB', stream_id, 1) + d)
            except: pass
            finally: await tunnel_queue.put(struct.pack('!IB', stream_id, 2))

        async def local_writer():
            try:
                while is_running:
                    d = await streams[stream_id].get()
                    if d is None: break
                    writer.write(d)
                    await writer.drain()
            except: pass

        await asyncio.gather(local_reader(), local_writer())

    except: pass
    finally:
        if stream_id in streams: del streams[stream_id]
        if stream_id in pending_streams: del pending_streams[stream_id]
        try: writer.close(); await writer.wait_closed()
        except: pass

# --- ГРАФИЧЕСКИЙ ИНТЕРФЕЙС (GUI) ---

async def main(page: ft.Page):
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#121212"
    page.padding = 20
    page.vertical_alignment = ft.MainAxisAlignment.START

    # Элементы UI
    status_indicator = ft.Container(width=15, height=15, bgcolor="red", border_radius=50, animate=ft.animation.Animation(300, ft.AnimationCurve.EASE_IN_OUT))
    status_text = ft.Text("DISCONNECTED", color="red", weight="bold", size=16)
    
    log_view = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=2)
    log_container = ft.Container(
        content=log_view,
        bgcolor="#1E1E1E",
        border_radius=10,
        padding=10,
        expand=True,
        border=ft.border.all(1, "#333333")
    )

    def add_log(msg, color="white"):
        log_view.controls.append(ft.Text(f"> {msg}", color=color, font_family="Roboto Mono", size=11))
        if len(log_view.controls) > 100: log_view.controls.pop(0) # Чистим старые логи
        page.update()

    def set_status(state):
        if state == "ON":
            status_indicator.bgcolor = "#00FF00" # Ярко-зеленый
            status_text.value = "SYSTEM ACTIVE"
            status_text.color = "#00FF00"
            btn.text = "STOP SYSTEM"
            btn.bgcolor = "#FF3333" # Красный
        elif state == "OFF":
            status_indicator.bgcolor = "#FF0000"
            status_text.value = "DISCONNECTED"
            status_text.color = "#FF0000"
            btn.text = "ACTIVATE"
            btn.bgcolor = "#00AA00" # Зеленый
        elif state == "CONNECTING":
             status_indicator.bgcolor = "yellow"
             status_text.value = "CONNECTING..."
             status_text.color = "yellow"
        page.update()

    async def tractor_engine():
        global is_running, tunnel_queue, streams, pending_streams, next_stream_id
        add_log(f"🚀 Initializing {APP_NAME} V2.6...", "cyan")
        
        # Сброс состояний
        tunnel_queue = asyncio.Queue()
        streams = {}
        pending_streams = {}
        
        # Старт локального SOCKS сервера
        server = await asyncio.start_server(handle_socks_client, '127.0.0.1', LOCAL_PORT)
        add_log(f"SOCKS5 Proxy listening: 127.0.0.1:{LOCAL_PORT}", "cyan")

        session = None
        while is_running:
            try:
                set_status("CONNECTING")
                add_log(f"Dialing secure uplink: {SERVER_URL}...", "blue")
                session = aiohttp.ClientSession()
                # ВАЖНО: ssl=True для HTTPS
                async with session.ws_connect(SERVER_URL, headers={"Authorization": TOKEN}, ssl=True) as ws:
                    add_log("🔒 TUNNEL ESTABLISHED. Link stable.", "green")
                    set_status("ON")
                    
                    # Запускаем задачи
                    sender_task = asyncio.create_task(tunnel_sender(ws))
                    receiver_task = asyncio.create_task(tunnel_receiver(ws))
                    heartbeat_task = asyncio.create_task(heartbeat_loop(ws, add_log))
                    
                    # Ждем, пока что-то не прервется
                    await asyncio.wait(
                        [sender_task, receiver_task], 
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Чистка задач при разрыве
                    for task in [sender_task, receiver_task, heartbeat_task]:
                         if not task.done(): task.cancel()

                    add_log("⚠️ Connection drop detected.", "orange")

            except Exception as e:
                add_log(f"Connection Error: {str(e)}", "red")
                set_status("CONNECTING")
                await asyncio.sleep(5) # Пауза перед реконнектом
            finally:
                if session: await session.close()
        
        # Остановка сервера при выключении
        server.close()
        await server.wait_closed()
        set_status("OFF")
        add_log("🛑 System Shutdown complete.", "red")

    async def toggle_btn(e):
        global is_running, main_task
        if not is_running:
            is_running = True
            btn.disabled = True # Блокируем кнопку на момент старта
            page.update()
            main_task = asyncio.create_task(tractor_engine())
            btn.disabled = False
        else:
            is_running = False
            btn.text = "STOPPING..."
            btn.disabled = True
            page.update()
            if main_task: await main_task
            btn.disabled = False
        page.update()

    # Сборка интерфейса
    btn = ft.ElevatedButton(
        text="ACTIVATE",
        bgcolor="#00AA00",
        color="white",
        height=60,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10)),
        on_click=toggle_btn
    )

    header = ft.Row(
        [ft.Icon(ft.icons.HEALTH_AND_SAFETY, color="#00FF00", size=30), 
         ft.Text(APP_NAME, size=28, weight="bold", font_family="Roboto")],
        alignment=ft.MainAxisAlignment.CENTER
    )
    
    status_bar = ft.Container(
        content=ft.Row([status_indicator, status_text], alignment=ft.MainAxisAlignment.CENTER),
        padding=10,
        bgcolor="#1E1E1E",
        border_radius=10
    )

    page.add(
        ft.SafeArea(
            ft.Column([
                header,
                ft.Divider(color="#333333"),
                status_bar,
                ft.Container(height=10),
                ft.Container(content=btn, alignment=ft.alignment.center),
                ft.Container(height=10),
                ft.Text("EVENT LOG:", size=12, color="grey"),
                log_container
            ], expand=True)
        )
    )

ft.app(target=main)