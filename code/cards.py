"""
Render a product card (1080x1080) for the Meta catalog, in one of several concepts.

A card is built only from facts in data/classified.json (see classify.py) and from the
brand tokens in client.config.json. Fonts and colours come from the config, not from here.

Concepts
  K0  today: the site photo as Meta shows it in a square tile
  C1  clean frame: logo, whole product, readable name
  C2  spec chips: up to 3 facts of the family (No, kg, pieces / type, ingredient, ml / ...)
  C3  hero fact: the one fact that decides the click, as a big pill on the photo
  C4  value: price per piece (diapers, incontinence, wipes). Needs the hourly rebuild.
  C5  store USPs: chips + shipping line of the store
  C6  colour panel: product cut out on the brand panel, name on an orange band

Usage (single card, for a quick look):
  python -I code/cards.py <product_id> <concept> out.jpg
"""
import hashlib, io, json, os, sys, urllib.request
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "client.config.json"), encoding="utf-8"))
B = CFG["brand"]
W = H = 1080
CONCEPTS = ["K0", "C1", "C2", "C3", "C4", "C5", "C6"]


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


CREAM, CREAM2, ORANGE, ORANGE1, ORANGE2, DARK, WHITE = (rgb(B["colors"][k]) for k in ("cream", "cream_deep", "orange", "pill_top", "pill_bottom", "dark", "white"))
_fonts = {}


def font(role, size):
    key = (role, size)
    if key not in _fonts:
        for path in B["fonts"][role]:
            path = path if os.path.isabs(path) else os.path.join(ROOT, path)
            if os.path.exists(path):
                _fonts[key] = ImageFont.truetype(path, size)
                break
        else:
            raise FileNotFoundError(f"no font file found for role {role}: {B['fonts'][role]}")
    return _fonts[key]


# ---------- source image ----------
def fetch_image(url, cache=os.path.join(ROOT, "data", "img_cache")):
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, hashlib.sha1(url.encode()).hexdigest()[:16])
    if not os.path.exists(path):
        req = urllib.request.Request(urllib.request.quote(url, safe=":/%?=&"), headers={"User-Agent": "Mozilla/5.0 (dpa-cards)"})
        with urllib.request.urlopen(req, timeout=40) as r:
            open(path, "wb").write(r.read())
    im = Image.open(path)
    im.load()
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        bg.alpha_composite(im)
        im = bg
    return im.convert("RGB")


def trim(im, thr=242, margin=0.03):
    """Crop the white margins of a pack shot so the product fills the tile."""
    diff = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).convert("L")
    bbox = diff.point(lambda v: 255 if v > 255 - thr else 0).getbbox()
    if not bbox:
        return im
    m = int(max(im.size) * margin)
    x0, y0, x1, y1 = bbox
    return im.crop((max(0, x0 - m), max(0, y0 - m), min(im.width, x1 + m), min(im.height, y1 + m)))


def product_share(im):
    """Share of the tile covered by non-white pixels: the QC number 'is the product visible'."""
    g = ImageChops.difference(im, Image.new("RGB", im.size, (255, 255, 255))).convert("L").point(lambda v: 255 if v > 14 else 0)
    return sum(g.histogram()[255:]) / (im.width * im.height)


# ---------- drawing helpers ----------
def canvas():
    im = Image.new("RGBA", (W, H), CREAM + (255,))
    g = Image.new("RGBA", (W, H))
    gd = ImageDraw.Draw(g)
    for y in range(H):
        gd.line([(0, y), (W, y)], fill=CREAM2 + (int(110 * y / H),))
    im.alpha_composite(g)
    return im


def shadow(im, box, r=28, blur=18, alpha=55):
    x0, y0, x1, y1 = box
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 8, x1, y1 + 8), r, fill=(90, 50, 20, alpha))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))


def panel(im, box, fill=WHITE, r=28):
    shadow(im, box, r)
    ImageDraw.Draw(im).rounded_rectangle(box, r, fill=fill + (255,))


