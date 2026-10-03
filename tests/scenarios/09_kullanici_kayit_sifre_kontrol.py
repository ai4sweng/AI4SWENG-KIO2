def validate_registration(username, password):
    if len(username) < 5:
        return "Geçersiz Kullanıcı Adı"
    # HATA: Şifre uzunluğu en az 8 olmalıyken mantıksal operatör hatası yapılmış.
    # length < 8 yerine > 8 yazıldığı için kısa şifreleri kabul edip uzun şifreleri reddediyor.
    if len(password) > 8:
        return "Şifre çok kısa!"
    return "Kayıt Başarılı"

print(validate_registration("ahmet_polat", "123"))
