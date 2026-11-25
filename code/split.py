"""
Random half test: pairs of products by impressions, one of each pair keeps the site photo.

  python -I code/split.py make stats.csv [family]   -> switches/holdout.txt (control ids) + data/test_pairs.json
  python -I code/split.py read stats.csv            -> link CTR per half, z-test, CPC

stats.csv comes from Meta Ads (product_id breakdown), columns:
  id,impressions,link_clicks,spend       (id = WooCommerce product id = Meta retailer_id)
"""
import csv, json, math, os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    rows = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        rows[r["id"].strip()] = {"imp": float(r["impressions"] or 0), "clk": float(r["link_clicks"] or 0), "spend": float(r.get("spend") or 0)}
    return rows


def make(stats_path, family=None, seed=20261125):
    stats = load(stats_path)
    prods = {str(p["id"]): p for p in json.load(open(os.path.join(ROOT, "data", "classified.json"), encoding="utf-8"))["products"] if not p["skip"]}
    ids = [i for i in prods if (not family or prods[i]["family"] == family)]
    # pair inside each family, so both halves have the same mix of categories
    rnd, pairs, holdout = random.Random(seed), [], []
    fams = sorted({prods[i]["family"] for i in ids})
    for fam in fams:
        ranked = sorted((i for i in ids if prods[i]["family"] == fam), key=lambda i: (-stats.get(i, {"imp": 0})["imp"], i))
        for a, b in zip(ranked[0::2], ranked[1::2]):
            control, test = (a, b) if rnd.random() < 0.5 else (b, a)
            pairs.append({"family": fam, "test": test, "control": control})
            holdout.append(control)
    os.makedirs(os.path.join(ROOT, "switches"), exist_ok=True)
    open(os.path.join(ROOT, "switches", "holdout.txt"), "w", encoding="utf-8").write("\n".join(holdout) + "\n")
    json.dump({"seed": seed, "family": family, "pairs": pairs}, open(os.path.join(ROOT, "data", "test_pairs.json"), "w", encoding="utf-8"), indent=0)
    imp = lambda side: sum(stats.get(p[side], {"imp": 0})["imp"] for p in pairs)
    print(f"{len(pairs)} pairs | past impressions: test half {imp('test'):.0f}, control half {imp('control'):.0f}")


def read(stats_path):
    stats = load(stats_path)
    pairs = json.load(open(os.path.join(ROOT, "data", "test_pairs.json"), encoding="utf-8"))["pairs"]
    tot = {s: {"imp": 0.0, "clk": 0.0, "spend": 0.0} for s in ("test", "control")}
    for p in pairs:
        for s in tot:
            for k in tot[s]:
                tot[s][k] += stats.get(p[s], {"imp": 0, "clk": 0, "spend": 0})[k]
    t, c = tot["test"], tot["control"]
    if not t["imp"] or not c["imp"]:
        print("no impressions yet")
        return
    p1, p2 = t["clk"] / t["imp"], c["clk"] / c["imp"]
    pool = (t["clk"] + c["clk"]) / (t["imp"] + c["imp"])
    se = math.sqrt(pool * (1 - pool) * (1 / t["imp"] + 1 / c["imp"]))
    z = (p1 - p2) / se if se else 0
    pval = math.erfc(abs(z) / math.sqrt(2))
    cpc = lambda x: x["spend"] / x["clk"] if x["clk"] else float("nan")
    print(f"card    : {t['imp']:.0f} imp, link CTR {p1 * 100:.2f}%, CPC {cpc(t):.3f}")
    print(f"control : {c['imp']:.0f} imp, link CTR {p2 * 100:.2f}%, CPC {cpc(c):.3f}")
    print(f"lift {((p1 / p2 - 1) * 100) if p2 else float('nan'):+.1f}% | z {z:.2f} | p {pval:.4f} | " + ("significant at 95%" if pval < 0.05 else "not significant yet, keep running"))


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in ("make", "read"):
        sys.exit(__doc__)
    make(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) if sys.argv[1] == "make" else read(sys.argv[2])
