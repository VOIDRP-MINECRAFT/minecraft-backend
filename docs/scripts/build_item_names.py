#!/usr/bin/env python3
"""
Извлекает ru_ru.json из всех модов → item_names.json для сайта.
Также обновляет KubeJS текстуры (перезаписывает).
Запуск: python3 scripts/build_item_names.py
"""

import json
import os
import glob
import zipfile
import shutil

MODS_DIR      = os.path.join(os.path.dirname(__file__), '..', 'minecraft_server', 'mods')
KUBEJS_TEXTURES = os.path.join(os.path.dirname(__file__), '..', 'minecraft_server', 'kubejs', 'assets', 'kubejs', 'textures', 'item')
ICONS_OUT     = os.path.join(os.path.dirname(__file__), '..', 'VOIDRP-SITE', 'public', 'item-icons')
NAMES_OUT = os.path.join(os.path.dirname(__file__), '..', 'VOIDRP-SITE', 'public', 'item_names.json')

def extract_names_from_jar(jar_path):
    names = {}
    try:
        with zipfile.ZipFile(jar_path, 'r') as zf:
            lang_files = [n for n in zf.namelist() if n.endswith('/lang/ru_ru.json')]
            for lang_path in lang_files:
                try:
                    data = json.loads(zf.read(lang_path).decode('utf-8'))
                    for key, value in data.items():
                        if key.startswith(('item.', 'block.')):
                            parts = key.split('.')
                            if len(parts) >= 3:
                                modid = parts[1]
                                item_key = '.'.join(parts[2:])
                                names[f'{modid}:{item_key}'] = value
                except Exception:
                    pass
    except Exception:
        pass
    return names

def update_kubejs_textures():
    out_dir = os.path.join(ICONS_OUT, 'kubejs')
    os.makedirs(out_dir, exist_ok=True)
    copied = 0
    if not os.path.exists(KUBEJS_TEXTURES):
        return 0
    for fname in os.listdir(KUBEJS_TEXTURES):
        if fname.endswith('.png'):
            shutil.copy2(os.path.join(KUBEJS_TEXTURES, fname), os.path.join(out_dir, fname))
            copied += 1
    return copied

def main():
    # Обновляем KubeJS текстуры (всегда перезаписываем)
    copied = update_kubejs_textures()
    print(f'KubeJS текстуры обновлены: {copied} файлов')

    # Собираем русские имена из всех модов
    all_names = {}
    jar_files = sorted(glob.glob(os.path.join(MODS_DIR, '*.jar')))
    for jar_path in jar_files:
        names = extract_names_from_jar(jar_path)
        all_names.update(names)
        if names:
            print(f'  {os.path.basename(jar_path)}: {len(names)} имён')

    os.makedirs(os.path.dirname(NAMES_OUT), exist_ok=True)
    with open(NAMES_OUT, 'w', encoding='utf-8') as f:
        json.dump(all_names, f, ensure_ascii=False, indent=2)

    print(f'\nГотово: {len(all_names)} имён предметов → {NAMES_OUT}')

if __name__ == '__main__':
    main()
