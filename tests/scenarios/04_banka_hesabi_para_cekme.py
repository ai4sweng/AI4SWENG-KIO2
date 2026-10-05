def withdraw_money(account, amount):
    
    if account['balance'] >= amount:
        print("Yetersiz bakiye!")
        return account['balance']
    
    account['balance'] -= amount
    return account['balance']

my_account = {'owner': 'Sergen', 'balance': 500}
withdraw_money(my_account, 150)
