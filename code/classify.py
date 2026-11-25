"""
Classify every product into one card family and extract the facts a card may show.

Evidence rule: a fact goes on a card only when the product's own title, attributes or
store category state it. Nothing is inferred or invented.

Usage: python -I code/classify.py            -> data/classified.json + coverage table
"""
import html, json, os, re, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Family order = priority. First match wins, so a product sits in exactly one family.
# Matching is on WooCommerce category ids (ancestors included).
FAMILIES = [
    ("sex",          "Sex (προφυλακτικά, λιπαντικά)",      [806, 743, 673, 749]),
    ("korean",       "Korean Beauty",                      [715]),
    ("diapers",      "Παιδικές πάνες",                     [449]),
    ("incontinence", "Ακράτεια",                           [440]),
    ("vitamins",     "Βιταμίνες & Συμπληρώματα",           [725]),
    ("wipes",        "Μωρομάντηλα",                        [116]),
    ("oral",         "Στοματική υγιεινή",                  [423]),
    ("cosmetics",    "Καλλυντικά & Περιποίηση",            [421, 396]),
    ("home",         "Σπίτι & Απορρυπαντικά",              [446]),
    ("baby",         "Βρεφικά, φροντίδα & παιχνίδια",      [142, 424, 704, 683]),
    ("health",       "Υγεία & Υγιεινή",                    [1063, 412]),
]
OTHER = ("other", "Λοιπά")

INGREDIENTS = [
    ("Niacinamide", r"niacinamide|νιασιναμ"), ("Retinol", r"retino|ρετινό"), ("Vitamin C", r"vitamin\s?c\b|vita[- ]?c\b|βιταμίνη\s?c\b"),
    ("Hyaluronic", r"hyaluron|υαλουρον"), ("Centella", r"centella|cica|madecass"), ("Collagen", r"collagen|κολλαγόν"),
    ("Snail Mucin", r"snail|σαλιγκαρ"), ("PDRN", r"\bpdrn\b"), ("Rice", r"\brice\b|ρυζ"), ("Ceramide", r"ceramid"),
    ("Peptide", r"peptid|πεπτίδ"), ("Salicylic / BHA", r"salicyl|\bbha\b"), ("Propolis", r"propolis|πρόπολ"),
    ("Ginseng", r"ginseng"), ("Tea Tree", r"tea\s?tree"), ("Heartleaf", r"heartleaf"), ("Aloe", r"\baloe\b|αλόη"),
]
VIT_FORMS = r"κάψουλες|καψουλες|caps(?:ules)?|ταμπλέτες|ταμπλετες|tabs?|tablets|softgels|μαλακές κάψουλες|δισκία|δισκια|μασώμενες|φακελ[άα]κια|φακελίσκοι|sachets|gummies|ζελεδάκια|αμπούλες|vcaps|veg\.?\s?caps"
DIAPER_PACKS = [
    ("Mega Monthly Pack", r"mega\s?monthly"), ("Mini Monthly Pack", r"mini\s?monthly"), ("Monthly Pack", r"monthly"),
    ("Double Pack", r"double\s?pack"), ("Super Jumbo", r"super\s?jumbo"), ("Jumbo+", r"jumbo\s?\+|jumbo\s?plus"), ("Jumbo Pack", r"jumbo"),
    ("Mega Pack", r"mega\s?pack|megapack"), ("Giant Pack", r"giant"), ("Value Pack", r"value\s?pack"),
]
DIAPER_LINES = [
    ("Premium Care Pants", r"premium\s?care\s?pants"), ("Premium Care", r"premium\s?care"), ("Harmonie Pants", r"harmonie.*pants|pants.*harmonie"),
    ("Harmonie", r"harmonie"), ("Night Pants", r"night\s?pants"), ("Pants", r"pants|βρακ[άα]κι"), ("Active Baby", r"active\s?baby"),
    ("Baby-Dry", r"baby[- ]?dry"), ("Sensitive", r"sensitive"), ("Pure", r"\bpure\b"), ("Premium", r"premium"),
]


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def num(s):
    return float(s.replace(",", "."))


def first(pat, text, flags=re.I):
    m = re.search(pat, text, flags)
    return m


