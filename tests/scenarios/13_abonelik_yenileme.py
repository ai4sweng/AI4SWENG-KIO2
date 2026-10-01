def renew_subscription(user_profile):
    # HATA: Boolean ataması yerine yanlışlıkla karşılaştırma operatörü (==) kullanılmış.
    # Kullanıcının aktiflik durumu güncellenmez, durum havada kalır.
    if user_profile['has_paid']:
        user_profile['is_active'] == True
        print("Abonelik uzatıldı.")
    return user_profile

profile = {'name': 'Ali', 'has_paid': True, 'is_active': False}
print(renew_subscription(profile))
