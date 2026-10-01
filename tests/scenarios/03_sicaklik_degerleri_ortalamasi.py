def get_average_temperature(readings):
    if not readings:
        return 0
    valid_readings = [t for t in readings if -50 <= t <= 60]
    if len(valid_readings) == 0:
        return 0
    return sum(valid_readings) / len(valid_readings)
sensor_data = [22.5, 23.0, 100.0, 21.8, -10.0]
avg_temp = get_average_temperature(sensor_data)
print(f"Ortalama Sıcaklık: {avg_temp}")