def extract(fam, p, cat_names):
    name = clean(p["name"])
    low = name.lower()
    f = {}
    brand = next((a["terms"][0] for a in p["attributes"] if a["name"] in ("brand", "Μάρκα") and a["terms"]), None)
    if brand:
        f["brand"] = clean(brand)
    # pieces: "174τεμ", "(102τεμ)", "12x60", "100 τμχ"
    m = first(r"(\d{1,3})\s?[x×χ]\s?(\d{1,3})\s?(cm|εκ)?", low)
    if m and (m.group(3) or (fam in ("incontinence", "home") and int(m.group(1)) >= 40 and int(m.group(2)) >= 40)):
        f["dims"] = f"{m.group(1)}×{m.group(2)} cm"
    elif m and int(m.group(1)) <= 36 and int(m.group(2)) >= 5:
        f["multi"] = f"{m.group(1)}×{m.group(2)}"
        f["pieces"] = int(m.group(1)) * int(m.group(2))
    m = first(r"(\d{1,4})\s?(?:τεμ[άα]χ\w*|τεμ\b|τεμ\.|τμχ|τμχ\.|pcs|pieces|φύλλα)", low)
    if m:
        # a title can state both the inner pack and the total ("8×15 τμχ (120 τμχ)"): the total is the largest
        allp = [int(x) for x in re.findall(r"(\d{1,4})\s?(?:τεμ[άα]χ\w*|τεμ\b|τεμ\.|τμχ|pcs|pieces|φύλλα)", low)]
        f["pieces"] = max(allp + [f.get("pieces", 0)])
    if fam in ("diapers", "incontinence"):
        m = first(r"\b(?:n|ν)[oοº°]?\.?\s?(\d\+?)(?!\d)", low)
        if m:
            f["size_no"] = m.group(1)
        m = first(r"(\d{1,2})\s?[-–]\s?(\d{1,2})\s?kg", low) or first(r"(\d{1,2})\s?\+\s?kg()", low)
        if m:
            f["kg"] = f"{m.group(1)}-{m.group(2)} kg" if m.group(2) else f"{m.group(1)}+ kg"
        f["pack"] = next((n for n, r in DIAPER_PACKS if re.search(r, low)), None)
        f["line"] = next((n for n, r in DIAPER_LINES if re.search(r, low)), None)
    if fam == "incontinence":
        m = first(r"\b(xxl|extra\s?extra\s?large|extra\s?large|x-?large|xl|large|medium|small)\b", low) or first(r"\b(?:size|μέγεθος)\s?([sml])\b", low)
        if m:
            f["size"] = {"extra extra large": "XXL", "extra large": "XL", "x-large": "XL", "xlarge": "XL", "large": "L", "medium": "M", "small": "S"}.get(re.sub(r"\s+", " ", m.group(1)), m.group(1).upper())
        m = first(r"\b(maxi|super|plus|night|normal|ultra)\b", low)
        if m:
            f["absorb"] = m.group(1).capitalize()
    if fam == "vitamins":
        m = first(r"(\d{1,4})\s?(?:φυτικές\s|μαλακές\s|αναβράζοντα\s|αναβράζουσες\s|vegan\s|veg\.?\s?)?(" + VIT_FORMS + r")", low)
        if m:
            f["count"] = f"{m.group(1)} {m.group(2)}"
        m = first(r"(\d[\d.,]*)\s?(mg|mcg|μg|iu|gr|g)\b", low)
        if m:
            f["dose"] = f"{m.group(1)} {m.group(2).upper() if m.group(2) == 'iu' else m.group(2)}"
        need = [c for c in cat_names if c in VIT_NEEDS]
        if need:
            f["need"] = VIT_NEEDS[need[0]]
    if fam in ("korean", "cosmetics", "oral", "baby", "home", "wipes", "health", "sex", "vitamins"):
        m = first(r"(\d[\d.,]*)\s?(ml|lt|l|gr|g|kg)\b", low)
        if m and not (fam == "vitamins" and m.group(2) in ("g", "gr") and "dose" in f):
            f["volume"] = f"{m.group(1)} {m.group(2)}"
    if fam in ("korean", "cosmetics"):
        m = first(r"spf\s?(\d{2}\+?)", low)
        if m:
            f["spf"] = "SPF " + m.group(1)
        ing = sorted((re.search(r, low).start(), n) for n, r in INGREDIENTS if re.search(r, low))
        if ing:
            f["ingredient"] = ing[0][1]  # the one the title names first
        t = [c for c in cat_names if c in SKIN_TYPES]
        if t:
            f["type"] = SKIN_TYPES[t[0]]
    if fam == "home":
        m = first(r"(\d{1,3})\s?(μεζ(?:ο[ύυ]ρες)?|πλ[ύυ]σεις|μεζ\.|caps|κ[άα]ψουλ\w*|ταμπλ[έε]τ\w*|tabs)", low)
        if m:
            f["washes"] = f"{m.group(1)} {'πλύσεις' if m.group(2).startswith(('μεζ', 'πλ')) else m.group(2)}"
    if fam == "baby":
        m = first(r"(\d{1,2})\s?\+\s?(?:m|μ|μην[ώω]ν|months)\b|(\d{1,2})\s?[-–]\s?(\d{1,2})\s?(?:m|μ|μην[ώω]ν|months)\b|\+\s?(\d{1,2})\s?(?:m|μ|μην[ώω]ν)", low)
        if m:
            f["age"] = (f"{m.group(1)}+ μηνών" if m.group(1) else f"{m.group(2)}-{m.group(3)} μηνών" if m.group(2) else f"{m.group(4)}+ μηνών")
    if fam == "sex":
        pass
    if p.get("price") and f.get("pieces") and fam in ("diapers", "incontinence", "wipes") and f["pieces"] >= 10:
        f["unit_price"] = round(p["price"] / f["pieces"], 3)
    return {k: v for k, v in f.items() if v not in (None, "")}


