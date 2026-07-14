#!/usr/bin/env python3
"""
Ищет и копирует недостающие иконки предметов из mod JAR-файлов.
Стратегия: item texture → block texture → fuzzy match по имени.
Запуск: python3 scripts/fetch_missing_icons.py
"""

import json, os, zipfile, glob, shutil, urllib.request

MODS_DIR   = os.path.join(os.path.dirname(__file__), '..', 'minecraft_server', 'mods')
ICONS_DIR  = os.path.join(os.path.dirname(__file__), '..', 'VOIDRP-SITE', 'public', 'item-icons')
RECIPES    = os.path.join(os.path.dirname(__file__), '..', 'VOIDRP-SITE', 'src', 'data', 'recipes.json')

# Явные переопределения JAR: modid → glob-шаблон относительно MODS_DIR
JAR_OVERRIDES = {
    'ae2':               'appliedenergistics2-*.jar',
    'bigreactors':       'ExtremeReactors2-*.jar',
    'create':            'create-[0-9]*.jar',        # avoid create-dyn-light-forge
    'draconicevolution': 'Draconic-Evolution-*.jar',
    'evolvedmekanism':   'Evolved Mekanism-*.jar',
    'farmersdelight':    'FarmersDelight-*.jar',
    'immersiveengineering': 'ImmersiveEngineering-*.jar',
    'naturescompass':    'NaturesCompass-*.jar',
    'sophisticatedbackpacks': 'sophisticatedbackpacks-*.jar',
    'toms_storage':      'toms_storage-*.jar',
}

