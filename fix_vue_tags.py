import re
import os

pattern = re.compile(r'<([A-Z][a-zA-Z0-9-]*|el-[a-zA-Z0-9-]+)([^>]*?)\s*/>')

for filename in ['public/admin.html', 'public/app.html', 'public/platform.html']:
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = pattern.sub(r'<\1\2></\1>', content)
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(new_content)

print("Fixed tags")