def wordmark(im, y=30, size=40, fill=None):
    d = ImageDraw.Draw(im)
    f, t, sp = font("logo", size), B["wordmark"], 4
    w = sum(d.textlength(c, font=f) for c in t) + sp * (len(t) - 1)
    x = (W - w) / 2
    for c in t:
        d.text((x, y), c, font=f, fill=fill or ORANGE)
        x += d.textlength(c, font=f) + sp


def gradient(size, top, bottom, r):
    w, h = size
    g = Image.new("RGBA", size)
    gd = ImageDraw.Draw(g)
    for i in range(h):
        t = i / max(h - 1, 1)
        gd.line([(0, i), (w, i)], fill=tuple(int(top[k] + (bottom[k] - top[k]) * t) for k in range(3)) + (255,))
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    g.putalpha(m)
    return g


def pill(im, x, y, text, size=60, padx=34, pady=18, colors=None, anchor="l"):
    """Solid gradient pill. Returns (w, h). anchor: l, r or c for x."""
    f = font("black", size)
    d = ImageDraw.Draw(im)
    bb = f.getbbox(text)
    w, h = int(d.textlength(text, font=f) + 2 * padx), int(bb[3] - bb[1] + 2 * pady)
    x = int(x - w if anchor == "r" else x - w / 2 if anchor == "c" else x)
    top, bottom = colors or (ORANGE1, ORANGE2)
    shadow(im, (x, y, x + w, y + h), r=h // 2, blur=10, alpha=80)
    im.alpha_composite(gradient((w, h), top, bottom, h // 2), (x, int(y)))
    ImageDraw.Draw(im).text((x + padx, y + pady - bb[1]), text, font=f, fill=WHITE)
    return w, h


def chips(im, texts, y, size=42, gap=16, maxw=W - 120, first_solid=True, on_dark=False):
    """A centred row of chips. Shrinks the font until the row fits. Returns row height."""
    texts = [t for t in texts if t][:3]
    if not texts:
        return 0
    d = ImageDraw.Draw(im)
    while True:
        f = font("bold", size)
        padx, pady = int(size * 0.62), int(size * 0.36)
        ws = [int(d.textlength(t, font=f) + 2 * padx) for t in texts]
        if sum(ws) + gap * (len(ws) - 1) <= maxw or size <= 26:
            break
        size -= 2
    bb = f.getbbox("Άg")
    h = bb[3] - bb[1] + 2 * pady
    x = (W - sum(ws) - gap * (len(ws) - 1)) // 2
    for i, (t, w) in enumerate(zip(texts, ws)):
        if i == 0 and first_solid and not on_dark:
            im.alpha_composite(gradient((w, h), ORANGE1, ORANGE2, h // 2), (x, y))
            col = WHITE
        elif on_dark:
            ImageDraw.Draw(im).rounded_rectangle((x, y, x + w, y + h), h // 2, fill=WHITE + (255,))
            col = ORANGE2
        else:
            ImageDraw.Draw(im).rounded_rectangle((x, y, x + w, y + h), h // 2, fill=WHITE + (255,), outline=ORANGE + (255,), width=3)
            col = ORANGE2
        ImageDraw.Draw(im).text((x + padx, y + pady - bb[1]), t, font=f, fill=col)
        x += w + gap
    return h


def wrap(d, text, f, maxw, lines=2):
    words, out, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw:
            cur = t
        else:
            out.append(cur)
            cur = w
            if len(out) == lines:
                break
    if len(out) < lines and cur:
        out.append(cur)
        cur = ""
    if (cur or len(out) > lines) and out:
        out = out[:lines]
        while out[-1] and d.textlength(out[-1] + "…", font=f) > maxw:
            out[-1] = out[-1].rsplit(" ", 1)[0] if " " in out[-1] else out[-1][:-1]
        out[-1] += "…"
    return [l for l in out if l]


def title(im, text, y, size=50, lines=2, fill=None, maxw=W - 120, role="bold"):
    d = ImageDraw.Draw(im)
    f = font(role, size)
    ls = wrap(d, text, f, maxw, lines)
    lh = int(size * 1.22)
    for i, l in enumerate(ls):
        d.text(((W - d.textlength(l, font=f)) / 2, y + i * lh), l, font=f, fill=fill or DARK)
    return len(ls) * lh


def place(im, prod, box, pad=36, multiply=False):
    x0, y0, x1, y1 = box
    p = prod.copy()
    bw, bh = x1 - x0 - 2 * pad, y1 - y0 - 2 * pad
    s = min(bw / p.width, bh / p.height)
    p = p.resize((max(1, int(p.width * s)), max(1, int(p.height * s))), Image.LANCZOS)
    px, py = x0 + (x1 - x0 - p.width) // 2, y0 + (y1 - y0 - p.height) // 2
    if multiply:
        region = im.crop((px, py, px + p.width, py + p.height)).convert("RGB")
        im.paste(ImageChops.multiply(region, p), (px, py))
    else:
        im.paste(p, (px, py))


# ---------- copy ----------
def money(v, digits=2):
    return f"{v:.{digits}f}".replace(".", ",") + "€"


def short_name(p):
    f, fam = p["facts"], p["family"]
    if fam == "diapers" and f.get("brand") and f.get("line"):
        return " ".join(x for x in (f["brand"], f["line"], f.get("pack")) if x)
    n = p["name"]
    for sep in (" – ", " - ", ",", " (", " με "):
        i = n.find(sep)
        if i >= 18:
            n = n[:i]
    return n.strip(" ,-–")


def chip_texts(p):
    f, fam = p["facts"], p["family"]
    pcs = f"{f['pieces']} τεμ." if f.get("pieces") else None
    if fam == "diapers":
        return [f"Νο {f['size_no']}" if f.get("size_no") else None, f.get("kg"), pcs]
    if fam == "incontinence":
        return [f"Μέγεθος {f['size']}" if f.get("size") else f.get("dims"), pcs, f.get("absorb")]
    if fam == "wipes":
        return [f.get("multi"), pcs]
    if fam == "vitamins":
        return [f.get("count") or f.get("volume"), f.get("dose"), f.get("need")]
    if fam in ("korean", "cosmetics"):
        return [f.get("type"), f.get("ingredient") or f.get("spf"), f.get("volume")]
    if fam == "home":
        return [f.get("washes"), f.get("volume"), pcs or f.get("dims")]
    if fam == "baby":
        return [f.get("age"), f.get("volume"), pcs]
    return [f.get("volume"), pcs]


def hero_text(p):
    f, fam = p["facts"], p["family"]
    if fam == "diapers" and f.get("size_no"):
        return f"Νο {f['size_no']}" + (f" · {f['kg']}" if f.get("kg") else "")
    if fam == "incontinence":
        return f"Μέγεθος {f['size']}" if f.get("size") else (f"{f['pieces']} τεμ." if f.get("pieces") else None)
    if fam == "wipes":
        return f"{f['pieces']} μωρομάντηλα" if f.get("pieces") else None
    if fam == "vitamins":
        return f.get("count") or f.get("need")
    if fam in ("korean", "cosmetics"):
        return f.get("ingredient") or f.get("spf") or f.get("type")
    if fam == "home":
        return f.get("washes") or f.get("volume")
    if fam == "baby":
        return f.get("age")
    return None


def value_text(p):
    f, fam = p["facts"], p["family"]
    u = f.get("unit_price")
    lo, hi = CFG["unit_price_bounds"].get(fam, (0, 0))
    if not u or not (lo <= u <= hi):
        return None
    if fam == "diapers":
        return f"{money(u)} / πάνα"
    if fam == "incontinence":
        return f"{money(u)} / τεμ."
    if fam == "wipes":
        return f"{money(u * 100)} / 100 τεμ."
    return None


def accent(p):
    return (rgb(B["colors"]["kbeauty_top"]), rgb(B["colors"]["kbeauty_bottom"])) if p["family"] == "korean" else None


# ---------- concepts ----------
def k0(p, src):
    im = Image.new("RGB", (W, H), (255, 255, 255))
    s = min(W / src.width, H / src.height)
    r = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
    im.paste(r, ((W - r.width) // 2, (H - r.height) // 2))
    return im


def c1(p, src):
    im = canvas(); wordmark(im, 24, 34)
    box = (36, 80, W - 36, 880); panel(im, box); place(im, trim(src), box, pad=22)
    title(im, short_name(p), 904, 58)
    return im


def c2(p, src):
    im = canvas(); wordmark(im, 24, 34)
    box = (36, 80, W - 36, 790); panel(im, box); place(im, trim(src), box, pad=22)
    h = chips(im, chip_texts(p), 814, 56)
    if h:
        title(im, short_name(p), 814 + h + 22, 50, lines=2)
    else:
        title(im, short_name(p), 830, 58, lines=3)
    return im


def c3(p, src):
    im = canvas(); wordmark(im, 24, 34)
    box = (36, 80, W - 36, 880); panel(im, box)
    t = hero_text(p)
    place(im, trim(src), (36, 190 if t else 80, W - 36, 880), pad=22)
    if t:
        pill(im, 66, 108, t, 76, padx=40, pady=22, colors=accent(p))
    title(im, short_name(p), 904, 58)
    return im


def c4(p, src):
    im = canvas(); wordmark(im, 24, 34)
    box = (36, 80, W - 36, 790); panel(im, box)
    v = value_text(p)
    place(im, trim(src), (36, 80, W - 36, 690 if v else 790), pad=22)
    if v:
        pill(im, W / 2, 664, v, 68, padx=40, pady=22, anchor="c")
    h = chips(im, chip_texts(p), 814, 56, first_solid=not v)
    if h:
        title(im, short_name(p), 814 + h + 22, 50, lines=2)
    else:
        title(im, short_name(p), 830, 58, lines=3)
    return im


def c5(p, src):
    # Chosen 2026-11-25: no logo, the frame starts at the top so the product is larger.
    im = canvas()
    box = (32, 32, W - 32, 770); panel(im, box); place(im, trim(src), box, pad=16)
    h = chips(im, chip_texts(p), 792, 54)
    name, size = short_name(p), 46
    if h:  # one line next to the chips: shrink a little before cutting the name
        d = ImageDraw.Draw(im)
        while size > 38 and d.textlength(name, font=font("bold", size)) > W - 120:
            size -= 2
    title(im, name, 792 + (h + 14 if h else 10), size, lines=1 if h else 2)
    band = gradient((W, 104), ORANGE1, ORANGE2, 0)
    im.alpha_composite(band, (0, H - 104))
    d = ImageDraw.Draw(im)
    f = font("bold", 46)
    line = "  ·  ".join(CFG["store_usps"][:2])
    while d.textlength(line, font=f) > W - 80:
        f = font("bold", f.size - 1)
    bb = f.getbbox(line)
    d.text(((W - d.textlength(line, font=f)) / 2, H - 52 - (bb[3] + bb[1]) / 2), line, font=f, fill=WHITE)
    return im


def c6(p, src):
    im = canvas()
    wordmark(im, 24, 34)
    place(im, trim(src), (20, 76, W - 20, 800), pad=10, multiply=True)
    a = accent(p) or (ORANGE1, ORANGE2)
    im.alpha_composite(gradient((W, 264), a[0], a[1], 0), (0, H - 264))
    h = chips(im, chip_texts(p), H - 240, 56, on_dark=True)
    title(im, short_name(p), H - 240 + (h + 22 if h else 30), 50, lines=1 if h else 3, fill=WHITE)
    return im


RENDER = {"K0": k0, "C1": c1, "C2": c2, "C3": c3, "C4": c4, "C5": c5, "C6": c6}


def render(p, concept, src=None):
    src = src or fetch_image(p["image"])
    return RENDER[concept](p, src).convert("RGB")


def input_hash(p, concept):
    """File name hash: changes when photo, title, shown facts or design version change."""
    key = json.dumps([p["image"], p["name"], p["facts"], concept, CFG["design_version"], CFG["store_usps"] if concept == "C5" else None], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(key.encode()).hexdigest()[:10]


if __name__ == "__main__":
    pid, concept, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    prods = {p["id"]: p for p in json.load(open(os.path.join(ROOT, "data", "classified.json"), encoding="utf-8"))["products"]}
    render(prods[pid], concept).save(out, quality=90)
    print("saved", out)
