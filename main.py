import flet as ft
import asyncio
import aiohttp
import struct
import random
import socket
import traceback

# ==========================================
# ⚙️ НАСТРОЙКИ (ВСТАВЬ СВОИ ДАННЫЕ)
# ==========================================
TOKEN = "GARDEN_MASTER_251184psv"  # <-- ТВОЙ ТОКЕН
SERVER_URL = "https://izba-art.ru/api/v1/sync" # <-- ТВОЙ URL
LOCAL_PORT = 1090
# ==========================================

# Глобальные переменные
RUNNING = False
TRACTOR_TASK = None
tunnel_queue = None 
streams = {}
pending_streams = {}
next_stream_id = 1

async def main(page: ft.Page):
    # --- НАСТРОЙКИ ANDROID ---
    page.platform = ft.PagePlatform.ANDROID
    page.keep_awake = True 
    page.title = "Tractor Simple"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#000000"
    page.padding = 20
    
    # Инициализация очереди
    global tunnel_queue
    tunnel_queue = asyncio.Queue()

    # --- ЛОГИ ---
    logs_column = ft.Column(scroll=ft.ScrollMode.AUTO, auto_scroll=True)
    logs_container = ft.Container(
        content=logs_column,
        expand=True,
        bgcolor="#111111",
        border=ft.border.all(1, "#333333"),
        border_radius=5,
        padding=5,
    )

    def log(msg, color="white"):
        try:
            # Просто текст, без излишеств
            logs_column.controls.append(ft.Text(f"> {msg}", color=color, size=12))
            if len(logs_column.controls) > 60: logs_column.controls.pop(0)
            page.update()
        except: pass

    # --- СЕТЕВОЕ ЯДРО (БЕЗ ИЗМЕНЕНИЙ) ---
    async def tunnel_sender(ws):
        try:
            while RUNNING:
                packet = await tunnel_queue.get()
                await ws.send_bytes(packet)
                tunnel_queue.task_done()
        except: pass

    async def heartbeat_loop(ws):
        try:
            while RUNNING:
                await asyncio.sleep(random.randint(20, 140))
                junk = random.randbytes(random.randint(10, 50))
                await ws.send_bytes(struct.pack('!IB', 0, 3) + junk)
                log("💓 Ping", "pink")
        except: pass

    async def tunnel_receiver(ws):
        try:
            async for msg in ws:
                if not RUNNING: break
                if msg.type == aiohttp.WSMsgType.BINARY:
                    if len(msg.data) < 5: continue
                    sid = struct.unpack('!I', msg.data[:4])[0]
                    cmd = msg.data[4]
                    if cmd == 0 and sid in pending_streams: pending_streams[sid].set()
                    elif cmd == 1 and sid in streams: await streams[sid].put(msg.data[5:])
                    elif cmd == 2 and sid in streams: await streams[sid].put(None)
        except: pass

    async def handle_socks_client(reader, writer):
        global next_stream_id
        sid = next_stream_id
        next_stream_id += 1
        streams[sid] = asyncio.Queue()
        pending_streams[sid] = asyncio.Event()

        try:
            await reader.read(256)
            writer.write(b"\x05\x00")
            await writer.drain()
            data = await reader.read(4096)
            if not data or len(data) < 7: return
            
            if data[3] == 1: addr = ".".join(map(str, data[4:8])); port = struct.unpack('!H', data[8:10])[0]
            elif data[3] == 3: l = data[4]; addr = data[5:5+l].decode(); port = struct.unpack('!H', data[5+l:7+l])[0]
            else: return

            log(f"🔗 {addr}:{port}", "cyan")
            await tunnel_queue.put(struct.pack('!IBB', sid, 0, len(addr)) + addr.encode() + struct.pack('!H', port))

            try: await asyncio.wait_for(pending_streams[sid].wait(), timeout=10)
            except: return

            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()

            async def r():
                try:
                    while RUNNING:
                        d = await reader.read(16384)
                        if not d: break
                        await tunnel_queue.put(struct.pack('!IB', sid, 1) + d)
                    await tunnel_queue.put(struct.pack('!IB', sid, 2))
                except: pass

            async def w():
                try:
                    while RUNNING:
                        d = await streams[sid].get()
                        if d is None: break
                        writer.write(d)
                        await writer.drain()
                except: pass

            await asyncio.gather(r(), w())
        except: pass
        finally:
            if sid in streams: del streams[sid]
            if sid in pending_streams: del pending_streams[sid]
            try: writer.close()
            except: pass

    # --- ЗАПУСК ДВИГАТЕЛЯ ---
    async def start_engine():
        global RUNNING
        server = None
        session = None
        try:
            server = await asyncio.start_server(handle_socks_client, '127.0.0.1', LOCAL_PORT)
            log(f"✅ READY: 127.0.0.1:{LOCAL_PORT}", "green")
            session = aiohttp.ClientSession()
            while RUNNING:
                try:
                    log("Connecting...", "yellow")
                    async with session.ws_connect(SERVER_URL, headers={"Authorization": TOKEN}, ssl=False) as ws:
                        log("🚀 CONNECTED!", "green")
                        tasks = [tunnel_sender(ws), tunnel_receiver(ws), heartbeat_loop(ws)]
                        await asyncio.wait([asyncio.create_task(t) for t in tasks], return_when=asyncio.FIRST_COMPLETED)
                except Exception as e:
                    if RUNNING: 
                        log(f"Error: {e}", "red")
                        await asyncio.sleep(5)
                    else: break
        finally:
            if server: server.close()
            if session: await session.close()
            log("🛑 STOPPED", "red")

    # --- КНОПКА И UI (БЕЗ ИКОНОК!) ---
    async def on_click(e):
        global RUNNING, TRACTOR_TASK
        if not RUNNING:
            RUNNING = True
            btn.text = "STOP"
            btn.bgcolor = "red"
            TRACTOR_TASK = asyncio.create_task(start_engine())
        else:
            RUNNING = False
            btn.text = "START"
            btn.bgcolor = "green"
            if TRACTOR_TASK: TRACTOR_TASK.cancel()
        page.update()

    btn = ft.ElevatedButton("START", on_click=on_click, bgcolor="green", color="white", width=200, height=60)

    # Простейшая сборка: Текст, Кнопка, Логи
    page.add(
        ft.Column([
            ft.Container(height=40),
            ft.Text("ARRHYTHMIA", size=30, weight="bold", color="white"),
            ft.Container(height=20),
            btn,
            ft.Container(height=20),
            logs_container
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    )

ft.app(target=main)
