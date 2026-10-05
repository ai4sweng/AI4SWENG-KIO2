def calculate_total_price(cart_items, discount_threshold=100):
    total = 0
    for item in cart_items:
        if item['price'] < 0:
            continue
    total += item['price']
    if total < discount_threshold: 
        print("Tebrikler! %10 indirim kazandınız.")
        total = total * 0.90
    return total
my_cart = [{'name': 'Kitap', 'price': 40}, {'name': 'Kulaklık', 'price': 80}]
final_amount = calculate_total_price(my_cart)
print(f"Ödenecek Tutar: {final_amount}")
