#!/usr/bin/env python3
"""
Извлекает текстуры предметов из JAR-файлов модов → VOIDRP-SITE/public/item-icons/{modid}/{name}.png
Запуск: python3 scripts/extract_item_textures.py
"""

import os
import shutil
import zipfile
import glob

MODS_DIR = os.path.join(os.path.dirname(__file__), '..', 'minecraft_server', 'mods')
KUBEJS_TEXTURES = os.path.join(os.path.dirname(__file__), '..', 'minecraft_server', 'kubejs', 'assets', 'kubejs', 'textures', 'item')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'VOIDRP-SITE', 'public', 'item-icons')

def extract_mod_textures(jar_path, output_base):
    modid = None
    extracted = 0
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            names = zf.namelist()
            # Определяем modid по структуре assets/
            for name in names:
                if name.startswith('assets/') and name.count('/') >= 2:
                    parts = name.split('/')
                    candidate = parts[1]
                    if candidate and candidate != 'minecraft' and candidate != 'pack.png':
                        modid = candidate
                        break
            if not modid:
                return 0

            out_dir = os.path.join(output_base, modid)
            os.makedirs(out_dir, exist_ok=True)

            for name in names:
                # assets/{modid}/textures/item/{name}.png
                if (name.startswith(f'assets/{modid}/textures/item/') and
                        name.endswith('.png') and not name.endswith('/')):
                    item_name = os.path.basename(name)
                    out_path = os.path.join(out_dir, item_name)
                    if not os.path.exists(out_path):
                        with zf.open(name) as src, open(out_path, 'wb') as dst:
                            dst.write(src.read())
                        extracted += 1
    except (zipfile.BadZipFile, Exception):
        pass
    return extracted

def copy_kubejs_textures(kubejs_src, output_base):
    out_dir = os.path.join(output_base, 'kubejs')
    os.makedirs(out_dir, exist_ok=True)
    copied = 0
    if not os.path.exists(kubejs_src):
        return 0
    for fname in os.listdir(kubejs_src):
        if fname.endswith('.png'):
            src = os.path.join(kubejs_src, fname)
            dst = os.path.join(out_dir, fname)
            shutil.copy2(src, dst)
            copied += 1
    return copied

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # KubeJS кастомные иконки
    copied = copy_kubejs_textures(KUBEJS_TEXTURES, OUTPUT_DIR)
    print(f'KubeJS: {copied} текстур скопировано')

    # Моды
    jar_files = glob.glob(os.path.join(MODS_DIR, '*.jar'))
    total = 0
    for jar_path in sorted(jar_files):
        count = extract_mod_textures(jar_path, OUTPUT_DIR)
        if count > 0:
            jar_name = os.path.basename(jar_path)
            print(f'  {jar_name}: {count} текстур')
            total += count

    print(f'\nГотово: {total} текстур из модов + {copied} KubeJS → {OUTPUT_DIR}')

if __name__ == '__main__':
    main()
