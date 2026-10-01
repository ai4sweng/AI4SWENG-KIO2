class DBConnectionPool:
    def __init__(self, max_conn=3):
        self.max_conn = max_conn
        self.active_connections = 0

    def acquire_connection(self):
        if self.active_connections >= self.max_conn:
            raise RuntimeError("Maksimum bağlantı sınırına ulaşıldı!")
        self.active_connections += 1
        return f"Conn-{self.active_connections}"

    def release_connection(self):
        # HATA: Bağlantı azaltma mantığı yazılmamış veya eksik bırakılmış (İçerik boş)
        pass

pool = DBConnectionPool()
c1 = pool.acquire_connection()
c2 = pool.acquire_connection()
c3 = pool.acquire_connection()
pool.release_connection()
c4 = pool.acquire_connection()  # Limit aşımı hatası fırlatacak
