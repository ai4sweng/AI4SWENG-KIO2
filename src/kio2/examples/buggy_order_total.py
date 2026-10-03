"""A small buggy program used as KIO2's dummy failing input.

Bug: ``average_price`` divides by the number of *in-stock* items, but the
sample cart has no in-stock items, so ``len(prices) == 0`` → ZeroDivisionError.
The real fault is the empty-list guard that is missing on line ``return
total / len(prices)``.
"""


def average_price(items):
    prices = [it["price"] for it in items if it["in_stock"]]
    total = 0
    for p in prices:
        total += p
    return total / len(prices)  # ← fault: no guard for empty prices


def summarise_cart(items):
    avg = average_price(items)
    return {"count": len(items), "average_price": avg}


if __name__ == "__main__":
    cart = [
        {"name": "pen", "price": 3, "in_stock": False},
        {"name": "cup", "price": 8, "in_stock": False},
    ]
    print(summarise_cart(cart))
