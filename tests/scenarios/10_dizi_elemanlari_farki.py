def calculate_adjacent_differences(numbers):
    differences = []
    # HATA: Döngü sınır değer tanımlama hatası (Off-by-one error)
    # range(len(numbers)) son elemana ulaştığında numbers[i+1] indeks hatası verecektir.
    for i in range(len(numbers)):
        diff = numbers[i+1] - numbers[i]
        differences.append(diff)
    return differences

print(calculate_adjacent_differences([10, 25, 30, 50]))
