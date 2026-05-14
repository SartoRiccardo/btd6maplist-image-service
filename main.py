import hashlib
import os
import io
import http
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import Response
from PIL import Image, ImageFont, ImageDraw

BANNER_SIZE = (1536, 192)
MEDAL_SIZE = 128
MEDAL_SLOTS = 8
TEXT_POS_REL = (-10, -10)
LUCKIEST_GUY = ImageFont.truetype(os.path.join(os.getcwd(), "bin", "LuckiestGuy-Regular.ttf"), 60)

CACHE_DIR = "/tmp/btd6_banners"
CACHE_MAX = 256

_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    _http_client = httpx.AsyncClient()
    os.makedirs(CACHE_DIR, exist_ok=True)
    yield
    await _http_client.aclose()


app = FastAPI(lifespan=lifespan)


def _evict_cache():
    entries = sorted(
        (os.path.getmtime(p), p)
        for f in os.listdir(CACHE_DIR)
        if os.path.isfile(p := os.path.join(CACHE_DIR, f))
    )
    for _, path in entries[: max(0, len(entries) - CACHE_MAX)]:
        os.remove(path)


@app.get("/banner")
async def get_banner(
    banner: str = Query(...),
    wins: int = Query(0),
    black_border: int = Query(0),
    no_geraldo: int = Query(0),
    lccs: int = Query(0),
) -> Response:
    cache_path = os.path.join(CACHE_DIR, hashlib.md5(banner.encode()).hexdigest())
    if os.path.exists(cache_path):
        image_bytes = open(cache_path, "rb").read()
    else:
        resp = await _http_client.get(banner)
        if resp.status_code != http.HTTPStatus.OK:
            return Response(status_code=http.HTTPStatus.BAD_REQUEST)
        image_bytes = resp.content
        open(cache_path, "wb").write(image_bytes)
        _evict_cache()

    medals = {"wins": wins, "black_border": black_border, "no_geraldo": no_geraldo, "lccs": lccs}
    image = generate_image(io.BytesIO(image_bytes), medals)

    return Response(content=image.getvalue(), media_type="image/png")


def generate_image(banner: io.BytesIO, medals: dict) -> io.BytesIO:
    unused_space = BANNER_SIZE[0] - MEDAL_SIZE * MEDAL_SLOTS
    padding = unused_space // (MEDAL_SLOTS + 1)

    base_img = Image.open(banner).convert("RGB")
    width, _ = base_img.size
    if width != BANNER_SIZE[0]:
        base_img = base_img.resize(BANNER_SIZE)
    canvas = ImageDraw.Draw(base_img)

    medal_x = padding
    medal_y = (BANNER_SIZE[1] - MEDAL_SIZE) // 2
    for key, count in medals.items():
        if count <= 0:
            continue
        medal_img = Image.open(os.path.join(os.getcwd(), "bin", "img", f"medal_{key}.png")).convert("RGBA")
        base_img.paste(medal_img, (medal_x, medal_y), mask=medal_img)
        canvas.text(
            (medal_x + MEDAL_SIZE + TEXT_POS_REL[0], medal_y + MEDAL_SIZE + TEXT_POS_REL[1]),
            str(count),
            font=LUCKIEST_GUY,
            fill=(255, 255, 255),
            stroke_fill=(0, 0, 0),
            stroke_width=6,
            anchor="mm",
        )
        medal_x += padding + MEDAL_SIZE

    stream = io.BytesIO()
    base_img.save(stream, format="PNG")
    return stream
