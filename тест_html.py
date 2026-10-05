import json

wells = {"500": {"row": 5, "col": 3}, "501": {"row": 7, "col": 8}}

wells_js = json.dumps(wells, ensure_ascii=False)

html = '<!DOCTYPE html>\n<html>\n<head>\n<meta charset="UTF-8">\n</head>\n<body>\n'
html += '<div id="test"></div>\n'
html += '<script>\n'
html += 'const WELLS = ' + wells_js + ';\n'
html += 'document.getElementById("test").innerHTML = "Скважин: " + Object.keys(WELLS).length + "<br>";\n'
html += 'for (const w in WELLS) { document.getElementById("test").innerHTML += "Скв " + w + " row=" + WELLS[w].row + " col=" + WELLS[w].col + "<br>"; }\n'
html += '</script>\n</body>\n</html>'

with open('test.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Готово! Откройте test.html в браузере")