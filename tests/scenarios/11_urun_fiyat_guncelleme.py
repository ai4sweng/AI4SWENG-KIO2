discount_rate = 0.15

def apply_global_discount(price):
    # HATA: Fonksiyon içinde discount_rate değişkenine atama yapılmaya çalışılıyor.
    # Python bunu local değişken kabul eder ama atamadan önce okumaya çalıştığı için çöker.
    if price > 200:
        price = price - (price * discount_rate)
        discount_rate = 0.20  # Local tanım globali gölgeler
    return price

print(apply_global_discount(250))
