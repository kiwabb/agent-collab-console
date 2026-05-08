import os
import re

def fix_file(path):
    with open(path, 'r') as f:
        content = f.read()
    
    # 1. Fix double awaits (recursive)
    old_content = ""
    while content != old_content:
        old_content = content
        content = re.sub(r'await\s+await\s+', 'await ', content)
    
    # 2. Fix the "bawait bootstrap_module" and similar
    content = re.sub(r'await [a-z]await ([a-z_]+)', r'await \1', content)
    content = content.replace('await bstrap_module', 'await bootstrap_module')
    content = content.replace('await otstrap_module', 'await bootstrap_module')
    content = content.replace('await odex_store', 'await codex_store')
    content = content.replace('await session_service', 'await session_service')

    # 3. Fix Parentheses
    # First, flatten all multiple parens for await calls
    content = re.sub(r'\(+\s*await\s+(.*?)\s*\)+\.json\(\)', r'(await \1).json()', content)
    content = re.sub(r'\(+\s*await\s+(.*?)\s*\)+\.status_code', r'(await \1).status_code', content)
    
    # 4. Fix signatures
    content = re.sub(r'async def test_(.*?)\(self, async_client\):', r'async def test_\1(self, async_client):', content)

    with open(path, 'w') as f:
        f.write(content)

for root, dirs, files in os.walk('tests'):
    for file in files:
        if file.endswith('.py'):
            fix_file(os.path.join(root, file))
