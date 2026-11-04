import os
import io
import uuid
import asyncio
import logging

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile

from PIL import Image, ImageOps, ImageDraw, ImageFont

logging.basicConfig(level=logging.INFO)

API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise SystemExit("BOT_TOKEN is not set")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

MAX_DIM = 4096
STORE = {}

TEXT = (
    "\U0001F5BC Привет! Пришли картинку — конвертирую её прямо в чате.\n\n"
    "• Форматы: PNG / JPG / WEBP\n"
    "• Ч/Б, прозрачный фон, водяной знак\n"
    "• Ресайз, кроп 1:1 и кроп по координатам\n"
    "• Сжатие до целевого веса (в КБ)\n"
    "• Превью перед сохранением\n\n"
    "Пришли изображение — дальше всё делаешь кнопками."
)


def menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F5BC PNG", callback_data="fmt:PNG"),
         InlineKeyboardButton(text="\U0001F4F7 JPG", callback_data="fmt:JPG"),
         InlineKeyboardButton(text="\U0001F5C2 WEBP", callback_data="fmt:WEBP")],
        [InlineKeyboardButton(text="⬛ Ч/Б", callback_data="fx:gray"),
         InlineKeyboardButton(text="\U0001F52D Прозрачный фон", callback_data="fx:bg"),
         InlineKeyboardButton(text="\U0001F5A5 Водяной знак", callback_data="fx:wm")],
        [InlineKeyboardButton(text="\U0001F5D1 Ресайз", callback_data="fx:resize"),
         InlineKeyboardButton(text="\U0001F9A4 Кроп 1:1", callback_data="fx:crop11"),
         InlineKeyboardButton(text="\U0001F9A4 Кроп по точкам", callback_data="fx:croppt")],
        [InlineKeyboardButton(text="\U0001F4CF Сжать до КБ", callback_data="fx:compress"),
         InlineKeyboardButton(text="\U0001F50D Качество", callback_data="fx:quality"),
         InlineKeyboardButton(text="\U0001F504 Сброс", callback_data="reset")],
    ])


def preview_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001F7CE Сохранить", callback_data="do:save"),
         InlineKeyboardButton(text="\U0001F504 Ещё раз", callback_data="do:again")],
        [InlineKeyboardButton(text="\U0001F5BC PNG", callback_data="fmt:PNG"),
         InlineKeyboardButton(text="\U0001F4F7 JPG", callback_data="fmt:JPG"),
         InlineKeyboardButton(text="\U0001F5C2 WEBP", callback_data="fmt:WEBP")],
    ])


