"""Fix Chinese curly quotes in JS file to avoid JS parser confusion"""
with open('generate_pending_docx.js', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace Chinese curly double quotes with straight quotes (inside JS strings they won't break parsing)
# U+201C = " (LEFT DOUBLE QUOTATION MARK)
# U+201D = " (RIGHT DOUBLE QUOTATION MARK)
count_l = content.count('“')
count_r = content.count('”')
print(f'Found {count_l} left and {count_r} right Chinese curly double quotes')

# Replace with no-width equivalents that look similar but won't confuse JS
content = content.replace('“', '『')  # 『
content = content.replace('”', '』')  # 』

with open('generate_pending_docx.js', 'w', encoding='utf-8') as f:
    f.write(content)
print('Fixed')
