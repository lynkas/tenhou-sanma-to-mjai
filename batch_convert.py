#!/usr/bin/env python3
"""Batch convert sanma XML data and find top players.

Usage:
    python3 batch_convert.py --data-dir ~/sanma-data --out-dir ~/sanma-mjson --top 250 --min-games 200
"""

import argparse
import gzip
import json
import os
import subprocess
import sys
import tarfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote
import re

sys.path.insert(0, str(Path(__file__).parent))
from xml_to_tenhou6 import convert_xml_to_tenhou6
from tenhou6_to_mjai import convert_tenhou6_json


def extract_players_from_xml(xml_content: str):
    """Extract player names and dan/rate from XML."""
    un_match = re.search(
        r'<UN n0="([^"]*)" n1="([^"]*)" n2="([^"]*)" n3="([^"]*)" dan="([^"]*)" rate="([^"]*)"',
        xml_content
    )
    if not un_match:
        return None
    names = [unquote(un_match.group(i+1)) for i in range(3)]
    dan = [int(x) for x in un_match.group(5).split(',')[:3]]
    rate = [float(x) for x in un_match.group(6).split(',')[:3]]
    return names, dan, rate


def process_tar(tar_path: Path, out_dir: Path, player_stats: dict, convert: bool = True):
    """Process one tar.zst file: extract XMLs, convert to mjson, collect player stats."""
    try:
        # Decompress tar.zst
        result = subprocess.run(
            ['tar', '--use-compress-program=zstd', '-xf', str(tar_path), '-C', '/tmp/sanma-extract'],
            capture_output=True, timeout=120
        )
        if result.returncode != 0:
            # Try alternative method
            subprocess.run(['zstd', '-d', str(tar_path), '-o', '/tmp/sanma.tar', '-f'], 
                         capture_output=True, timeout=60)
            subprocess.run(['tar', 'xf', '/tmp/sanma.tar', '-C', '/tmp/sanma-extract'],
                         capture_output=True, timeout=60)
    except Exception as e:
        print(f"  Error extracting {tar_path.name}: {e}", file=sys.stderr)
        return 0

    converted = 0
    extract_dir = Path('/tmp/sanma-extract')
    
    for xml_zst in extract_dir.glob('*.xml.zst'):
        game_id = xml_zst.stem.replace('.xml', '')
        try:
            # Decompress XML
            result = subprocess.run(['zstd', '-df', str(xml_zst), '-o', '/tmp/game.xml'],
                                  capture_output=True, timeout=10)
            with open('/tmp/game.xml') as f:
                xml_content = f.read()
            
            # Extract player info for stats
            player_info = extract_players_from_xml(xml_content)
            if player_info:
                names, dan, rate = player_info
                for i, name in enumerate(names):
                    if name:
                        stats = player_stats[name]
                        stats['games'] += 1
                        stats['dan'] = max(stats.get('dan', 0), dan[i])
                        stats['rate'] = max(stats.get('rate', 0.0), rate[i])
            
            if convert:
                # Convert XML → tenhou6 JSON → mjai mjson
                t6 = convert_xml_to_tenhou6(xml_content)
                events = convert_tenhou6_json(t6)
                
                # Write gzipped mjson
                mjson_path = out_dir / f"{game_id}.mjson"
                with gzip.open(mjson_path, 'wt') as f:
                    for ev in events:
                        f.write(json.dumps(ev, ensure_ascii=False) + '\n')
                converted += 1
                
        except Exception as e:
            pass  # Skip problematic files silently
        finally:
            for tmp in ['/tmp/game.xml']:
                if os.path.exists(tmp):
                    os.unlink(tmp)
    
    # Cleanup
    for f in extract_dir.glob('*'):
        os.unlink(f)
    if os.path.exists('/tmp/sanma.tar'):
        os.unlink('/tmp/sanma.tar')
    
    return converted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True, help='Directory with tar.zst files')
    parser.add_argument('--out-dir', default=None, help='Output directory for mjson files')
    parser.add_argument('--top', type=int, default=250, help='Number of top players to select')
    parser.add_argument('--min-games', type=int, default=200, help='Minimum games for a player')
    parser.add_argument('--stats-only', action='store_true', help='Only collect stats, no conversion')
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir) if args.out_dir else None
    
    if out_dir and not args.stats_only:
        out_dir.mkdir(parents=True, exist_ok=True)
    
    os.makedirs('/tmp/sanma-extract', exist_ok=True)
    
    # Collect all tar.zst files
    tar_files = sorted(data_dir.rglob('*.tar.zst'))
    print(f"Found {len(tar_files)} tar.zst files")
    
    player_stats = defaultdict(lambda: {'games': 0, 'dan': 0, 'rate': 0.0})
    total_converted = 0
    
    for i, tar_path in enumerate(tar_files):
        print(f"[{i+1}/{len(tar_files)}] {tar_path.relative_to(data_dir)}", end='', flush=True)
        n = process_tar(tar_path, out_dir, player_stats, convert=not args.stats_only)
        total_converted += n
        print(f" → {n} games")
    
    # Filter and rank players
    qualified = [(name, stats) for name, stats in player_stats.items() 
                 if stats['games'] >= args.min_games]
    
    # Sort by dan (descending), then rate (descending)
    qualified.sort(key=lambda x: (-x[1]['dan'], -x[1]['rate']))
    
    top_players = qualified[:args.top]
    
    print(f"\n=== Results ===")
    print(f"Total games processed: {total_converted}")
    print(f"Total unique players: {len(player_stats)}")
    print(f"Players with >= {args.min_games} games: {len(qualified)}")
    print(f"Top {args.top} players selected: {len(top_players)}")
    
    if top_players:
        print(f"\nTop 10:")
        for i, (name, stats) in enumerate(top_players[:10]):
            print(f"  {i+1:3d}. {name:20s} dan={stats['dan']:2d} rate={stats['rate']:.1f} games={stats['games']}")
    
    # Save player lists
    stats_dir = out_dir or Path('.')
    
    with open(stats_dir / 'top_players_250.txt', 'w') as f:
        for name, stats in qualified[:250]:
            f.write(f"{name}\n")
    
    with open(stats_dir / 'top_players_750.txt', 'w') as f:
        for name, stats in qualified[:750]:
            f.write(f"{name}\n")
    
    with open(stats_dir / 'player_stats.json', 'w') as f:
        json.dump({name: stats for name, stats in qualified}, f, ensure_ascii=False, indent=2)
    
    print(f"\nSaved: top_players_250.txt, top_players_750.txt, player_stats.json")


if __name__ == "__main__":
    main()
