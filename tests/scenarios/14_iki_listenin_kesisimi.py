# HATA: Varsayılan argüman olarak liste ([]) kullanımı.
# Fonksiyon her çağrıldığında eski çağrılardan kalan veriler bu listede birikir!
def find_intersection(list_a, list_b, result_list=[]):
    for item in list_a:
        if item in list_b and item not in result_list:
            result_list.append(item)
    return result_list

res1 = find_intersection([1, 2, 3], [2, 3, 4])  # Beklenen: [2, 3]
res2 = find_intersection([5, 6], [6, 7])  # Beklenen: [6] ama [2, 3, 6] döner!
print("Çağrı 2 Çıktısı:", res2)
