from __future__ import annotations

import csv
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://developers.cjdropshipping.com/api2.0/v1"
CJ_API_KEY = os.getenv("CJ_API_KEY", os.getenv("CJ_ACCESS_TOKEN", "")).strip()
MAX_PRODUCTS = int(os.getenv("MAX_PRODUCTS", "60"))
COMMISSION_PCT = float(os.getenv("COMMISSION_PCT", "13"))
TARGET_MARGIN_PCT = float(os.getenv("TARGET_MARGIN_PCT", "25"))
CJ_COUNTRY_CODE = os.getenv("CJ_COUNTRY_CODE", "FR").strip().upper()

DEFAULT_KEYWORDS = (
    "home gadget,kitchen gadget,phone accessory,car accessory,"
    "fitness accessory,pet accessory,beauty accessory,desk accessory,"
    "travel accessory,storage organizer"
)
KEYWORDS = [x.strip() for x in os.getenv("CJ_KEYWORDS", DEFAULT_KEYWORDS).split(",") if x.strip()]
MIN_STOCK = int(os.getenv("CJ_MIN_STOCK", "1"))
MIN_COST_USD = float(os.getenv("CJ_MIN_COST_USD", "1"))
MAX_COST_USD = float(os.getenv("CJ_MAX_COST_USD", "35"))
PAGE_SIZE = min(int(os.getenv("CJ_PAGE_SIZE", "50")), 100)
PAGES_PER_KEYWORD = max(1, int(os.getenv("CJ_PAGES_PER_KEYWORD", "1")))
ESTIMATED_SHIPPING_USD = max(0.0, float(os.getenv("ESTIMATED_SHIPPING_USD", "0")))
REQUEST_TIMEOUT = int(os.getenv("CJ_REQUEST_TIMEOUT", "30"))
REQUEST_RETRIES = max(1, int(os.getenv("CJ_REQUEST_RETRIES", "4")))
CJ_MIN_INTERVAL_SECONDS = max(1.05, float(os.getenv("CJ_MIN_INTERVAL_SECONDS", "1.25")))

OUTPUT_SELECTED = Path("selected_products.csv")
OUTPUT_DRAFTS = Path("draft_listings.csv")
OUTPUT_CANDIDATES = Path("cj_candidates.csv")

BLOCKED_TERMS = [
    "weapon", "firearm", "gun", "rifle", "pistol", "ammunition", "ammo",
    "knife", "switchblade", "sword", "taser", "pepper spray", "mace",
    "explosive", "firework", "drug", "cannabis", "marijuana", "thc", "cbd",
    "nicotine", "vape", "cigarette", "tobacco", "prescription", "steroid",
    "counterfeit", "replica", "fake rolex",
]
BLOCKED_BRANDS = [
    "nike", "adidas", "apple", "samsung", "gucci", "louis vuitton",
    "chanel", "rolex", "dyson", "lego", "disney",
]


def log(message: str) -> None:
    print(f"[Resell AI] {message}", flush=True)


