import time

def log_sensor_readings(device_id, samples):
    log_entries = []
    for i, val in enumerate(samples):
        entry = {
            "timestamp": time.time(),
            "device": device_id,
            "sequence": i,
            "reading": val
        }
        log_entries.append(entry)
    return log_entries

readings = [14.2, 15.1, 14.9]
logs = log_sensor_readings("SENSOR-A", readings)
print(f"Toplam log: {len(logs)}")
