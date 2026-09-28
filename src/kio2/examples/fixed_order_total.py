"""The corrected counterpart of ``buggy_order_total.py``.

Same program and same cart, with the missing guard added: an empty list of
in-stock prices yields no average instead of a ZeroDivisionError. KIO2 reports
this run as ``clean``, and its recording serves as the passing reference run
when the two executions are compared.
"""


def average_price(items):
    prices = [it["price"] for it in items if it["in_stock"]]
    total = 0
    for p in prices:
        total += p
    return total / len(prices) if prices else None


def summarise_cart(items):
    avg = average_price(items)
    return {"count": len(items), "average_price": avg}


if __name__ == "__main__":
    cart = [
        {"name": "pen", "price": 3, "in_stock": False},
        {"name": "cup", "price": 8, "in_stock": False},
    ]
    print(summarise_cart(cart))
