"""Trim transparent margins from the model renders and save web-sized product images."""
import os

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "_work", "renders")
OUT = os.path.join(ROOT, "images", "products")
MAX = 900
PAD = 0.06

os.makedirs(OUT, exist_ok=True)
for name in sorted(os.listdir(SRC)):
    if not name.endswith(".png"):
        continue
    img = Image.open(os.path.join(SRC, name)).convert("RGBA")
    alpha = img.getchannel("A").point(lambda a: 255 if a > 8 else 0)
    box = alpha.getbbox()
    img = img.crop(box)
    pad = int(max(img.size) * PAD)
    canvas = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad), (0, 0, 0, 0))
    canvas.paste(img, (pad, pad))
    canvas.thumbnail((MAX, MAX), Image.LANCZOS)
    dest = os.path.join(OUT, name.replace(".png", ".webp"))
    canvas.save(dest, "WEBP", quality=86, method=6)
    print(f"{os.path.basename(dest)}: {canvas.width}x{canvas.height}, {os.path.getsize(dest) // 1024} KB")
