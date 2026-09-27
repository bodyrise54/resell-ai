import csv
import math
import os
from datetime import datetime, timezone

MAX_PRODUCTS = int(os.getenv("MAX_PRODUCTS", "60"))
COMMISSION_PCT = float(os.getenv("COMMISSION_PCT", "13"))
TARGET_MARGIN_PCT = float(os.getenv("TARGET_MARGIN_PCT", "25"))

def money(x):
    return round(float(x), 2)

def sale_price(cost):
    # Simple target-margin formula:
    # price - fee(price) - cost = target_margin * price
    fee = COMMISSION_PCT / 100
    margin = TARGET_MARGIN_PCT / 100
    denominator = 1 - fee - margin
    if denominator <= 0:
        return None
    return money(float(cost) / denominator)

def score(row):
    cost = float(row["cost"])
    price = sale_price(cost)
    if price is None:
        return -999

    supplier_stock = int(row.get("supplier_stock", "0") or 0)
    rating = float(row.get("rating", "0") or 0)
    reviews = int(row.get("reviews", "0") or 0)

    if supplier_stock <= 0:
        return -999

    profit = price * (1 - COMMISSION_PCT / 100) - cost
    margin = profit / price if price else 0

    # Conservative score: profitability + stock + social proof.
    return (
        margin * 60
        + min(math.log10(max(reviews, 1) + 1), 5) * 4
        + min(supplier_stock / 1000, 5) * 2
        + max(min(rating - 3.0, 2.0), 0) * 8
    )

def build_title(row):
    title = row["name"].strip()
    brand = row.get("brand", "").strip()
    if brand and brand.lower() not in title.lower():
        title = f"{brand} {title}"
    return title[:80]

def build_description(row, price, profit):
    return (
        f"{row['name']}\n\n"
        f"Produit sélectionné automatiquement par Resell AI.\n"
        f"Prix indicatif : {price:.2f} €\n"
        f"Stock fournisseur détecté : {row['supplier_stock']}\n\n"
        f"Référence fournisseur : {row['supplier_sku']}\n"
        f"Important : vérifier les informations produit, la disponibilité, "
        f"les droits sur les images/marque et les règles de la marketplace "
        f"avant publication."
    )

def main():
    input_file = "products.csv"
    output_file = "selected_products.csv"
    listings_file = "draft_listings.csv"

    with open(input_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    candidates = []
    for row in rows:
        try:
            s = score(row)
            if s <= -999:
                continue
            price = sale_price(float(row["cost"]))
            profit = price * (1 - COMMISSION_PCT / 100) - float(row["cost"])
            row["_score"] = s
            row["_sale_price"] = price
            row["_profit"] = money(profit)
            candidates.append(row)
        except (ValueError, KeyError):
            continue

    candidates.sort(key=lambda r: r["_score"], reverse=True)
    selected = candidates[:MAX_PRODUCTS]

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        fields = [
            "supplier_sku", "name", "brand", "cost", "supplier_stock",
            "rating", "reviews", "_sale_price", "_profit", "_score"
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in selected)

    with open(listings_file, "w", newline="", encoding="utf-8") as f:
        fields = [
            "supplier_sku", "title", "description", "price",
            "quantity", "profit_estimate", "status", "generated_at"
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        now = datetime.now(timezone.utc).isoformat()
        for r in selected:
            w.writerow({
                "supplier_sku": r["supplier_sku"],
                "title": build_title(r),
                "description": build_description(r, r["_sale_price"], r["_profit"]),
                "price": r["_sale_price"],
                "quantity": min(int(r["supplier_stock"]), 10),
                "profit_estimate": r["_profit"],
                "status": "READY_FOR_EBAY_API",
                "generated_at": now,
            })

    print(f"Selected {len(selected)} products.")
    print(f"Wrote {output_file} and {listings_file}.")

if __name__ == "__main__":
    main()