# Ручные алиасы: modid:item_name → путь в JAR (без assets/{modid}/)
MANUAL_ALIASES = {
    # Immersive Engineering — префиксы
    'immersiveengineering:ingot_steel':     'textures/item/metal_ingot_steel.png',
    'immersiveengineering:ingot_electrum':  'textures/item/metal_ingot_electrum.png',
    'immersiveengineering:plate_steel':     'textures/item/metal_plate_steel.png',
    'immersiveengineering:wire_copper':     'textures/item/material_wire_copper.png',
    'immersiveengineering:wire_steel':      'textures/item/material_wire_steel.png',
    'immersiveengineering:wire_electrum':   'textures/item/material_wire_electrum.png',
    'immersiveengineering:component_iron':  'textures/item/material_component_iron.png',
    'immersiveengineering:component_steel': 'textures/item/material_component_steel.png',
    'immersiveengineering:coal_coke':       'textures/item/material_coal_coke.png',
    'immersiveengineering:stick_treated':   'textures/item/material_stick_treated.png',
    'immersiveengineering:circuit_board':   'textures/item/material_circuit_board.png',
    'immersiveengineering:treated_wood_horizontal': 'textures/block/treated_wood_horizontal.png',
    'immersiveengineering:treated_wood_vertical':   'textures/block/treated_wood_vertical.png',
    'immersiveengineering:treated_wood_packaged':   'textures/block/treated_wood_packaged.png',
    'immersiveengineering:blastbrick':          'textures/block/blastbrick.png',
    'immersiveengineering:blastbrick_reinforced': 'textures/block/blastbrick_reinforced.png',
    'immersiveengineering:cokebrick':           'textures/block/cokebrick.png',
    # Create — блочные текстуры
    'create:basin':             'textures/block/basin.png',
    'create:cogwheel':          'textures/block/cogwheel.png',
    'create:shaft':             'textures/block/shaft.png',
    'create:large_cogwheel':    'textures/block/large_cogwheel.png',
    'create:deployer':          'textures/block/deployer_pole.png',
    'create:crushing_wheel':    'textures/block/crushing_wheel.png',
    'create:mechanical_press':  'textures/block/mechanical_press_head.png',
    'create:mechanical_bearing':'textures/block/mechanical_bearing_side.png',
    'create:mechanical_saw':    'textures/block/mechanical_saw_blade.png',
    'create:andesite_casing':   'textures/block/andesite_casing.png',
    'create:brass_casing':      'textures/block/brass_casing.png',
    # AE2
    'ae2:controller':            'textures/block/controller_column_powered.png',
    'ae2:charger':               'textures/block/charger.png',
    'ae2:quantum_link':          'textures/block/quantum_link.png',
    'ae2:quantum_ring':          'textures/block/quantum_ring.png',
    'ae2:fluix_block':           'textures/block/fluix_block_empty.png',
    'ae2:drive':                 'textures/block/drive/drive_front.png',
    'ae2:inscriber':             'textures/block/inscriber_inside.png',
    'ae2:interface':             'textures/block/interface.png',
    'ae2:molecular_assembler':   'textures/block/molecular_assembler.png',
    'ae2:pattern_provider':      'textures/block/pattern_provider.png',
    'ae2:terminal':              'textures/item/wireless_terminal.png',
    'ae2:wireless_access_point': 'textures/block/wireless_access_point.png',
    'ae2:crafting_unit':         'textures/block/crafting/light_base.png',
    'ae2:256k_crafting_storage': 'textures/block/crafting/256k_storage.png',
    'ae2:64k_crafting_storage':  'textures/block/crafting/64k_storage.png',
    # Mekanism — блочные текстуры
    'mekanism:steel_casing':       'textures/block/steel_casing.png',
    'mekanism:basic_energy_cube':  'textures/block/models/energy_cube_basic_corner.png',
    'mekanism:basic_fluid_tank':   'textures/block/models/fluid_tank.png',
    'mekanism:basic_chemical_tank':'textures/block/models/chemical_tank.png',
    # Immersive Engineering — multiblocks & decorations
    'immersiveengineering:assembler':       'textures/block/multiblocks/assembler.png',
    'immersiveengineering:crusher':         'textures/block/multiblocks/crusher.png',
    'immersiveengineering:metal_press':     'textures/block/multiblocks/metal_press.png',
    'immersiveengineering:capacitor_lv':    'textures/block/metal_device/capacitor_lv_down_in.png',
    'immersiveengineering:capacitor_mv':    'textures/block/metal_device/capacitor_mv_down_in.png',
    'immersiveengineering:capacitor_hv':    'textures/block/metal_device/capacitor_hv_down_in.png',
    'immersiveengineering:heavy_engineering':'textures/block/metal_decoration/heavy_engineering.png',
    'immersiveengineering:light_engineering':'textures/block/metal_decoration/light_engineering.png',
    'immersiveengineering:rs_engineering':  'textures/block/metal_decoration/redstone_engineering.png',
    # bigreactors
    'bigreactors:basic_reactorcasing':      'textures/block/reactor/basic/casing_single.png',
    'bigreactors:basic_reactorcontroller':  'textures/block/reactor/basic/controller.png',
    # Draconic Evolution
    'draconicevolution:crafting_core':             'textures/block/crafting/crafting_core.png',
    'draconicevolution:energy_core':               'textures/block/energy_core.png',
    'draconicevolution:chaos_shard':               'textures/item/chaos_crystal.png',
    'draconicevolution:basic_crafting_injector':   'textures/block/crafting/injector_core_draconium.png',
    'draconicevolution:wyvern_crafting_injector':  'textures/block/crafting/injector_core_wyvern.png',
    'draconicevolution:awakened_crafting_injector':'textures/block/crafting/injector_core_draconic.png',
    'draconicevolution:chaotic_crafting_injector': 'textures/block/crafting/injector_core_chaotic.png',
    # Evolved Mekanism
    'evolvedmekanism:alloyer':                    'textures/block/alloyer/front.png',
    'evolvedmekanism:chemixer':                   'textures/block/chemixer/back.png',
    'evolvedmekanism:solidification_chamber':     'textures/block/solidification_chamber/back.png',
    'evolvedmekanism:thermalizer':                'textures/block/thermalizer/back.png',
    'evolvedmekanism:basic_alloying_factory':     'textures/block/factory/alloying/alloying_factory_front.png',
    'evolvedmekanism:advanced_alloying_factory':  'textures/block/factory/alloying/alloying_factory_front.png',
    'evolvedmekanism:dense_alloying_factory':     'textures/block/factory/alloying/alloying_factory_front.png',
    'evolvedmekanism:elite_alloying_factory':     'textures/block/factory/alloying/alloying_factory_front.png',
    'evolvedmekanism:multiversal_alloying_factory':'textures/block/factory/alloying/alloying_factory_front.png',
    'evolvedmekanism:overclocked_alloying_factory':'textures/block/factory/alloying/alloying_factory_front.png',
    'evolvedmekanism:quantum_alloying_factory':   'textures/block/factory/alloying/alloying_factory_front.png',
    'evolvedmekanism:ultimate_alloying_factory':  'textures/block/factory/alloying/alloying_factory_front.png',
    # Farmer's Delight
    'farmersdelight:cutting_board': 'textures/block/cutting_board.png',
    'farmersdelight:skillet':       'textures/block/skillet_top.png',
    'farmersdelight:stove':         'textures/block/stove_front.png',
    # Industrial Foregoing — machine frames
    'industrialforegoing:machine_frame_simple':   'textures/block/base/simple/top.png',
    'industrialforegoing:machine_frame_pity':     'textures/block/base/pity/top.png',
    'industrialforegoing:machine_frame_advanced': 'textures/block/base/advanced/top.png',
    'industrialforegoing:machine_frame_supreme':  'textures/block/base/supreme/top.png',
    'industrialforegoing:mob_crusher':            'textures/block/mob_slaughter_factory_side.png',
    'industrialforegoing:ore_laser_base':         'textures/block/laser_base_top.png',
    'industrialforegoing:plant_gatherer':         'textures/block/plant_interactor_front.png',
    # Mahou Tsukai
    'mahoutsukai:mana_circuit':         'textures/block/circuit1.png',
    'mahoutsukai:mana_circuit_magitech':'textures/block/circuit3.png',
    # Sophisticated Backpacks — use cloth texture as base
    'sophisticatedbackpacks:backpack':          'textures/block/backpack_cloth.png',
    'sophisticatedbackpacks:iron_backpack':     'textures/block/iron_clips.png',
    'sophisticatedbackpacks:gold_backpack':     'textures/block/gold_clips.png',
    'sophisticatedbackpacks:diamond_backpack':  'textures/block/diamond_clips.png',
    'sophisticatedbackpacks:netherite_backpack':'textures/block/netherite_clips.png',
    # Toms Storage
    'toms_storage:storage_terminal': 'textures/block/terminal_front.png',
    # Create — уточнённые пути (не совпадают с item_name напрямую)
    'create:shaft':             'textures/block/axis.png',
    'create:deployer':          'textures/block/deployer.png',
    'create:mechanical_crafter':'textures/block/crafter_side.png',
    'create:mechanical_mixer':  'textures/block/mixer_head.png',
    'create:mechanical_saw':    'textures/block/mechanical_saw_top.png',
    # Create Diesel Generators
    'createdieselgenerators:huge_diesel_engine': 'textures/block/diesel_engine_big.png',
    'createdieselgenerators:large_diesel_engine':'textures/block/diesel_engine_big.png',
    'createdieselgenerators:pumpjack_head':       'textures/block/pumpjack_bearing_top.png',
}

