"""
Rollout order from Meta delivery per product.

Input : a saved Meta Ads report (ad level, breakdown product_id), as JSON from the Meta Ads connector.
Output: data/meta_product_stats.csv (id,impressions,link_clicks,spend) and supp_order.txt.

Order: products with impressions first (most seen first), then the rest family by family.
The 20 pilot ids on top are spread over the families, so the pilot shows every template.

Usage: python -I code/order.py <report.json> [pilot_size]
"""
import collections, csv, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAMILY_ORDER = ["diapers", "korean", "vitamins", "incontinence", "wipes", "cosmetics", "baby", "home", "oral", "health"]


def num(v):
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rep = json.load(open(sys.argv[1], encoding="utf-8"))
    pilot = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    rows = rep["ad_entities"]
    if isinstance(rows, str):
        rows = json.loads(rows)
    stats = collections.defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        pid = str(r.get("product_id") or "")
        rid = pid.split(",", 1)[0].strip()          # "1661924, product name" -> retailer id
        if not rid.isdigit():
            continue
        s = stats[rid]
        s[0] += num(r.get("impressions")); s[1] += num(r.get("link_click")); s[2] += num(r.get("amount_spent"))
    prods = {str(p["id"]): p for p in json.load(open(os.path.join(ROOT, "data", "classified.json"), encoding="utf-8"))["products"]
             if not p["skip"] and p["family"] in FAMILY_ORDER}
    with open(os.path.join(ROOT, "data", "meta_product_stats.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "impressions", "link_clicks", "spend"])
        for rid, s in sorted(stats.items(), key=lambda x: -x[1][0]):
            w.writerow([rid, int(s[0]), int(s[1]), round(s[2], 2)])
    seen = sorted((i for i in prods if stats.get(i, [0])[0] > 0), key=lambda i: (-stats[i][0], i))
    # pilot: best seen product of each family in turn
    by_fam = {f: [i for i in seen if prods[i]["family"] == f] for f in FAMILY_ORDER}
    head, k = [], 0
    while len(head) < pilot and any(by_fam.values()):
        f = FAMILY_ORDER[k % len(FAMILY_ORDER)]
        if by_fam[f]:
            head.append(by_fam[f].pop(0))
        k += 1
    rest_seen = [i for i in seen if i not in set(head)]
    unseen = sorted((i for i in prods if i not in set(seen)), key=lambda i: (FAMILY_ORDER.index(prods[i]["family"]), i))
    order = head + rest_seen + unseen
    open(os.path.join(ROOT, "supp_order.txt"), "w", encoding="utf-8").write("\n".join(order) + "\n")
    tot = sum(s[0] for s in stats.values())
    in_cat = sum(stats[i][0] for i in seen)
    print(f"report rows {len(rows)} | products with delivery {len(stats)} ({tot:.0f} impressions) | of them with a card {len(seen)} ({in_cat:.0f} impressions)")
    print(f"order: {len(head)} pilot + {len(rest_seen)} seen + {len(unseen)} not seen = {len(order)}")
    print("pilot:", collections.Counter(prods[i]["family"] for i in head))
    for i in head:
        print(" ", i, prods[i]["family"], int(stats[i][0]), prods[i]["name"][:60])


if __name__ == "__main__":
    main()
