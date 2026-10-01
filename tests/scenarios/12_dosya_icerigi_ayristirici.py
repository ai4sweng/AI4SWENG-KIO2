def parse_config_lines(lines):
    config = {}
    for line in lines:
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        if "=" in cleaned:
            key, val = cleaned.split("=", 1)
            config[key.strip()] = val.strip()
    return config

raw_lines = ["# Ayarlar Dosyası", "port = 8080", "host = localhost", " ", "debug = true"]
print(parse_config_lines(raw_lines))
