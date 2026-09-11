#!/usr/bin/env python3
"""Generate a realistic BThrifty Online packing slip and print to thermal label."""

import fitz
import subprocess
import uuid
from datetime import datetime

ORDER_NUM = f"BTO-{uuid.uuid4().hex[:8].upper()}"
ORDER_DATE = datetime.now().strftime("%m/%d/%Y")
SHIP_DATE = datetime.now().strftime("%m/%d/%Y")

# Items priced like BThrifty second-hand (NWT = New With Tags, NWOT = New Without Tags, EUC = Excellent Used Condition)
# Total should come out to ~$48
ITEMS = [
    ("SKU-48231", "Girls Floral Dress",          "5-6",  "NWT",  8.49),
    ("SKU-48232", "Girls Stripe Sundress",         "5-6",  "NWT",  7.49),
    ("SKU-39117", "Girls One-Piece Swimsuit",      "5-6",  "NWT",  5.99),
    ("SKU-29088", "Boys Swim Trunks",              "2T",   "NWT",  5.49),
    ("SKU-29089", "Boys Swim Top (Rash Guard)",    "2T",   "NWT",  5.99),
    ("SKU-55210", "Boys Graphic Tee",              "2T",   "EUC",  4.99),
    ("SKU-55211", "Boys Cargo Shorts",             "2T",   "NWT",  5.49),
]

SUBTOTAL = sum(i[4] for i in ITEMS)
SHIPPING = 0.00
TAX = round(SUBTOTAL * 0.07, 2)
TOTAL = round(SUBTOTAL + SHIPPING + TAX, 2)

# 4x6 label in points
W, H = 288, 432

doc = fitz.open()
page = doc.new_page(width=W, height=H)

DARK = (0, 0, 0)
GRAY = (0.35, 0.35, 0.35)
LIGHT_GRAY = (0.6, 0.6, 0.6)
WHITE = (1, 1, 1)
GREEN = (0.09, 0.55, 0.24)  # #16a34a — BThrifty green accent

# ── Logo ──
logo_rect = fitz.Rect(10, 6, 150, 36)
page.insert_image(logo_rect, filename="/tmp/b-thrifty.png")

# Order number top-right
page.insert_text(fitz.Point(W - 8, 14), "ORDER", fontsize=5, fontname="helv", color=LIGHT_GRAY)
page.insert_text(fitz.Point(W - 8, 22), ORDER_NUM, fontsize=6, fontname="helv", color=DARK)
page.insert_text(fitz.Point(W - 8, 32), ORDER_DATE, fontsize=5, fontname="helv", color=GRAY)

# URL
page.insert_text(fitz.Point(155, 32), "bthriftyonline.com", fontsize=5, fontname="helv", color=LIGHT_GRAY)

# ── Thin green accent line ──
y = 40
shape = page.new_shape()
shape.draw_line(fitz.Point(0, y), fitz.Point(W, y))
shape.finish(color=GREEN, width=1.5)
shape.commit()

# ── Ship To ──
y = 48
page.insert_text(fitz.Point(10, y), "SHIP TO", fontsize=5, fontname="helv", color=LIGHT_GRAY)
y += 9
page.insert_text(fitz.Point(10, y), "Martha Guadalupe Andrade Reyes", fontsize=6.5, fontname="helv", color=DARK)

# ── Order/Ship info right side ──
page.insert_text(fitz.Point(175, 48), "Order Date", fontsize=4.5, fontname="helv", color=LIGHT_GRAY)
page.insert_text(fitz.Point(175, 55), ORDER_DATE, fontsize=5, fontname="helv", color=DARK)
page.insert_text(fitz.Point(240, 48), "Ship Date", fontsize=4.5, fontname="helv", color=LIGHT_GRAY)
page.insert_text(fitz.Point(240, 55), SHIP_DATE, fontsize=5, fontname="helv", color=DARK)

# ── Divider ──
y = 70
shape2 = page.new_shape()
shape2.draw_line(fitz.Point(10, y), fitz.Point(W - 10, y))
shape2.finish(color=(0.85, 0.85, 0.85), width=0.4)
shape2.commit()

