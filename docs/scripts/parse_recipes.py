#!/usr/bin/env python3
"""
Парсит все KubeJS рецепты из server_scripts/ и генерирует recipes.json для сайта.
Запуск: python3 scripts/parse_recipes.py
"""

import re
import json
import os
import glob

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'minecraft_server', 'kubejs', 'server_scripts')
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'VOIDRP-SITE', 'src', 'data', 'recipes.json')

# Категории по папкам скриптов
FOLDER_CATEGORIES = {
    '00_core': 'Ядро',
    '01_vanilla': 'Ваниль',
    '02_food': 'Еда',
    '03_create': 'Create',
    '04_immersive_engineering': 'Immersive Engineering',
    '05_mekanism': 'Mekanism',
    '06_ae2': 'AE2',
    '07_industrial_foregoing': 'Industrial Foregoing',
    '08_magic': 'Магия',
    '09_endgame': 'Эндгейм',
    '10_avaritia': 'Avaritia',
    '11_progression_rebuild': 'Прогрессия',
    '99_progression_tracking': 'Прогрессия',
    '99_superhard': 'Сложные',
}

def parse_output(raw):
    raw = raw.strip()
    # Item.of('mod:item', count)
    m = re.match(r"Item\.of\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*(\d+)\s*\)", raw)
    if m:
        return m.group(1), int(m.group(2))
    # '2x mod:item'
    inner = raw.strip("'\"")
    m = re.match(r'^(\d+)x\s+(.+)$', inner)
    if m:
        return m.group(2).strip(), int(m.group(1))
    if ':' in inner or inner.startswith('#'):
        return inner, 1
    return None, 1

def parse_pattern(s):
    return re.findall(r"['\"]([^'\"]*)['\"]", s)

def parse_keys(s):
    keys = {}
    for m in re.finditer(r"([A-Za-z0-9])\s*:\s*['\"]([^'\"]+)['\"]", s):
        keys[m.group(1)] = m.group(2)
    return keys

def parse_inputs(s):
    return re.findall(r"['\"]([^'\"]+)['\"]", s)

def extract_block(text, start):
    """Извлечь содержимое блока скобок начиная с позиции открывающей скобки."""
    depth = 0
    i = start
    while i < len(text):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[start+1:i], i
        i += 1
    return None, -1

def split_top_level_args(s):
    """Разбить строку на аргументы верхнего уровня по запятым."""
    args = []
    depth = 0
    current = []
    for ch in s:
        if ch in '([{':
            depth += 1
            current.append(ch)
        elif ch in ')]}':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            args.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        args.append(''.join(current).strip())
    return args

def parse_shaped_call(args, category, source_file):
    """Парсит аргументы shaped рецепта: output, pattern, keys."""
    if len(args) < 3:
        return None
    output, count = parse_output(args[0])
    if not output:
        return None
    pattern = parse_pattern(args[1])
    if not pattern:
        return None
    keys = parse_keys(args[2])
    if not keys:
        return None
    return {
        'type': 'shaped',
        'output': output,
        'output_count': count,
        'pattern': pattern,
        'keys': keys,
        'category': category,
        'source': os.path.basename(source_file),
    }

def parse_shapeless_call(args, category, source_file):
    """Парсит аргументы shapeless рецепта: output, inputs."""
    if len(args) < 2:
        return None
    output, count = parse_output(args[0])
    if not output:
        return None
    inputs = parse_inputs(args[1])
    if not inputs:
        return None
    return {
        'type': 'shapeless',
        'output': output,
        'output_count': count,
        'inputs': inputs,
        'category': category,
        'source': os.path.basename(source_file),
    }

def get_category(filepath):
    parts = filepath.replace('\\', '/').split('/')
    for part in parts:
        if part in FOLDER_CATEGORIES:
            return FOLDER_CATEGORIES[part]
    return 'Другое'

def parse_file(filepath):
    recipes = []
    category = get_category(filepath)

    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()

    # Убираем однострочные комментарии
    text = re.sub(r'//[^\n]*', '', text)

    # --- vrpShaped / vrpExtraShaped ---
    for m in re.finditer(r'vrp(?:Extra)?Shaped\s*\(', text):
        block, end = extract_block(text, m.end() - 1)
        if block is None:
            continue
        args = split_top_level_args(block)
        # vrpShaped(event, output, pattern, keys, name)
        if len(args) >= 4:
            rec = parse_shaped_call(args[1:], category, filepath)
            if rec:
                # ID из последнего аргумента
                name_arg = args[-1].strip("'\" ")
                rec['id'] = 'voidrp:' + name_arg
                recipes.append(rec)

    # --- vrpShapeless / vrpExtraShapeless ---
    for m in re.finditer(r'vrp(?:Extra)?Shapeless\s*\(', text):
        block, end = extract_block(text, m.end() - 1)
        if block is None:
            continue
        args = split_top_level_args(block)
        # vrpShapeless(event, output, inputs, name)
        if len(args) >= 3:
            rec = parse_shapeless_call(args[1:], category, filepath)
            if rec:
                name_arg = args[-1].strip("'\" ")
                rec['id'] = 'voidrp:' + name_arg
                recipes.append(rec)

    # --- event.shaped ---
    for m in re.finditer(r'event\.shaped\s*\(', text):
        block, end = extract_block(text, m.end() - 1)
        if block is None:
            continue
        args = split_top_level_args(block)
        # Пропускаем event.recipes.create.* и т.п.
        if len(args) < 3:
            continue
        rec = parse_shaped_call(args, category, filepath)
        if rec:
            # Ищем .id('...') после закрывающей скобки
            after = text[end:]
            id_m = re.match(r'\s*\.id\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', after)
            if id_m:
                rec['id'] = id_m.group(1)
            recipes.append(rec)

    # --- event.shapeless ---
    for m in re.finditer(r'event\.shapeless\s*\(', text):
        block, end = extract_block(text, m.end() - 1)
        if block is None:
            continue
        args = split_top_level_args(block)
        if len(args) < 2:
            continue
        # Пропускаем event.recipes.* паттерны (у них нет простого массива)
        rec = parse_shapeless_call(args, category, filepath)
        if rec:
            after = text[end:]
            id_m = re.match(r'\s*\.id\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)', after)
            if id_m:
                rec['id'] = id_m.group(1)
            recipes.append(rec)

    return recipes

def main():
    all_recipes = []
    seen_ids = set()

    js_files = sorted(glob.glob(os.path.join(SCRIPTS_DIR, '**', '*.js'), recursive=True))
    # Пропускаем файл удаления рецептов
    js_files = [f for f in js_files if '20_remove_recipes' not in f and '10_tags' not in f]

    for filepath in js_files:
        try:
            recipes = parse_file(filepath)
            for r in recipes:
                rid = r.get('id', '')
                if rid and rid in seen_ids:
                    continue
                # Пропускаем рецепты с шаблонными строками JS (${...})
                if '${' in str(r.get('output', '')) or '${' in rid:
                    continue
                seen_ids.add(rid)
                all_recipes.append(r)
        except Exception as e:
            print(f'  Ошибка в {filepath}: {e}')

    # Сортируем по категории, потом по id
    all_recipes.sort(key=lambda r: (r.get('category', ''), r.get('id', '')))

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump({'recipes': all_recipes}, f, ensure_ascii=False, indent=2)

    print(f'Готово: {len(all_recipes)} рецептов → {OUTPUT_FILE}')

    # Статистика по категориям
    from collections import Counter
    cats = Counter(r['category'] for r in all_recipes)
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f'  {cat}: {count}')

if __name__ == '__main__':
    main()