VIT_NEEDS = {
    "Ανοσοποιητικό": "Ανοσοποιητικό", "Άγχος - Ύπνος - Νευρικό Σύστημα": "Ύπνος & Ηρεμία", "Ενέργεια & Τόνωση": "Ενέργεια",
    "Καρδιά & Κυκλοφορικό": "Καρδιά", "Οστά - Αρθρώσεις - Μύες": "Οστά & Αρθρώσεις", "Άθληση & Αποκατάσταση": "Άθληση",
    "Γυναίκα & Εγκυμοσύνη": "Γυναίκα", "Παιδί": "Για παιδιά", "Πεπτικό Σύστημα & Αποτοξίνωση": "Πεπτικό",
    "Ωμέγα-3 & Μουρουνέλαιο": "Ωμέγα-3", "Προβιοτικά": "Προβιοτικά", "Μεταβολισμός & Έλεγχος Βάρους": "Μεταβολισμός",
    "Άντρας & Γονιμότητα": "Άντρας", "Πολυβιταμίνες & Μέταλλα": "Πολυβιταμίνη",
}
SKIN_TYPES = {
    "Serum & Ampoule": "Serum", "Serum Προσώπου": "Serum", "Κρέμες Προσώπου": "Κρέμα προσώπου", "Μάσκες Προσώπου": "Μάσκα προσώπου",
    "Toner & Essence": "Toner", "Καθαρισμός": "Καθαρισμός", "Καθαρισμός Προσώπου": "Καθαρισμός", "Περιποίηση Ματιών": "Μάτια",
    "Αντηλιακή Προστασία": "Αντηλιακό", "Περιποίηση Ατελειών": "Ατέλειες", "Περιποίηση Μαλλιών": "Μαλλιά", "Αποσμητικά": "Αποσμητικό",
    "Αφρόλουτρα": "Αφρόλουτρο", "Σώματος": "Σώμα", "Αντηλιακά": "Αντηλιακό",
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    d = json.load(open(os.path.join(ROOT, "data", "products.json"), encoding="utf-8"))
    cats = {c["id"]: c for c in d["categories"]}

    def ancestors(cid):
        out = set()
        while cid and cid in cats and cid not in out:
            out.add(cid)
            cid = cats[cid]["parent"]
        return out

    rows, cov = [], collections.defaultdict(collections.Counter)
    for p in d["products"]:
        ids = set()
        for c in p["categories"]:
            ids |= ancestors(c["id"])
        fam, label = next(((k, l) for k, l, cids in FAMILIES if ids & set(cids)), OTHER)
        # wipes sold inside a diaper or baby category are still wipes
        if fam in ("diapers", "baby") and re.search(r"μωρομ[άα]ντ[ηι]λ|υγρ[άα] μαντ[ηι]λ|\bwipes\b", clean(p["name"]).lower()):
            fam, label = "wipes", "Μωρομάντηλα"
        cat_names = [clean(c["name"]) for c in p["categories"]]
        facts = extract(fam, p, cat_names)
        skip = None
        if not p["images"]:
            skip = "no image"
        elif p["type"] in ("pw-gift-card",):
            skip = "gift card"
        elif not p["price"]:
            skip = "no price"
        elif fam == "sex":
            skip = "sex category (excluded until decided)"
        rows.append({
            "id": p["id"], "name": clean(p["name"]), "family": fam, "family_label": label, "price": p["price"],
            "regular_price": p["regular_price"], "on_sale": p["on_sale"], "permalink": p["permalink"],
            "image": p["images"][0]["src"] if p["images"] else None, "categories": cat_names, "facts": facts, "skip": skip,
        })
        cov[fam]["_n"] += 1
        for k in facts:
            cov[fam][k] += 1
    json.dump({"fetched": d["fetched"], "families": [{"key": k, "label": l} for k, l, _ in FAMILIES] + [{"key": OTHER[0], "label": OTHER[1]}], "products": rows},
              open(os.path.join(ROOT, "data", "classified.json"), "w", encoding="utf-8"), ensure_ascii=False)
    cover = {}
    print(f"{'family':14} {'n':>5}  fact coverage")
    for k, l, _ in FAMILIES + [(OTHER[0], OTHER[1], [])]:
        c = cov[k]
        n = c.pop("_n", 0)
        cover[k] = {"label": l, "n": n, "facts": {f: v for f, v in c.most_common()}}
        print(f"{k:14} {n:5}  " + ", ".join(f"{f} {v} ({v * 100 // max(n, 1)}%)" for f, v in c.most_common()))
    json.dump(cover, open(os.path.join(ROOT, "data", "coverage.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