def quality_kb(cur):
    rows = []
    for q in (50, 70, 85, 95, 100):
        mark = " \u2713" if q == cur else ""
        rows.append([InlineKeyboardButton(text=f"{q}%{mark}", callback_data=f"q:{q}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def default_params():
    return {"fmt": None, "gray": False, "bg": False, "wm": False, "resize": None,
            "crop": None, "croppts": None, "compress_kb": None, "quality": 92}


def store(uid, data):
    key = str(uuid.uuid4())[:8]
    STORE.setdefault(uid, {})[key] = {"bytes": data, "params": default_params()}
    return key


def cur_key(uid):
    keys = list(STORE.get(uid, {}).keys())
    return keys[-1] if keys else None


def load_img(rec):
    img = Image.open(io.BytesIO(rec["bytes"]))
    img.load()
    if max(img.size) > MAX_DIM:
        img.thumbnail((MAX_DIM, MAX_DIM))
    return img


def make_transparent(img):
    im = img.convert("RGBA")
    r, g, b, a = im.split()
    gray = Image.merge("RGB", (r, g, b)).convert("L")
    mask = gray.point(lambda p: 0 if p > 235 else 255)
    im.putalpha(mask)
    return im


def add_watermark(img):
    im = img.convert("RGBA")
    layer = Image.new("RGBA", im.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(layer)
    size = max(14, im.width // 40)
    font = None
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf"):
        try:
            font = ImageFont.truetype(path, size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    margin = max(10, im.width // 40)
    text = "converted by ImageConv Bot"
    try:
        box = draw.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
    except Exception:
        tw, th = size * 10, size
    draw.text((im.width - tw - margin, im.height - th - margin), text,
              fill=(255, 255, 255, 200), font=font)
    return Image.alpha_composite(im, layer)


def apply_params(img, p):
    if p.get("croppts"):
        x1, y1, x2, y2 = p["croppts"]
        x1 = max(0, min(img.width, x1))
        x2 = max(0, min(img.width, x2))
        y1 = max(0, min(img.height, y1))
        y2 = max(0, min(img.height, y2))
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        if x2 - x1 > 20 and y2 - y1 > 20:
            img = img.crop((x1, y1, x2, y2))
    if p.get("crop") == "11":
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2,
                        (w - side) // 2 + side, (h - side) // 2 + side))
    if p.get("resize"):
        im = img.copy()
        im.thumbnail((p["resize"], p["resize"]))
        img = im
    if p.get("bg"):
        img = make_transparent(img)
    if p.get("wm"):
        img = add_watermark(img)
    if p.get("gray"):
        img = ImageOps.grayscale(img).convert("RGB")
    return img


def encode(img, fmt, quality=92):
    buf = io.BytesIO()
    fmt = (fmt or "PNG").upper()
    if fmt in ("JPG", "JPEG"):
        img.convert("RGB").save(buf, "JPEG", quality=quality)
    elif fmt == "WEBP":
        img.convert("RGBA").save(buf, "WEBP", quality=quality)
    else:
        img.save(buf, "PNG")
    buf.seek(0)
    return buf


def encode_to_kb(img, kb_limit, fmt="JPG"):
    if (fmt or "PNG").upper() == "PNG":
        fmt = "JPG"
    for q in range(95, 20, -5):
        buf = encode(img, fmt, q)
        if len(buf.getvalue()) <= kb_limit * 1024:
            return q, buf
    return 20, encode(img, fmt, 20)


def file_name(fmt):
    fmt = (fmt or "PNG").upper()
    return "converted." + ("jpg" if fmt in ("JPG", "JPEG") else fmt.lower())


@dp.message(Command("start"))
async def cmd_start(m: types.Message):
    await m.answer(TEXT, reply_markup=menu_kb())


@dp.message(Command("help"))
async def cmd_help(m: types.Message):
    await m.answer(TEXT, reply_markup=menu_kb())


async def accept(m: types.Message, data: bytes):
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        await m.answer("Не смог прочитать изображение \U0001F615 Пришли картинку ещё раз.")
        return
    store(m.from_user.id, data)
    await m.answer("Принял \U0001F44D Дальше — кнопки ниже.", reply_markup=menu_kb())


@dp.message(F.photo)
async def on_photo(m: types.Message):
    buf = io.BytesIO()
    await bot.download(m.photo[-1], destination=buf)
    await accept(m, buf.getvalue())


@dp.message(F.document)
async def on_doc(m: types.Message):
    mime = m.document.mime_type or ""
    if not mime.startswith("image/"):
        await m.answer("Это не изображение \u2026 Пришли картинку.")
        return
    buf = io.BytesIO()
    await bot.download(m.document, destination=buf)
    await accept(m, buf.getvalue())


@dp.callback_query()
async def on_cb(q):
    await q.answer()
    uid = q.from_user.id
    key = cur_key(uid)
    if not key:
        await q.message.answer("Сначала пришли изображение.")
        return
    rec = STORE[uid][key]
    p = rec["params"]
    data = q.data

    if data.startswith("fmt:"):
        p["fmt"] = data.split(":", 1)[1]
        img = apply_params(load_img(rec), p)
        prev = img.convert("RGB")
        prev.thumbnail((1200, 1200))
        prev_buf = io.BytesIO()
        prev.save(prev_buf, "JPEG", quality=80)
        prev_buf.seek(0)
        await q.message.answer_photo(
            BufferedInputFile(prev_buf.getvalue(), filename=file_name(p["fmt"])),
            caption=f"Превью \u2022 {p['fmt']} \u2022 качество {p['quality']}%",
            reply_markup=preview_kb())
        return

    if data == "fx:gray":
        p["gray"] = not p["gray"]
        await q.message.answer(f"Ч/Б: {'вкл' if p['gray'] else 'выкл'}", reply_markup=menu_kb())
        return
    if data == "fx:bg":
        p["bg"] = not p["bg"]
        await q.message.answer(f"Прозрачный фон: {'вкл' if p['bg'] else 'выкл'}", reply_markup=menu_kb())
        return
    if data == "fx:wm":
        p["wm"] = not p["wm"]
        await q.message.answer(f"Водяной знак: {'вкл' if p['wm'] else 'выкл'}", reply_markup=menu_kb())
        return
    if data == "fx:resize":
        p["resize"] = None if p.get("resize") else 1920
        await q.message.answer(f"Ресайз: {p['resize'] or 'выкл'}", reply_markup=menu_kb())
        return
    if data == "fx:crop11":
        p["crop"] = None if p.get("crop") == "11" else "11"
        await q.message.answer(f"Кроп 1:1: {'вкл' if p.get('crop') == '11' else 'выкл'}",
                               reply_markup=menu_kb())
        return
    if data == "fx:croppt":
        img = load_img(rec)
        await q.message.answer(
            f"Размер картинки: {img.width}x{img.height}\n\n"
            "Пришли две точки в формате <code>x1 y1 x2 y2</code> — координаты пикселей "
            "левого-верхнего и правого-нижнего углов кропа.",
            parse_mode="HTML")
        return
    if data == "fx:quality":
        await q.message.answer("Качество (JPG / WEBP):", reply_markup=quality_kb(p["quality"]))
        return
    if data.startswith("q:"):
        p["quality"] = int(data.split(":", 1)[1])
        await q.message.answer(f"Качество: {p['quality']}%", reply_markup=menu_kb())
        return
    if data == "fx:compress":
        if p.get("compress_kb"):
            p["compress_kb"] = None
            await q.message.answer("Сжатие выключено", reply_markup=menu_kb())
        else:
            await q.message.answer("Пришли число в КБ (например, 300):", reply_markup=menu_kb())
        return
    if data == "reset":
        rec["params"] = default_params()
        await q.message.answer("Сбросила настройки \U0001F504", reply_markup=menu_kb())
        return
    if data == "do:save":
        img = apply_params(load_img(rec), p)
        fmt = p.get("fmt") or "PNG"
        if p.get("compress_kb"):
            q, buf = encode_to_kb(img, p["compress_kb"], fmt)
            caption = (f"Готово \u2022 {fmt} \u2022 ~{len(buf.getvalue()) / 1024:.0f} КБ "
                       f"(качество {q}%)")
        else:
            buf = encode(img, fmt, p["quality"])
            caption = f"Готово \u2022 {fmt} \u2022 качество {p['quality']}%"
        await q.message.answer_document(
            BufferedInputFile(buf.getvalue(), filename=file_name(fmt)),
            caption=caption)
        return
    if data == "do:again":
        await q.message.answer("Выбирай дальше \U0001F3AF", reply_markup=menu_kb())
        return

    await q.message.answer("Выбери действие:", reply_markup=menu_kb())


@dp.message()
async def on_text(m: types.Message):
    uid = m.from_user.id
    key = cur_key(uid)
    text = (m.text or "").strip()

    if key and text:
        rec = STORE[uid][key]
        parts = text.replace(",", " ").split()
        if len(parts) == 1 and parts[0].isdigit():
            kb_val = int(parts[0])
            if 20 <= kb_val <= 20000:
                rec["params"]["compress_kb"] = kb_val
                await m.answer(f"Буду сжимать до {kb_val} КБ \u2022 выбери формат для превью",
                               reply_markup=menu_kb())
                return
        if len(parts) == 4 and all(p.lstrip("-").isdigit() for p in parts):
            x1, y1, x2, y2 = [int(v) for v in parts]
            rec["params"]["croppts"] = (x1, y1, x2, y2)
            await m.answer("Кроп задан \u2705 Выбери формат — покажу превью",
                           reply_markup=menu_kb())
            return

    await m.answer(TEXT, reply_markup=menu_kb())


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