# ── Column headers ──
y = 78
page.insert_text(fitz.Point(10, y), "ITEM", fontsize=5.5, fontname="helv", color=LIGHT_GRAY)
page.insert_text(fitz.Point(60, y), "DESCRIPTION", fontsize=5.5, fontname="helv", color=LIGHT_GRAY)
page.insert_text(fitz.Point(185, y), "SIZE", fontsize=5.5, fontname="helv", color=LIGHT_GRAY)
page.insert_text(fitz.Point(215, y), "COND.", fontsize=5.5, fontname="helv", color=LIGHT_GRAY)
page.insert_text(fitz.Point(252, y), "PRICE", fontsize=5.5, fontname="helv", color=LIGHT_GRAY)

y += 2
shape3 = page.new_shape()
shape3.draw_line(fitz.Point(10, y), fitz.Point(W - 10, y))
shape3.finish(color=(0.85, 0.85, 0.85), width=0.3)
shape3.commit()

# ── Item rows ──
y += 10
for sku, name, size, cond, price in ITEMS:
    page.insert_text(fitz.Point(10, y), sku, fontsize=6.5, fontname="helv", color=DARK)
    page.insert_text(fitz.Point(60, y), name, fontsize=6.5, fontname="helv", color=DARK)
    page.insert_text(fitz.Point(185, y), size, fontsize=6.5, fontname="helv", color=GRAY)
    page.insert_text(fitz.Point(215, y), cond, fontsize=6.5, fontname="helv", color=GRAY)
    page.insert_text(fitz.Point(252, y), f"${price:.2f}", fontsize=6.5, fontname="helv", color=DARK)
    y += 12

# ── Totals block ──
y += 4
shape4 = page.new_shape()
shape4.draw_line(fitz.Point(10, y), fitz.Point(W - 10, y))
shape4.finish(color=(0.85, 0.85, 0.85), width=0.4)
shape4.commit()

y += 10
page.insert_text(fitz.Point(178, y), "Subtotal", fontsize=6, fontname="helv", color=GRAY)
page.insert_text(fitz.Point(252, y), f"${SUBTOTAL:.2f}", fontsize=6, fontname="helv", color=DARK)
y += 10
page.insert_text(fitz.Point(178, y), "Shipping", fontsize=6, fontname="helv", color=GRAY)
page.insert_text(fitz.Point(252, y), "FREE", fontsize=6, fontname="helv", color=GREEN)
y += 10
page.insert_text(fitz.Point(178, y), "Tax", fontsize=6, fontname="helv", color=GRAY)
page.insert_text(fitz.Point(252, y), f"${TAX:.2f}", fontsize=6, fontname="helv", color=DARK)

y += 2
shape5 = page.new_shape()
shape5.draw_line(fitz.Point(178, y), fitz.Point(W - 10, y))
shape5.finish(color=DARK, width=0.5)
shape5.commit()

y += 11
page.insert_text(fitz.Point(178, y), "TOTAL", fontsize=8, fontname="helv", color=DARK)
page.insert_text(fitz.Point(242, y), f"${TOTAL:.2f}", fontsize=8, fontname="helv", color=DARK)

# ── Condition legend ──
y += 12
page.insert_text(fitz.Point(10, y), "NWT = New With Tags  |  EUC = Excellent Used Condition", fontsize=4.5, fontname="helv", color=LIGHT_GRAY)

# ── Footer ──
y = H - 20
shape6 = page.new_shape()
shape6.draw_line(fitz.Point(10, y), fitz.Point(W - 10, y))
shape6.finish(color=(0.85, 0.85, 0.85), width=0.3)
shape6.commit()

y += 8
page.insert_text(fitz.Point(10, y), "Thank you for shopping BThrifty!", fontsize=7, fontname="helv", color=GREEN)
page.insert_text(fitz.Point(W - 10, y), f"{len(ITEMS)} items", fontsize=5, fontname="helv", color=LIGHT_GRAY)
y += 8
page.insert_text(fitz.Point(10, y), "Returns? bthriftyonline.com/pqrs  |  Support: bthriftyonline.com/contact", fontsize=4, fontname="helv", color=LIGHT_GRAY)

# ── Save and print ──
out_path = f"/tmp/packing_slip_{ORDER_NUM}.pdf"
doc.save(out_path)
doc.close()
print(f"Saved: {out_path}")
print(f"Subtotal: ${SUBTOTAL:.2f} | Tax: ${TAX:.2f} | Total: ${TOTAL:.2f}")

result = subprocess.run(
    ["lp", "-d", "Y42BT_TSPL", "-o", "PageSize=w288h432", "-n", "2", out_path],
    capture_output=True, text=True,
)
if result.returncode == 0:
    print(f"Printed: {result.stdout.strip()}")
else:
    print(f"Print error: {result.stderr.strip()}")
