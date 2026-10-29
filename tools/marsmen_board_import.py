"""Reads Christian's Mars Men caption board (storyboards/marsmen-captions.pcraft, one PhotoCraft type layer per caption
word, named "NN · WORD", with " · behind" on the words set behind the speaker) and writes tools/marsmen-layout.json:
for every caption's frame, each word's place, size, stretch, color, weight and italic, as he left them on the board. Then
tools/ai_marsmen.py sets the captions exactly there.

Words that sit a few pixels off the middle of the frame, or off the left edge, right edge or middle of a word above
or beside them, are snapped into line, on the board too (so the board stays the one copy to edit).

    python3 tools/marsmen_board_import.py
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT.parent / "storyboards/marsmen-captions.pcraft"
TILES = ROOT.parent / "storyboards/marsmen-board"
W = 540     # the video's width
SNAP = 10   # how far off (in the video's pixels) a word may sit and still be snapped into line


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
    H = 960
    tile_of = lambda x, y: next((n for n, (tx, ty) in pos.items() if tx <= x < tx + W and ty <= y < ty + H), None)
    caps, words = {}, []
    for r in infos:
        parts = names[r["layer"]].split(" · ")
        n, word = int(parts[0]), parts[1]
        st = r["runs"][0]["style"]
        a, _, _, d, tx, ty = r["transform"]
        c = st["color"]["c"]
        # which spoken word this is (its timing), by the word the layer was made for
        i = said[n].index(word) if word in said[n] else 0
        words.append({"n": n, "i": i, "text": r["text"], "layer": r["layer"], "lines": [
            {"text": r["text"][l["start"]:l["end"]].strip(), "x": tx + l["x0"] * a, "baseline": ty + l["baseline"] * d,
             "width": (l["x1"] - l["x0"]) * a} for l in r["lines"]],
            "size": round(st["size_pt"] * d, 1), "stretch": round(a / d, 3),
            "color": "#%02x%02x%02x" % tuple(round(v * 255) for v in c[:3]),
            "weight": st["font_style"].lower(), "italic": bool(st["faux_italic"] or st["italic"]),
            "behind": "behind" in parts[2:]})
    # a word he added (one more layer than words said) shows from the start of its caption
    seen = set()
    for w in sorted(words, key=lambda w: w["text"].replace("\n", " ").split()[-1] != said[w["n"]][w["i"]]):
        if (w["n"], w["i"]) in seen:
            w["i"] = -1
        seen.add((w["n"], w["i"]))
    # each line of a layer is set on its own; a word dragged onto another caption's frame is shown on that frame
    for w in words:
        for k, l in enumerate(w["lines"]):
            m = tile_of(l["x"] + l["width"] / 2, l["baseline"] - w["size"] / 3) or str(w["n"])
            e = {key: v for key, v in w.items() if key not in ("lines", "text")}
            e.update(text=l["text"], x=round(l["x"] - pos[m][0], 1), baseline=round(l["baseline"] - pos[m][1], 1),
                     width=round(l["width"], 1), snap=len(w["lines"]) == 1)
            caps.setdefault(m, []).append(e)
    moves = {}
    for ws in caps.values():
        done = []
        for w in sorted(ws, key=lambda w: w["baseline"] - w["size"]):   # top to bottom
            edges = lambda v: (v["x"], v["x"] + v["width"] / 2, v["x"] + v["width"])
            # the middle of the frame first, then the left, middle or right of a word already in line
            goals = [(edges(w)[1], W / 2)] + [(a, b) for v in done for a, b in zip(edges(w), edges(v))]
            off = next((b - a for a, b in goals if 0 < abs(b - a) <= SNAP), 0)
            if off and w["snap"]:
                w["x"] = round(w["x"] + off, 1)
                moves[w["layer"]] = off
            done.append(w)
    if moves:
        args = ["photocraft-cli", "run", BOARD]
        for layer, off in moves.items():
            args += ["--cmd", "type.edit", "--params", json.dumps({"layer": layer, "move": [off, 0]})]
        subprocess.run(args + ["--out", BOARD, "--in-place"], capture_output=True, check=True)
    for ws in caps.values():
        for w in ws:
            del w["layer"], w["snap"]
    print(len(moves), "words snapped into line")
    (ROOT / "tools/marsmen-layout.json").write_text(json.dumps(caps, indent=1))
    print(len(infos), "words in", len(caps), "captions")


if __name__ == "__main__":
    main()
