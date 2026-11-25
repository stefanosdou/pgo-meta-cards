"""
Fetch in-stock products from the WooCommerce Store API (public, read-only) into data/products.json.
Usage: python -I code/fetch.py [out.json]
"""
import json, os, sys, time, urllib.request, urllib.parse

SITE = "https://www.panesgiaolous.gr"
UA = {"User-Agent": "Mozilla/5.0 (dpa-cards)"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def slim(p):
    pr = p.get("prices") or {}
    minor = int(pr.get("currency_minor_unit", 2) or 2)
    f = lambda k: (int(pr[k]) / 10 ** minor) if pr.get(k) not in (None, "") else None
    return {
        "id": p["id"],
        "sku": p.get("sku"),
        "name": p.get("name"),
        "slug": p.get("slug"),
        "permalink": p.get("permalink"),
        "type": p.get("type"),
        "on_sale": p.get("on_sale"),
        "price": f("price"),
        "regular_price": f("regular_price"),
        "sale_price": f("sale_price"),
        "short_description": p.get("short_description"),
        "description": p.get("description"),
        "categories": [{"id": c["id"], "name": c["name"], "slug": c["slug"]} for c in p.get("categories", [])],
        "tags": [t["name"] for t in p.get("tags", [])],
        "brands": [b["name"] for b in p.get("brands", [])] if p.get("brands") else [],
        "attributes": [{"name": a.get("name"), "terms": [t.get("name") for t in a.get("terms", [])]} for a in p.get("attributes", [])],
        "images": [{"src": i["src"], "thumb": i.get("thumbnail")} for i in p.get("images", [])],
        "rating": p.get("average_rating"),
        "review_count": p.get("review_count"),
        "is_in_stock": p.get("is_in_stock"),
        "low_stock_remaining": p.get("low_stock_remaining"),
    }


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "products.json")
    items, page = [], 1
    while True:
        q = urllib.parse.urlencode({"per_page": 100, "page": page, "stock_status": "instock"})
        batch = get(f"{SITE}/wp-json/wc/store/v1/products?{q}")
        if not batch:
            break
        items += [slim(p) for p in batch]
        print(f"page {page}: {len(items)}", flush=True)
        page += 1
    cats = []
    page = 1
    while True:
        batch = get(f"{SITE}/wp-json/wc/store/v1/products/categories?per_page=100&page={page}")
        if not batch:
            break
        cats += [{"id": c["id"], "name": c["name"], "slug": c["slug"], "parent": c["parent"], "count": c["count"]} for c in batch]
        page += 1
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "products": items, "categories": cats}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print("saved", len(items), "products,", len(cats), "categories ->", out)


if __name__ == "__main__":
    main()