def fail(message: str, code: int = 1) -> None:
    print(f"[Resell AI] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        text = str(value).strip().replace(",", ".")
        if "-" in text and not text.startswith("-"):
            text = text.split("-", 1)[0]
        return float(text)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def calculate_sale_price(cost: float) -> float:
    denominator = 1 - COMMISSION_PCT / 100 - TARGET_MARGIN_PCT / 100
    if denominator <= 0:
        raise ValueError("COMMISSION_PCT + TARGET_MARGIN_PCT must be below 100")
    return round((cost + ESTIMATED_SHIPPING_USD) / denominator, 2)


def calculate_metrics(cost: float, sale_price: float) -> tuple[float, float]:
    fee = sale_price * COMMISSION_PCT / 100
    profit = sale_price - fee - cost - ESTIMATED_SHIPPING_USD
    margin = profit / sale_price * 100 if sale_price else 0
    return round(profit, 2), round(margin, 2)


def get_access_token(session: requests.Session, api_key: str) -> str:
    """Exchange the CJ API key for the short-lived API access token used by V2 endpoints."""
    url = f"{BASE_URL}/authentication/getAccessToken"
    r = session.post(url, json={"apiKey": api_key}, timeout=REQUEST_TIMEOUT)
    try:
        payload = r.json()
    except ValueError as exc:
        raise RuntimeError(f"CJ authentication returned non-JSON HTTP {r.status_code}") from exc
    if r.status_code >= 400 or payload.get("result") is False:
        raise RuntimeError(
            f"CJ authentication failed (HTTP {r.status_code}, code={payload.get('code')}): "
            f"{payload.get('message', 'Unknown error')}"
        )
    token = clean_text((payload.get("data") or {}).get("accessToken"))
    if not token:
        raise RuntimeError("CJ authentication succeeded but no accessToken was returned.")
    return token


_last_cj_request_at = 0.0


def _wait_for_cj_slot() -> None:
    global _last_cj_request_at
    elapsed = time.monotonic() - _last_cj_request_at
    if elapsed < CJ_MIN_INTERVAL_SECONDS:
        time.sleep(CJ_MIN_INTERVAL_SECONDS - elapsed)
    _last_cj_request_at = time.monotonic()


def cj_get(session: requests.Session, path: str, params: dict[str, Any]) -> dict:
    last_error = None
    for attempt in range(1, REQUEST_RETRIES + 1):
        try:
            # CJ Free accounts are currently limited to about 1 authenticated
            # request/second, so serialize calls with a safety gap.
            _wait_for_cj_slot()
            r = session.get(f"{BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                last_error = RuntimeError(f"HTTP 429 rate limit: {r.text[:300]}")
                if attempt < REQUEST_RETRIES:
                    wait = max(4, 2 ** attempt)
                    log(f"CJ rate limit (429); waiting {wait}s before retry {attempt + 1}/{REQUEST_RETRIES}")
                    time.sleep(wait)
                    continue
                break
            r.raise_for_status()
            payload = r.json()
            if payload.get("result") is False:
                code = payload.get("code")
                message = payload.get("message")
                # Some CJ responses use an application-level rate-limit code.
                if str(code) in {"402", "406", "429", "1600200", "1600201"} and attempt < REQUEST_RETRIES:
                    wait = max(4, 2 ** attempt)
                    last_error = RuntimeError(f"CJ rate limit {code}: {message}")
                    log(f"CJ rate limit ({code}); waiting {wait}s before retry {attempt + 1}/{REQUEST_RETRIES}")
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"CJ error {code}: {message}")
            return payload
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < REQUEST_RETRIES:
                wait = max(2, 2 ** (attempt - 1))
                log(f"API request failed; retrying in {wait}s: {exc}")
                time.sleep(wait)
    raise RuntimeError(f"CJ API request failed: {last_error}")


def extract_products(payload: dict) -> list[dict]:
    data = payload.get("data") or {}
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    products: list[dict] = []
    for block in data.get("content", []) if isinstance(data, dict) else []:
        if isinstance(block, dict) and isinstance(block.get("productList"), list):
            products.extend(x for x in block["productList"] if isinstance(x, dict))
    if not products and isinstance(data, dict) and isinstance(data.get("productList"), list):
        products = [x for x in data["productList"] if isinstance(x, dict)]
    return products


def search_cj(session: requests.Session) -> list[dict]:
    candidates, seen = [], set()
    total_calls = len(KEYWORDS) * PAGES_PER_KEYWORD
    call_number = 0
    for keyword in KEYWORDS:
        for page in range(1, PAGES_PER_KEYWORD + 1):
            call_number += 1
            log(f'CJ search {call_number}/{total_calls}: "{keyword}" page {page}')
            params = {
                "page": page, "size": PAGE_SIZE, "keyWord": keyword,
                "countryCode": CJ_COUNTRY_CODE,
                "startSellPrice": MIN_COST_USD,
                "endSellPrice": MAX_COST_USD,
                "startWarehouseInventory": MIN_STOCK,
                "features": ["enable_description", "enable_category"],
            }
            products = extract_products(cj_get(session, "/product/listV2", params))
            if not products:
                break
            for product in products:
                pid = clean_text(product.get("id"))
                if pid and pid not in seen:
                    seen.add(pid)
                    product["_search_keyword"] = keyword
                    candidates.append(product)
            if len(products) < PAGE_SIZE:
                break
    return candidates


def normalize_product(product: dict) -> dict | None:
    name = clean_text(product.get("nameEn"))
    pid = clean_text(product.get("id"))
    spu = clean_text(product.get("spu") or product.get("sku"))
    cost = to_float(product.get("nowPrice") or product.get("discountPrice") or product.get("sellPrice"))
    stock = max(to_int(product.get("totalVerifiedInventory")), to_int(product.get("warehouseInventoryNum")))
    category = clean_text(product.get("threeCategoryName") or product.get("twoCategoryName") or product.get("oneCategoryName"))
    if not pid or not name or cost <= 0 or stock < MIN_STOCK or not (MIN_COST_USD <= cost <= MAX_COST_USD):
        return None
    combined = " ".join([name, category, clean_text(product.get("description"))]).lower()
    if any(term in combined for term in BLOCKED_TERMS) or any(brand in combined for brand in BLOCKED_BRANDS):
        return None
    if to_int(product.get("customization")) == 1:
        return None
    sale_status = clean_text(product.get("saleStatus"))
    if sale_status and sale_status != "3":
        return None
    sale_price = calculate_sale_price(cost)
    profit, margin = calculate_metrics(cost, sale_price)
    if profit <= 0 or margin < TARGET_MARGIN_PCT:
        return None
    listed_num = to_int(product.get("listedNum"))
    verified = to_int(product.get("totalVerifiedInventory"))
    free_shipping = to_int(product.get("addMarkStatus")) == 1
    score = round(
        min(profit / max(cost, 1), 5) * 35
        + min(verified / 500, 1) * 25
        + 20 / (1 + listed_num / 50)
        + (10 if free_shipping else 0)
        + (10 if clean_text(product.get("deliveryCycle")) else 0),
        2,
    )
    return {
        "product_id": pid, "spu": spu, "name": name, "category": category,
        "cost_usd": round(cost, 2), "estimated_shipping_usd": round(ESTIMATED_SHIPPING_USD, 2),
        "suggested_sale_price_usd": sale_price, "estimated_profit_usd": profit,
        "estimated_margin_pct": margin, "commission_pct": COMMISSION_PCT,
        "target_margin_pct": TARGET_MARGIN_PCT, "stock": stock, "verified_stock": verified,
        "listed_num": listed_num, "free_shipping": free_shipping,
        "delivery_cycle_days": clean_text(product.get("deliveryCycle")),
        "has_ce_certification": bool(to_int(product.get("hasCECertification"))),
        "image_url": clean_text(product.get("bigImage")),
        "search_keyword": clean_text(product.get("_search_keyword")),
        "score": score, "pricing_note": "Estimated before final shipping quote",
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_drafts(selected: list[dict]) -> None:
    rows = []
    for p in selected:
        rows.append({
            "sku": f"CJ-{p['product_id']}",
            "product_id": p["product_id"],
            "title": clean_text(p["name"])[:80],
            "description": (
                f"{p['name']}. Practical {p['category'].lower() if p['category'] else 'everyday'} product. "
                f"Estimated CJ delivery cycle: {p['delivery_cycle_days'] or 'standard'} days. "
                "Availability and price are checked during each worker run. "
                "Verify final shipping cost and marketplace compliance before publishing."
            ),
            "price_usd": p["suggested_sale_price_usd"],
            "quantity": max(1, min(p["stock"], 10)),
            "image_url": p["image_url"],
            "source": "CJdropshipping", "status": "DRAFT_ONLY", "publish_platform": "NOT_CONNECTED",
        })
    write_csv(OUTPUT_DRAFTS, rows)


def main() -> None:
    if not CJ_API_KEY:
        fail("CJ_API_KEY/CJ_ACCESS_TOKEN is missing. Add the CJ API key as a GitHub Actions repository secret.")
    if COMMISSION_PCT + TARGET_MARGIN_PCT >= 100:
        fail("COMMISSION_PCT + TARGET_MARGIN_PCT must be below 100.")
    if not KEYWORDS:
        fail("CJ_KEYWORDS is empty.")

    log(f"Starting real CJ search: country={CJ_COUNTRY_CODE}, target={MAX_PRODUCTS}")
    log(f"Keywords={len(KEYWORDS)}, price=${MIN_COST_USD:.2f}-${MAX_COST_USD:.2f}, min stock={MIN_STOCK}")

    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "ResellAI/2.1",
    })

    log("Authenticating with CJ API key...")
    access_token = get_access_token(session, CJ_API_KEY)
    session.headers.update({"CJ-Access-Token": access_token})
    log("CJ authentication OK.")

    raw = search_cj(session)
    log(f"Raw unique products received: {len(raw)}")
    normalized = [x for x in (normalize_product(p) for p in raw) if x is not None]
    normalized.sort(key=lambda x: x["score"], reverse=True)

    selected, seen = [], set()
    for item in normalized:
        identity = item["spu"] or item["product_id"]
        if identity in seen:
            continue
        seen.add(identity)
        selected.append(item)
        if len(selected) >= MAX_PRODUCTS:
            break

    for rank, item in enumerate(selected, 1):
        item["rank"] = rank

    write_csv(OUTPUT_CANDIDATES, normalized)
    write_csv(OUTPUT_SELECTED, selected)
    write_drafts(selected)

    log(f"Selected: {len(selected)}")
    log(f"Wrote {OUTPUT_SELECTED}, {OUTPUT_DRAFTS}, {OUTPUT_CANDIDATES}")
    if not selected:
        fail("No products passed filters. Adjust CJ_MAX_COST_USD, CJ_MIN_STOCK or CJ_KEYWORDS.")
    log("Done. This worker selects products only; it does not publish listings or place orders.")


if __name__ == "__main__":
    main()
