"""Reads Christian's Mars Men caption board (storyboards/marsmen-captions.pcraft, one PhotoCraft type layer per caption
word, named "NN · WORD", with " · behind" on the words set behind the speaker) and writes tools/marsmen-layout.json:
for every caption, each word's place, size, stretch, color, weight and italic, as he left them on the board. Then
tools/ai_marsmen.py sets the captions exactly there.

    python3 tools/marsmen_board_import.py
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT.parent / "storyboards/marsmen-captions.pcraft"
TILES = ROOT.parent / "storyboards/marsmen-board"


def main():
    info = json.loads(subprocess.run(["photocraft-cli", "info", BOARD], capture_output=True, text=True, check=True).stdout)
    names = {l["id"]: l["name"] for l in info["layers"] if l["kind"] == "Type"}
    args = ["photocraft-cli", "run", BOARD]
    for i in names:
        args += ["--cmd", "type.info", "--params", json.dumps({"layer": i})]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    infos = [json.loads(l)["result"] for l in out.splitlines() if l.startswith("{")]
    pos = json.loads((TILES / "layout.json").read_text())["pos"]
    said = {b["n"]: [w["word"] for w in b["words"]] for b in json.loads((TILES / "board.json").read_text())}
    caps = {}
    for r in infos:
        parts = names[r["layer"]].split(" · ")
        n, word = int(parts[0]), parts[1]
        st = r["runs"][0]["style"]
        a, _, _, d, tx, ty = r["transform"]
        c = st["color"]["c"]
        tile = pos[str(n)]
        # which spoken word this is (its timing), by the word the layer was made for
        i = said[n].index(word) if word in said[n] else 0
        caps.setdefault(str(n), []).append({
            "text": r["text"], "i": i, "x": round(tx - tile[0], 1), "baseline": round(ty - tile[1], 1),
            "size": round(st["size_pt"] * d, 1), "stretch": round(a / d, 3),
            "color": "#%02x%02x%02x" % tuple(round(v * 255) for v in c[:3]),
            "weight": st["font_style"].lower(), "italic": bool(st["faux_italic"] or st["italic"]),
            "behind": "behind" in parts[2:]})
    # a word he added (one more layer than words said) shows from the start of the caption
    for n, ws in caps.items():
        seen = set()
        for w in sorted(ws, key=lambda w: w["text"] != said[int(n)][w["i"]]):
            if w["i"] in seen:
                w["i"] = -1
            seen.add(w["i"])
    (ROOT / "tools/marsmen-layout.json").write_text(json.dumps(caps, indent=1))
    print(len(infos), "words in", len(caps), "captions")


if __name__ == "__main__":
    main()