# Для vanilla — (item_name → block texture name) или True для item-пути
VANILLA_BLOCK_MAP = {
    'chest':        None,      # entity texture — нет PNG
    'ender_chest':  None,      # entity texture — нет PNG
    'piston':       'piston_top',
    'dispenser':    'dispenser_front',
    'dropper':      'dropper_front',
    'furnace':      'furnace_front',       # в репо без _off
    'smoker':       'smoker_front',        # в репо без _off
    'clock':        'clock_00',            # первый кадр анимации
    'compass':      'compass_00',          # первый кадр анимации
    'crossbow':     'crossbow_standby',    # item texture
    'shield':       None,                  # entity renderer — нет PNG
    'tripwire_hook': None,
    'dragon_egg':   None,
    'shulker_box':  None,
}

def get_mod_jar(modid):
    """Найти JAR по modid."""
    if modid in JAR_OVERRIDES:
        matches = glob.glob(os.path.join(MODS_DIR, JAR_OVERRIDES[modid]))
        if matches:
            return matches[0]
    patterns = [
        f'{modid}-[0-9]*.jar', f'{modid}_[0-9]*.jar',
        f'{modid[0].upper()}{modid[1:]}-[0-9]*.jar',
        f'{modid[0].upper()}{modid[1:]}[0-9]*.jar',
        f'{modid}-*.jar', f'{modid}_*.jar',
        f'{modid[0].upper()}{modid[1:]}-*.jar',
        f'*{modid}*.jar',
    ]
    for pat in patterns:
        matches = glob.glob(os.path.join(MODS_DIR, pat))
        if matches:
            return matches[0]
    return None

