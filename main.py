import flet as ft
import asyncio
import aiohttp
import struct
import random
import socket
import ssl 

# ==========================================
# ⚙️ НАСТРОЙКИ (DIRECT IP MODE)
# ==========================================
TOKEN = "GARDEN_MASTER_251184psv"

# ВАЖНО: Мы идем по ПРЯМОМУ IP, чтобы исключить ошибку DNS
# Я взял этот IP из твоих прошлых логов (45.143.94.166)
SERVER_IP = "45.143.94.166" 
SERVER_HOST = "izba-art.ru"

# Ссылка теперь строится на IP
SERVER_URL = f"https://{SERVER_IP}/api/v1/sync"
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
    # --- 0. НАСТРОЙКА ANDROID ---
    page.platform = ft.PagePlatform.ANDROID
    page.keep_awake = True 
    
    # --- 1. ВИЗУАЛ (НИКАКИХ ИКОНОК - ТОЛЬКО ТЕКСТ) ---
    page.title = "Tractor Direct"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#000000"
    page.padding = 10
    page.scroll = None 
    
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
        try:
            text = ft.Text(f"> {msg}", color=color, size=11, font_family="monospace", no_wrap=False, selectable=True)
            logs_column.controls.append(text)
            if len(logs_column.controls) > 60:
                logs_column.controls.pop(0)
            page.update()
        except: pass

    # --- 2. ЯДРО ТРАКТОРА ---

    async def tunnel_sender(ws):
        try:
            while RUNNING:
                packet = await tunnel_queue.get()
                await ws.send_bytes(packet)
                tunnel_queue.task_done()
        except asyncio.CancelledError: pass
        except Exception as e: pass

    async def heartbeat_loop(ws):
        try:
            while RUNNING:
                # Агрессивный пинг (10-20 сек), чтобы связь не рвалась
                sleep_time = random.randint(10, 20)
                await asyncio.sleep(sleep_time)
                junk = random.randbytes(random.randint(10, 50))
                packet = struct.pack('!IB', 0, 3) + junk
                log(f"💓 Pulse", "pink")
                await ws.send_bytes(packet)
        except asyncio.CancelledError: pass
        except Exception: pass

    async def tunnel_receiver(ws):
        try:
            async for msg in ws:
                if not RUNNING: break
                if msg.type == aiohttp.WSMsgType.BINARY:
                    if len(msg.data) < 5: continue
                    sid = struct.unpack('!I', msg.data[:4])[0]
                    cmd = msg.data[4]
                    if cmd == 0:   
                        if sid in pending_streams: pending_streams[sid].set()
                    elif cmd == 1: 
                        if sid in streams: await streams[sid].put(msg.data[5:])
                    elif cmd == 2: 
                        if sid in streams: await streams[sid].put(None)
        except Exception as e:
            log(f"RX Error: {e}", "red")

    async def handle_socks_client(reader, writer):
        global next_stream_id
        sid = next_stream_id
        next_stream_id += 1
        
        streams[sid] = asyncio.Queue()
        connected_event = asyncio.Event()
        pending_streams[sid] = connected_event

        try:
            await reader.read(256) 
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

            log(f"🔗 {addr}:{port}", "cyan")
            packet = struct.pack('!IBB', sid, 0, len(addr)) + addr.encode() + struct.pack('!H', port)
            await tunnel_queue.put(packet)

            try: await asyncio.wait_for(connected_event.wait(), timeout=8.0)
            except asyncio.TimeoutError: return

            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()

            async def tx():
                try:
                    while RUNNING:
                        d = await reader.read(16384)
                        if not d: break
                        await tunnel_queue.put(struct.pack('!IB', sid, 1) + d)
                    await tunnel_queue.put(struct.pack('!IB', sid, 2))
                except: pass

            async def rx():
                try:
                    while RUNNING:
                        d = await streams[sid].get()
                        if d is None: break
                        writer.write(d)
                        await writer.drain()
                except: pass

            await asyncio.gather(tx(), rx())
        except Exception: pass
        finally:
            if sid in streams: del streams[sid]
            if sid in pending_streams: del pending_streams[sid]
            try: writer.close()
            except: pass

    # --- 3. ЗАПУСК (РЕЖИМ ПРЯМОГО IP) ---
    
    async def start_engine():
        global RUNNING
        server = None
        session = None
        
        try:
            server = await asyncio.start_server(handle_socks_client, '127.0.0.1', LOCAL_PORT)
            log(f"✅ READY: 127.0.0.1:{LOCAL_PORT}", "green")
            
            # --- ВЗЛОМ DNS И SSL ---
            # Мы соединяемся с IP, но сертификат выписан на Домен.
            # check_hostname = False -> Не сверять IP с сертификатом.
            # verify_mode = CERT_NONE -> Игнорировать ошибки (максимальная пробиваемость).
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            # Строго IPv4
            connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=ssl_context)
            
            # Игнор прокси телефона (trust_env=False)
            timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10)
            session = aiohttp.ClientSession(connector=connector, trust_env=False, timeout=timeout)
            
            while RUNNING:
                try:
                    log(f"Direct link to {SERVER_IP}...", "yellow")
                    
                    # --- МАСКИРОВКА ---
                    # Host: SERVER_HOST -> Говорим серверу "Мы пришли на izba-art.ru"
                    # User-Agent -> Говорим "Мы Хром"
                    headers = {
                        "Authorization": TOKEN,
                        "Host": SERVER_HOST,
                        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
                        "Upgrade": "websocket",
                        "Connection": "Upgrade"
                    }
                    
                    async with session.ws_connect(SERVER_URL, headers=headers) as ws:
                        log("🚀 DIRECT LINK ESTABLISHED!", "green")
                        
                        tasks = [tunnel_sender(ws), tunnel_receiver(ws), heartbeat_loop(ws)]
                        await asyncio.wait([asyncio.create_task(t) for t in tasks], return_when=asyncio.FIRST_COMPLETED)
                        for t in tasks: 
                             if not t.done(): t.cancel()
                                
                except Exception as e:
                    if RUNNING:
                        log(f"Drop: {e}", "red")
                        await asyncio.sleep(3)
                    else: break
        finally:
            if server: server.close()
            if session: await session.close()
            log("🛑 STOPPED", "red")

    # --- 4. ИНТЕРФЕЙС ---

    async def on_click(e):
        global RUNNING, TRACTOR_TASK
        if not RUNNING:
            RUNNING = True
            btn.text = "STOP"
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
            btn.text = "START"
            btn.bgcolor = "#222222"
            btn.disabled = False
            page.update()

    btn = ft.ElevatedButton("START", on_click=on_click, bgcolor="#222222", color="white", width=200, height=50)

    page.add(
        ft.Column([
            ft.Container(height=30),
            ft.Text("ARRHYTHMIA", size=20, weight="bold", font_family="monospace"),
            ft.Container(height=20),
            btn,
            ft.Container(height=20),
            logs_container
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)
    )

ft.app(target=main)
