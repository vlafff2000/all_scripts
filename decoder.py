# -*- coding: utf-8 -*-

# Читаем файл в бинарном режиме (так мы не теряем оригинальные байты)
with open('/home/ev_fomichev@VNG/Касимовское ПХГ/Промысловая информация/Исследования скважин/ГИС-Контроль/Контроль осень 2025/1 Касимов/1Касимов_201025-РК.las', 'rb') as f:
    raw_bytes = f.read()

print("Пробуем декодировать как UTF-8:")
try:
    print(raw_bytes.decode('utf-8'))
except:
    print("Не UTF-8")

print("\nПробуем как Windows-1251:")
try:
    print(raw_bytes.decode('cp1251'))
except:
    print("Не cp1251")

print("\nПробуем перекодировать (cp1251 → utf-8):")
try:
    # Если файл в cp1251, а мы хотим utf-8
    text_cp1251 = raw_bytes.decode('cp1251')
    bytes_utf8 = text_cp1251.encode('utf-8')
    print(bytes_utf8.decode('utf-8'))
except:
    print("Ошибка")

print("\nСпециально для вашего случая (cp1251 → utf-8):")
try:
    # Ваш текст скорее всего был в cp1251, но отображается как кракозябры
    # Значит нужно сделать обратное преобразование
    fixed = raw_bytes.decode('cp1251')  # Если файл в cp1251
    print(fixed)
except:
    print("Ошибка")