def extract_from_jar(jar_path, modid, asset_path, out_path):
    """Извлечь конкретный файл из JAR."""
    full = f'assets/{modid}/{asset_path}'
    try:
        with zipfile.ZipFile(jar_path) as zf:
            if full in zf.namelist():
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                with zf.open(full) as src, open(out_path, 'wb') as dst:
                    dst.write(src.read())
                return True
    except Exception:
        pass
    return False

def fuzzy_find(jar_path, modid, item_name):
    """Найти любую текстуру в JAR, содержащую item_name."""
    try:
        with zipfile.ZipFile(jar_path) as zf:
            candidates = [
                n for n in zf.namelist()
                if f'assets/{modid}/textures/' in n
                and item_name in n
                and n.endswith('.png')
                and not n.endswith('.mcmeta')
                and '/gui' not in n
                and 'particle' not in n
            ]
            # Предпочитаем item/ перед block/
            item_cands = [c for c in candidates if '/item/' in c]
            block_cands = [c for c in candidates if '/block/' in c]
            ordered = item_cands + block_cands + candidates
            if ordered:
                asset_rel = ordered[0].replace(f'assets/{modid}/', '')
                return asset_rel
    except Exception:
        pass
    return None

def try_vanilla_cdn(item_name, out_path):
    """Скачать ванильную текстуру с CDN."""
    base_item = 'https://raw.githubusercontent.com/InventivetalentDev/minecraft-assets/1.21.1/assets/minecraft/textures/item/{}.png'
    base_block = 'https://raw.githubusercontent.com/InventivetalentDev/minecraft-assets/1.21.1/assets/minecraft/textures/block/{}.png'
    # Прямые пути: item, block
    for url_tmpl in [base_item, base_block]:
        try:
            urllib.request.urlretrieve(url_tmpl.format(item_name), out_path)
            return True
        except Exception:
            pass
    # Маппинг из таблицы
    mapped = VANILLA_BLOCK_MAP.get(item_name)
    if mapped:
        for url_tmpl in [base_block, base_item]:
            try:
                urllib.request.urlretrieve(url_tmpl.format(mapped), out_path)
                return True
            except Exception:
                pass
    return False

def collect_missing():
    with open(RECIPES) as f:
        data = json.load(f)
    missing = set()
    for r in data['recipes']:
        candidates = [r['output']]
        if r['type'] == 'shaped':
            candidates += list(r.get('keys', {}).values())
        else:
            candidates += r.get('inputs', [])
        for item in candidates:
            if not item or item.startswith('#') or ':' not in item or item.startswith('`'):
                continue
            mod, name = item.split(':', 1)
            if not os.path.exists(os.path.join(ICONS_DIR, mod, name + '.png')):
                missing.add(item)
    return sorted(missing)

def main():
    missing = collect_missing()
    print(f'Отсутствует: {len(missing)} иконок\n')

    ok, fail = 0, []

    for item in missing:
        mod, name = item.split(':', 1)
        out_path = os.path.join(ICONS_DIR, mod, name + '.png')
        os.makedirs(os.path.join(ICONS_DIR, mod), exist_ok=True)

        # 1. Ручной алиас
        if item in MANUAL_ALIASES:
            jar = get_mod_jar(mod)
            if jar and extract_from_jar(jar, mod, MANUAL_ALIASES[item], out_path):
                print(f'  [alias] {item}')
                ok += 1
                continue

        # 2. Vanilla CDN
        if mod == 'minecraft':
            if try_vanilla_cdn(name, out_path):
                print(f'  [cdn]   {item}')
                ok += 1
                continue
            else:
                fail.append(item)
                continue

        jar = get_mod_jar(mod)
        if not jar:
            fail.append(f'{item} (jar not found)')
            continue

        # 3. Прямые пути: item/ → block/
        found = False
        for tex_path in [f'textures/item/{name}.png', f'textures/block/{name}.png']:
            if extract_from_jar(jar, mod, tex_path, out_path):
                print(f'  [direct] {item}')
                ok += 1
                found = True
                break

        if found:
            continue

        # 4. Fuzzy поиск
        asset_rel = fuzzy_find(jar, mod, name)
        if asset_rel and extract_from_jar(jar, mod, asset_rel, out_path):
            print(f'  [fuzzy] {item} ← {asset_rel}')
            ok += 1
            continue

        fail.append(item)

    print(f'\nНайдено: {ok}, не найдено: {len(fail)}')
    if fail:
        print('Не найдено:')
        for f in fail:
            print(f'  {f}')

if __name__ == '__main__':
    main()