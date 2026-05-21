# tenhou-sanma-to-mjai

Convert Tenhou 3-player mahjong (sanma) game logs to MJAI JSONL format.

## Features

- Converts tenhou.net/6 JSON format to MJAI event stream
- Handles all sanma-specific events: nukidora (北抜き), pon, kan, riichi, hora, ryukyoku
- Supports double ron
- Verified against 200 random games (1832 kyokus, 100% accuracy)

## Usage

```bash
# From a tenhou.net/6 JSON file:
python3 tenhou6_to_mjai.py --json game.json -o output.mjson

# From a Tenhou game ID (requires mjai-reviewer for download):
python3 tenhou6_to_mjai.py --id 2026011603gm-00b9-0000-2b45278f -o output.mjson
```

## Input Format

The input is Tenhou's internal JSON format (tenhou.net/6), not the raw XML.
To obtain this format from a game ID, you can use [mjai-reviewer](https://github.com/Equim-chan/mjai-reviewer)'s `--tenhou-out` option.

## Output Format

Standard MJAI JSONL with 3-player arrays:

```jsonl
{"type": "start_game", "names": ["player0", "player1", "player2"]}
{"type": "start_kyoku", "bakaze": "E", "dora_marker": "7m", "kyoku": 1, "honba": 0, "kyotaku": 0, "oya": 0, "scores": [35000, 35000, 35000], "tehais": [[...], [...], [...]]}
{"type": "tsumo", "actor": 0, "pai": "9m"}
{"type": "nukidora", "actor": 0, "pai": "N"}
{"type": "dahai", "actor": 0, "pai": "3p", "tsumogiri": true}
...
```

## Tile Encoding

Tenhou sanma uses a compact tile encoding:
- `11`=1m, `19`=9m (only 1m and 9m exist in sanma)
- `21`-`29` = 1p-9p
- `31`-`39` = 1s-9s
- `41`-`47` = E, S, W, N, P, F, C
- `52`=red 5p, `53`=red 5s
- `0` in dahai = nukidora from hand
- `60` in dahai = tsumogiri

## License

MIT
