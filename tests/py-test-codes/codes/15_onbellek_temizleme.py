def clear_expired_cache(cache_dict):
    # HATA: Sözlük üzerinde döngü dönerken sözlüğün boyutu değiştirilmeye (del) çalışılıyor.
    # Python buna çalışma zamanında izin vermez.
    for key, data in cache_dict.items():
        if data['expired']:
            del cache_dict[key]
    return cache_dict

my_cache = {
    "a": {"expired": False},
    "b": {"expired": True},
    "c": {"expired": True}
}
print(clear_expired_cache(my_cache))
