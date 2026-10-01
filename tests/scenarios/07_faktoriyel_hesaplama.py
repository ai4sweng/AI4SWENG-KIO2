def recursive_factorial(n):
    # HATA: Taban durumu (Base case) yanlış tanımlanmış ya da eksik.
    # n == 1 yerine n == 0 unutulmuş ve negatif sayılar veya hatalı azaltma durumunda sonsuz döngü.
    if n == 1:
        return 1
    return n * recursive_factorial(n - 1)

# Negatif veya 0 parametre verilmesi durumunda:
print(recursive_factorial(0))
