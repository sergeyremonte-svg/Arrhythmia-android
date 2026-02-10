import flet as ft
import asyncio
import aiohttp
import struct
import random
import socket
import ssl
import os

# ==========================================
# ⚙️ НАСТРОЙКИ
# ==========================================
TOKEN = "vasy"
SERVER_IP = "45.143.94.166"
SERVER_HOST = "izba-art.ru"
SERVER_URL = f"https://{SERVER_IP}/api/v1/sync"
LOCAL_PORT = 1090
# ==========================================

streams = {}
pending_streams = {}
next_stream_id = 1

RUNNING = asyncio.Event()
tunnel_queue = asyncio.Queue()


async def main(page: ft.Page):
    page.platform = ft.PagePlatform.ANDROID
    page.keep_awake = True
    page.title = "Tractor Stable"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#000000"

    logs = ft.Column(scroll=ft.ScrollMode.AUTO, auto_scroll=True)

    def log(msg, color="white"):
        logs.controls.append(
            ft.Text(f"> {msg}", color=color, size=11, font_family="monospace")
        )
        if len(logs.controls) > 80:
            logs.controls.pop(0)
        page.update()

    # ================= SOCKS =================

    async def handle_socks_client(reader, writer):
        global next_stream_id
        sid = next_stream_id
        next_stream_id += 1

        streams[sid] = asyncio.Queue(maxsize=100)
        connected = asyncio.Event()
        pending_streams[sid] = connected

        try:
            await reader.read(256)
            writer.write(b"\x05\x00")
            await writer.drain()

            data = await reader.read(4096)
            if not data or len(data) < 7:
                return

            if data[3] == 1:
                addr = ".".join(map(str, data[4:8]))
                port = struct.unpack("!H", data[8:10])[0]
            elif data[3] == 3:
                l = data[4]
                addr = data[5:5+l].decode()
                port = struct.unpack("!H", data[5+l:7+l])[0]
            else:
                return

            log(f"🔗 {addr}:{port}", "cyan")

            packet = struct.pack("!IBB", sid, 0, len(addr)) + addr.encode() + struct.pack("!H", port)
            await tunnel_queue.put(packet)

            await asyncio.wait_for(connected.wait(), timeout=8)

            writer.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await writer.drain()

            async def tx():
                try:
                    while RUNNING.is_set():
                        d = await reader.read(16384)
                        if not d:
                            break
                        await tunnel_queue.put(struct.pack("!IB", sid, 1) + d)
                finally:
                    await tunnel_queue.put(struct.pack("!IB", sid, 2))

            async def rx():
                while RUNNING.is_set():
                    d = await streams[sid].get()
                    if d is None:
                        break
                    writer.write(d)
                    await writer.drain()

            await asyncio.gather(tx(), rx())

        except Exception as e:
            log(f"SOCKS err: {e}", "red")
        finally:
            streams.pop(sid, None)
            pending_streams.pop(sid, None)
            writer.close()

    # ================= WS =================

    async def tunnel_sender(ws):
        try:
            while RUNNING.is_set():
                packet = await tunnel_queue.get()
                await ws.send_bytes(packet)
                tunnel_queue.task_done()
        except Exception as e:
            log(f"SND err: {e}", "red")

    async def tunnel_receiver(ws):
        async for msg in ws:
            if not RUNNING.is_set():
                break
            if msg.type == aiohttp.WSMsgType.BINARY:
                sid = struct.unpack("!I", msg.data[:4])[0]
                cmd = msg.data[4]
                payload = msg.data[5:]

                if cmd == 0 and sid in pending_streams:
                    pending_streams[sid].set()
                elif cmd == 1 and sid in streams:
                    await streams[sid].put(payload)
                elif cmd == 2 and sid in streams:
                    await streams[sid].put(None)

    async def heartbeat(ws):
        try:
            while RUNNING.is_set():
                await asyncio.sleep(random.randint(20, 120))
                junk = os.urandom(random.randint(16, 64))
                await ws.send_bytes(struct.pack("!IB", 0, 3) + junk)
                log("💓 Pulse", "pink")
        except Exception as e:
            log(f"HB err: {e}", "red")

    # ================= ENGINE =================

    async def engine():
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(family=socket.AF_INET, ssl=ssl_ctx)
        timeout = aiohttp.ClientTimeout(sock_connect=10, sock_read=60)

        server = await asyncio.start_server(handle_socks_client, "127.0.0.1", LOCAL_PORT)
        log(f"✅ SOCKS 127.0.0.1:{LOCAL_PORT}", "green")

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            while RUNNING.is_set():
                try:
                    log("🔌 Connecting...", "yellow")
                    async with session.ws_connect(
                        SERVER_URL,
                        headers={
                            "Authorization": TOKEN,
                            "Host": SERVER_HOST,
                            "User-Agent": "Mozilla/5.0 Android"
                        }
                    ) as ws:
                        log("🚀 CONNECTED", "green")

                        sender = asyncio.create_task(tunnel_sender(ws))
                        receiver = asyncio.create_task(tunnel_receiver(ws))
                        hb = asyncio.create_task(heartbeat(ws))

                        await receiver
                        sender.cancel()
                        hb.cancel()

                except Exception as e:
                    log(f"WS drop: {e}", "red")
                    await asyncio.sleep(3)

        server.close()
        await server.wait_closed()

    # ================= UI =================

    async def toggle(e):
        if not RUNNING.is_set():
            RUNNING.set()
            btn.text = "STOP"
            page.update()
            asyncio.create_task(engine())
        else:
            RUNNING.clear()
            btn.text = "START"
            page.update()

    btn = ft.ElevatedButton("START", on_click=toggle)

    page.add(
        ft.Column([
            ft.Text("TRACTOR", size=20, weight="bold"),
            btn,
            logs
        ])
    )


ft.app(target=main)
