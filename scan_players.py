#!/usr/bin/env python3
"""Scan sanma XML data and collect player statistics.

Usage:
    python3 scan_players.py ~/sanma-data > player_stats.json
"""

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote


def scan_tar(tar_path: str, player_stats: dict) -> int:
    """Extract tar.zst, scan XMLs for player info, return game count."""
    work_dir = '/tmp/sanma-scan'
    os.makedirs(work_dir, exist_ok=True)
    
    # Clear work dir
    for f in os.listdir(work_dir):
        os.unlink(os.path.join(work_dir, f))
    
    # Extract
    r = subprocess.run(
        ['tar', '--use-compress-program=zstd', '-xf', tar_path, '-C', work_dir],
        capture_output=True, timeout=300
    )
    if r.returncode != 0:
        return 0
    
    count = 0
    for fname in os.listdir(work_dir):
        if not fname.endswith('.xml.zst'):
            continue
        xml_zst_path = os.path.join(work_dir, fname)
        try:
            r = subprocess.run(['zstd', '-dcf', xml_zst_path], capture_output=True, timeout=10)
            if r.returncode != 0:
                continue
            xml = r.stdout.decode('utf-8', errors='ignore')
            
            m = re.search(r'<UN n0="([^"]*)" n1="([^"]*)" n2="([^"]*)" n3="[^"]*" dan="([^"]*)" rate="([^"]*)"', xml)
            if not m:
                continue
            
            names = [unquote(m.group(i+1)) for i in range(3)]
            dan = [int(x) for x in m.group(4).split(',')[:3]]
            rate = [float(x) for x in m.group(5).split(',')[:3]]
            
            for i in range(3):
                if names[i]:
                    s = player_stats[names[i]]
                    s['games'] += 1
                    s['dan'] = max(s['dan'], dan[i])
                    s['rate'] = max(s['rate'], rate[i])
            count += 1
        except:
            pass
    
    # Cleanup
    for f in os.listdir(work_dir):
        os.unlink(os.path.join(work_dir, f))
    
    return count


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else '.'
    
    tar_files = sorted(Path(data_dir).rglob('*.tar.zst'))
    print(f"Found {len(tar_files)} tar.zst files", file=sys.stderr)
    
    player_stats = defaultdict(lambda: {'games': 0, 'dan': 0, 'rate': 0.0})
    total = 0
    
    for i, tf in enumerate(tar_files):
        n = scan_tar(str(tf), player_stats)
        total += n
        print(f"[{i+1}/{len(tar_files)}] {tf.name}: {n} games (total: {total})", file=sys.stderr)
    
    # Output
    result = {
        'total_games': total,
        'total_players': len(player_stats),
        'players': {k: v for k, v in sorted(player_stats.items(), key=lambda x: (-x[1]['dan'], -x[1]['rate']))}
    }
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
