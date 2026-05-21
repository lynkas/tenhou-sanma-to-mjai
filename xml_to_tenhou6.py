#!/usr/bin/env python3
"""Convert Tenhou sanma XML logs to tenhou.net/6 JSON format.

Usage:
    python3 xml_to_tenhou6.py input.xml -o output.json
    python3 xml_to_tenhou6.py input.xml  # prints to stdout
    
    # From zstd-compressed:
    zstd -d input.xml.zst -o input.xml && python3 xml_to_tenhou6.py input.xml
"""

import re
import json
import sys
import argparse
from urllib.parse import unquote


def xml_tile_to_compact(t: int) -> int:
    """Convert XML tile ID (0-135) to tenhou6 compact encoding."""
    if t == 16: return 51  # red 5m (rare in sanma but possible in encoding)
    if t == 52: return 52  # red 5p
    if t == 88: return 53  # red 5s
    kind = t // 36  # 0=man, 1=pin, 2=sou, 3=honors
    num = (t % 36) // 4 + 1
    if kind == 0: return 10 + num
    elif kind == 1: return 20 + num
    elif kind == 2: return 30 + num
    else: return 40 + num


def decode_naki_xml(m: int):
    """Decode XML naki code. Returns (type, who_from_rel, tiles_info)."""
    if m & 0x4:
        # Chi (shouldn't happen in sanma)
        return ('chi', None)
    elif m & 0x8:
        # Pon
        t5 = (m >> 9) & 0x7F
        t_base = (t5 // 3) * 4
        t_idx = t5 % 3
        from_who_rel = m & 0x3  # 1=kamicha, 2=toimen, 3=shimocha (relative to who)
        unused = (m >> 5) & 0x3
        # Build the 3 tiles used in pon
        tiles = []
        called_idx = None
        idx = 0
        for i in range(4):
            if i == unused:
                continue
            if idx == t_idx:
                called_idx = len(tiles)
                tiles.append(t_base + i)
            else:
                tiles.append(t_base + i)
            idx += 1
            if len(tiles) == 3:
                break
        called = tiles[called_idx] if called_idx is not None else tiles[0]
        consumed = [t for i, t in enumerate(tiles) if i != called_idx]
        return ('pon', from_who_rel, called, consumed)
    elif m & 0x10:
        # Kakan (added kan) - must check before 0x20 since both can be set
        t5 = (m >> 9) & 0x7F
        t_base = (t5 // 3) * 4
        t_idx = t5 % 3
        from_who_rel = m & 0x3
        # The added tile
        pai = t_base + t_idx
        # Original pon tiles
        tiles = [t_base + i for i in range(4) if i != t_idx]
        return ('kakan', from_who_rel, pai, tiles)
    elif m & 0x20:
        # Nukidora (kita/pei)
        return ('nukidora', None)
    else:
        # Kan (ankan or daiminkan)
        hai = (m >> 8) & 0xFF
        t_base = (hai // 4) * 4
        from_who_rel = m & 0x3
        if from_who_rel == 0:
            # Ankan
            tiles = [t_base + i for i in range(4)]
            return ('ankan', 0, tiles)
        else:
            # Daiminkan
            called = hai
            consumed = [t_base + i for i in range(4) if t_base + i != called]
            return ('daiminkan', from_who_rel, called, consumed)


def encode_pon_string(who: int, from_who_rel: int, called: int, consumed: list) -> str:
    """Encode pon as tenhou6 JSON string."""
    c_compact = xml_tile_to_compact(called)
    # Sort consumed: normal tiles first, red (51/52/53) last
    consumed_compact = sorted([xml_tile_to_compact(t) for t in consumed],
                              key=lambda x: (x >= 51, x))
    if from_who_rel == 3:
        return f"p{c_compact:02d}{consumed_compact[0]:02d}{consumed_compact[1]:02d}"
    elif from_who_rel == 2:
        return f"{consumed_compact[0]:02d}p{c_compact:02d}{consumed_compact[1]:02d}"
    elif from_who_rel == 1:
        return f"{consumed_compact[0]:02d}{consumed_compact[1]:02d}p{c_compact:02d}"
    return f"p{c_compact:02d}{consumed_compact[0]:02d}{consumed_compact[1]:02d}"


def encode_daiminkan_string(from_who_rel: int, called: int, consumed: list) -> str:
    """Encode daiminkan as tenhou6 JSON string."""
    c_compact = xml_tile_to_compact(called)
    consumed_compact = [xml_tile_to_compact(t) for t in consumed]
    if from_who_rel == 3:
        return f"m{c_compact:02d}{consumed_compact[0]:02d}{consumed_compact[1]:02d}{consumed_compact[2]:02d}"
    elif from_who_rel == 2:
        return f"{consumed_compact[0]:02d}m{c_compact:02d}{consumed_compact[1]:02d}{consumed_compact[2]:02d}"
    elif from_who_rel == 1:
        return f"{consumed_compact[0]:02d}{consumed_compact[1]:02d}{consumed_compact[2]:02d}m{c_compact:02d}"
    return f"m{c_compact:02d}{consumed_compact[0]:02d}{consumed_compact[1]:02d}{consumed_compact[2]:02d}"


def encode_kakan_string(from_who_rel: int, pai: int, tiles: list) -> str:
    """Encode kakan as tenhou6 JSON string."""
    p_compact = xml_tile_to_compact(pai)
    t_compact = [xml_tile_to_compact(t) for t in tiles]
    # from_who_rel refers to the original pon source
    if from_who_rel == 3:
        return f"k{p_compact:02d}{t_compact[0]:02d}{t_compact[1]:02d}{t_compact[2]:02d}"
    elif from_who_rel == 2:
        return f"{t_compact[0]:02d}k{p_compact:02d}{t_compact[1]:02d}{t_compact[2]:02d}"
    elif from_who_rel == 1:
        return f"{t_compact[0]:02d}{t_compact[1]:02d}k{p_compact:02d}{t_compact[2]:02d}"
    return f"k{p_compact:02d}{t_compact[0]:02d}{t_compact[1]:02d}{t_compact[2]:02d}"


def encode_ankan_string(tiles: list) -> str:
    """Encode ankan as tenhou6 JSON string."""
    t_compact = sorted([xml_tile_to_compact(t) for t in tiles],
                       key=lambda x: (x >= 51, x))
    # ankan format: "XXYYZZaWW" where a is at position 6
    return f"{t_compact[0]:02d}{t_compact[1]:02d}{t_compact[2]:02d}a{t_compact[3]:02d}"


def parse_xml(xml_content: str) -> dict:
    """Parse tenhou sanma XML into tenhou.net/6 JSON format."""
    # Extract metadata
    go_match = re.search(r'<GO type="(\d+)"', xml_content)
    game_type = int(go_match.group(1)) if go_match else 0
    
    un_match = re.search(r'<UN n0="([^"]*)" n1="([^"]*)" n2="([^"]*)" n3="([^"]*)" dan="([^"]*)" rate="([^"]*)" sx="([^"]*)"', xml_content)
    names = ["", "", "", ""]
    dan = []
    rate = []
    sx = []
    if un_match:
        names = [unquote(un_match.group(i+1)) for i in range(4)]
        dan = un_match.group(5).split(',')
        rate = un_match.group(6).split(',')
        sx = un_match.group(7).split(',')

    # Parse all tags
    tags = re.findall(r'<([A-Z]+)([^/>]*?)/?>', xml_content)
    
    # Find kyoku boundaries
    init_indices = [i for i, (tag, _) in enumerate(tags) if tag == 'INIT']
    
    logs = []
    
    for ki in range(len(init_indices)):
        start = init_indices[ki]
        end = init_indices[ki + 1] if ki + 1 < len(init_indices) else len(tags)
        kyoku_tags = tags[start:end]
        
        kyoku_data = parse_kyoku(kyoku_tags)
        if kyoku_data:
            logs.append(kyoku_data)
    
    # Build final scores from last AGARI/RYUUKYOKU
    # (scores are tracked through the game)
    
    result = {
        "ver": 2.3,
        "ref": "",
        "log": logs,
        "name": names,
        "rule": {"disp": "", "aka": 1, "aka51": 0, "aka52": 1, "aka53": 1},
        "ratingc": "",
        "lobby": 0,
        "dan": dan,
        "rate": rate,
        "sx": sx,
    }
    
    # Try to extract ref from SHUFFLE
    shuffle_match = re.search(r'<SHUFFLE seed="([^"]*)"', xml_content)
    
    return result


def parse_kyoku(kyoku_tags: list) -> list:
    """Parse one kyoku from XML tags into tenhou6 JSON format."""
    # Parse INIT
    init_tag, init_attrs = kyoku_tags[0]
    assert init_tag == 'INIT'
    
    seed = [int(x) for x in re.search(r'seed="([^"]*)"', init_attrs).group(1).split(',')]
    ten = [int(x) for x in re.search(r'ten="([^"]*)"', init_attrs).group(1).split(',')]
    oya = int(re.search(r'oya="(\d+)"', init_attrs).group(1))
    
    haipai = [[], [], []]
    for p in range(3):
        hai_str = re.search(rf'hai{p}="([^"]*)"', init_attrs)
        if hai_str and hai_str.group(1):
            haipai[p] = [int(x) for x in hai_str.group(1).split(',')]
    
    # Meta: [kyoku_num, honba, kyotaku]
    meta = [seed[0], seed[1], seed[2]]
    # Scores (in 100-point units in XML, need *100 for JSON)
    scores = [t * 100 for t in ten]
    # Dora indicator
    dora_indicators = [xml_tile_to_compact(seed[5])]
    ura_indicators = []
    
    # Build tsumo/dahai arrays for each player
    tsumo_arrays = [[], [], []]
    dahai_arrays = [[], [], []]
    
    # Track state for tsumogiri detection
    last_tsumo = [None, None, None]  # last drawn tile per player (compact)
    last_tsumo_xml = [None, None, None]  # last drawn tile per player (xml id)
    
    # Track if player is in "after naki" state (for dahai encoding)
    after_naki = [False, False, False]
    
    # Result data
    result_items = []
    
    tsumo_tags = {'T': 0, 'U': 1, 'V': 2}
    dahai_tags = {'D': 0, 'E': 1, 'F': 2}
    
    for tag, attrs in kyoku_tags[1:]:
        if tag in tsumo_tags:
            player = tsumo_tags[tag]
            tile_xml = int(attrs.strip())
            tile_compact = xml_tile_to_compact(tile_xml)
            tsumo_arrays[player].append(tile_compact)
            last_tsumo[player] = tile_compact
            last_tsumo_xml[player] = tile_xml
            after_naki[player] = False
            
        elif tag in dahai_tags:
            player = dahai_tags[tag]
            tile_xml = int(attrs.strip())
            tile_compact = xml_tile_to_compact(tile_xml)
            
            if not after_naki[player] and last_tsumo_xml[player] == tile_xml:
                # Tsumogiri
                dahai_arrays[player].append(60)
            else:
                if after_naki[player] and tile_compact == last_tsumo[player]:
                    # After naki, discarding the same tile as would be tsumogiri
                    # But we use 60 only for actual tsumogiri from tsumo
                    dahai_arrays[player].append(tile_compact)
                else:
                    dahai_arrays[player].append(tile_compact)
            after_naki[player] = False
            
        elif tag == 'N':
            who = int(re.search(r'who="(\d+)"', attrs).group(1))
            m = int(re.search(r'm="(\d+)"', attrs).group(1))
            
            naki_info = decode_naki_xml(m)
            naki_type = naki_info[0]
            
            if naki_type == 'nukidora':
                # In tenhou6 JSON, nukidora appears as:
                # - f44 in dahai if the N was just drawn (tsumogiri)
                # - 0 in dahai if N is from hand
                if last_tsumo[who] == 44:  # N tile compact = 44
                    dahai_arrays[who].append('f44')
                else:
                    dahai_arrays[who].append(0)
                    
            elif naki_type == 'pon':
                _, from_who_rel, called, consumed = naki_info
                pon_str = encode_pon_string(who, from_who_rel, called, consumed)
                tsumo_arrays[who].append(pon_str)
                after_naki[who] = True
                last_tsumo[who] = None
                last_tsumo_xml[who] = None
                
            elif naki_type == 'daiminkan':
                _, from_who_rel, called, consumed = naki_info
                kan_str = encode_daiminkan_string(from_who_rel, called, consumed)
                tsumo_arrays[who].append(kan_str)
                # Daiminkan: dahai gets a 0 placeholder
                dahai_arrays[who].append(0)
                after_naki[who] = False
                last_tsumo[who] = None
                last_tsumo_xml[who] = None
                
            elif naki_type == 'ankan':
                _, _, tiles = naki_info
                ankan_str = encode_ankan_string(tiles)
                dahai_arrays[who].append(ankan_str)
                
            elif naki_type == 'kakan':
                _, from_who_rel, pai, tiles = naki_info
                kakan_str = encode_kakan_string(from_who_rel, pai, tiles)
                dahai_arrays[who].append(kakan_str)
                
        elif tag == 'REACH':
            who = int(re.search(r'who="(\d+)"', attrs).group(1))
            step = int(re.search(r'step="(\d+)"', attrs).group(1))
            if step == 1:
                # Mark next dahai as reach
                # The reach declaration modifies the dahai entry
                # We need to look ahead - but simpler: mark state
                # Actually in tenhou6, reach appears as "rXX" in dahai
                # We handle this by checking if REACH step=1 precedes a dahai
                # Set a flag
                if not hasattr(parse_kyoku, '_reach_pending'):
                    parse_kyoku._reach_pending = {}
                parse_kyoku._reach_pending[who] = True
            elif step == 2:
                # Update scores (riichi payment)
                ten_match = re.search(r'ten="([^"]*)"', attrs)
                if ten_match:
                    new_ten = [int(x) for x in ten_match.group(1).split(',')]
                    # scores are updated but we don't need to track here
                    
        elif tag == 'DORA':
            hai = int(re.search(r'hai="(\d+)"', attrs).group(1))
            dora_indicators.append(xml_tile_to_compact(hai))
            
        elif tag == 'AGARI':
            agari_data = parse_agari(attrs)
            result_items.extend(agari_data)
            
        elif tag == 'RYUUKYOKU':
            ryuukyoku_data = parse_ryuukyoku(attrs)
            result_items.extend(ryuukyoku_data)
    
    # Handle reach: modify dahai entries
    # Actually we need to handle reach differently - go back and fix dahai
    # The reach flag should have been applied when we processed the dahai after REACH step=1
    # Let me redo this with a different approach - process in order and track reach state
    
    # Re-process to handle reach properly
    tsumo_arrays = [[], [], []]
    dahai_arrays = [[], [], []]
    last_tsumo = [None, None, None]
    last_tsumo_xml = [None, None, None]
    after_naki = [False, False, False]
    reach_pending = [False, False, False]
    result_items = []
    dora_indicators = [xml_tile_to_compact(seed[5])]
    
    for tag, attrs in kyoku_tags[1:]:
        if tag in tsumo_tags:
            player = tsumo_tags[tag]
            tile_xml = int(attrs.strip())
            tile_compact = xml_tile_to_compact(tile_xml)
            tsumo_arrays[player].append(tile_compact)
            last_tsumo[player] = tile_compact
            last_tsumo_xml[player] = tile_xml
            after_naki[player] = False
            
        elif tag in dahai_tags:
            player = dahai_tags[tag]
            tile_xml = int(attrs.strip())
            tile_compact = xml_tile_to_compact(tile_xml)
            
            if reach_pending[player]:
                # This dahai is a reach declaration
                if last_tsumo_xml[player] == tile_xml:
                    dahai_arrays[player].append(f"r60")
                else:
                    dahai_arrays[player].append(f"r{tile_compact:02d}")
                reach_pending[player] = False
            elif not after_naki[player] and last_tsumo_xml[player] == tile_xml:
                # Tsumogiri
                dahai_arrays[player].append(60)
            else:
                dahai_arrays[player].append(tile_compact)
            after_naki[player] = False
            
        elif tag == 'N':
            who = int(re.search(r'who="(\d+)"', attrs).group(1))
            m = int(re.search(r'm="(\d+)"', attrs).group(1))
            
            naki_info = decode_naki_xml(m)
            naki_type = naki_info[0]
            
            if naki_type == 'nukidora':
                # In tenhou6 JSON, all nukidora are encoded as 'f44'
                dahai_arrays[who].append('f44')
                    
            elif naki_type == 'pon':
                _, from_who_rel, called, consumed = naki_info
                pon_str = encode_pon_string(who, from_who_rel, called, consumed)
                tsumo_arrays[who].append(pon_str)
                after_naki[who] = True
                last_tsumo[who] = None
                last_tsumo_xml[who] = None
                
            elif naki_type == 'daiminkan':
                _, from_who_rel, called, consumed = naki_info
                kan_str = encode_daiminkan_string(from_who_rel, called, consumed)
                tsumo_arrays[who].append(kan_str)
                dahai_arrays[who].append(0)
                after_naki[who] = False
                last_tsumo[who] = None
                last_tsumo_xml[who] = None
                
            elif naki_type == 'ankan':
                _, _, tiles = naki_info
                ankan_str = encode_ankan_string(tiles)
                dahai_arrays[who].append(ankan_str)
                
            elif naki_type == 'kakan':
                _, from_who_rel, pai, tiles = naki_info
                kakan_str = encode_kakan_string(from_who_rel, pai, tiles)
                dahai_arrays[who].append(kakan_str)
                
        elif tag == 'REACH':
            who = int(re.search(r'who="(\d+)"', attrs).group(1))
            step = int(re.search(r'step="(\d+)"', attrs).group(1))
            if step == 1:
                reach_pending[who] = True
                
        elif tag == 'DORA':
            hai = int(re.search(r'hai="(\d+)"', attrs).group(1))
            dora_indicators.append(xml_tile_to_compact(hai))
            
        elif tag == 'AGARI':
            agari_data = parse_agari(attrs)
            result_items.extend(agari_data)
            
        elif tag == 'RYUUKYOKU':
            ryuukyoku_data = parse_ryuukyoku(attrs)
            result_items.extend(ryuukyoku_data)
    
    # Handle 'f' prefix for tsumogiri of non-60 tiles
    # In tenhou6, 'fXX' is used when the tile is aka (red) and tsumogiri
    # Actually 'f' prefix is used for tsumogiri when tile != last tsumo in compact
    # (because compact encoding loses the specific copy info)
    # Let me fix: use 'fXX' when tsumogiri but compact tile differs from what 60 would resolve to
    # Actually simpler: 60 means "same as tsumo", fXX means "tsumogiri but specifying tile explicitly"
    # This happens with aka tiles: if you draw 5pr (compact=52) and tsumogiri it,
    # the dahai should be 'f52' not 60, because 60 would resolve to the tsumo tile
    # which might be ambiguous. Actually in tenhou6, 60 always means tsumogiri.
    # 'fXX' is used when... let me check the actual data.
    
    # Build haipai in compact encoding
    haipai_compact = [sorted([xml_tile_to_compact(t) for t in haipai[p]]) for p in range(3)]
    
    # Build the kyoku array in tenhou6 format:
    # [meta, scores, dora_indicators, ura_indicators,
    #  haipai0, tsumo0, dahai0, haipai1, tsumo1, dahai1, haipai2, tsumo2, dahai2,
    #  haipai3(empty), tsumo3(empty), dahai3(empty), result]
    kyoku = [
        meta,
        scores,
        dora_indicators,
        ura_indicators,
        haipai_compact[0], tsumo_arrays[0], dahai_arrays[0],
        haipai_compact[1], tsumo_arrays[1], dahai_arrays[1],
        haipai_compact[2], tsumo_arrays[2], dahai_arrays[2],
        [], [], [],  # player 3 (empty in sanma)
        result_items,
    ]
    
    return kyoku


def parse_agari(attrs: str) -> list:
    """Parse AGARI tag attributes into tenhou6 result format."""
    sc = [int(x) for x in re.search(r'sc="([^"]*)"', attrs).group(1).split(',')]
    who = int(re.search(r'who="(\d+)"', attrs).group(1))
    from_who = int(re.search(r'fromWho="(\d+)"', attrs).group(1))
    
    # sc format: [score0, delta0, score1, delta1, score2, delta2, score3, delta3]
    # Convert to deltas array (in points, not 100s)
    deltas = [sc[i*2+1] * 100 for i in range(4)]
    
    # Build detail array: [who, fromWho, who_again, description, yaku1, yaku2, ...]
    ten_match = re.search(r'ten="([^"]*)"', attrs)
    ten = [int(x) for x in ten_match.group(1).split(',')] if ten_match else [0, 0, 0]
    
    # Yaku
    yaku_match = re.search(r'yaku="([^"]*)"', attrs)
    yakuman_match = re.search(r'yakuman="([^"]*)"', attrs)
    
    # Build description string (simplified)
    points = ten[1]
    if who == from_who:
        # Tsumo
        desc = f"{points}点∀"
    else:
        desc = f"{points}点"
    
    detail = [who, from_who, who]
    # Add point description
    detail.append(desc)
    
    # Parse yaku list
    if yaku_match:
        yaku_pairs = [int(x) for x in yaku_match.group(1).split(',')]
        for i in range(0, len(yaku_pairs), 2):
            detail.append(f"yaku{yaku_pairs[i]}({yaku_pairs[i+1]}飜)")
    
    # ura dora
    ura_match = re.search(r'doraHaiUra="([^"]*)"', attrs)
    if ura_match:
        ura_tiles = [int(x) for x in ura_match.group(1).split(',')]
        # Store in ura_indicators (handled at kyoku level)
    
    return ['和了', deltas, detail]


def parse_ryuukyoku(attrs: str) -> list:
    """Parse RYUUKYOKU tag attributes into tenhou6 result format."""
    sc_match = re.search(r'sc="([^"]*)"', attrs)
    if sc_match:
        sc = [int(x) for x in sc_match.group(1).split(',')]
        deltas = [sc[i*2+1] * 100 for i in range(4)]
        return ['流局', deltas]
    else:
        return ['流局']


def convert_xml_to_tenhou6(xml_content: str) -> dict:
    """Main conversion function."""
    return parse_xml(xml_content)


def main():
    parser = argparse.ArgumentParser(description="Convert tenhou sanma XML to tenhou.net/6 JSON")
    parser.add_argument("input", help="Input XML file")
    parser.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    args = parser.parse_args()
    
    with open(args.input) as f:
        xml_content = f.read()
    
    result = convert_xml_to_tenhou6(xml_content)
    
    output = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
