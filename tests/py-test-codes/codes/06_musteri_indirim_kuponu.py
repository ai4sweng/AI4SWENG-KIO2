def apply_coupon(price, coupon_code):
    # HATA: Giriş parametre tipi kontrol edilmeden string operasyonu yapılıyor
    # coupon_code tamsayı (int) gelirse .strip() metodu çökecektir.
    clean_code = coupon_code.strip().upper()
    if clean_code == "WINTER20":
        return price * 0.8
    return price

# Çağrı tarafında integer gönderiliyor
print(apply_coupon(200, 2026))
