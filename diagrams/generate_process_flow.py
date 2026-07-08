# Generates process-flow.dot with explicit pinned (neato) grid coordinates.
# Graphviz's automatic rank layout kept collapsing/misaligning the 3-row wrap,
# so node positions are assigned to an explicit row/col grid here instead.
# Regenerate after editing:
#   python3 generate_process_flow.py
#   neato -n -Tpng -Gdpi=200 process-flow.dot -o process-flow.png
#   neato -n -Tsvg process-flow.dot -o process-flow.svg

COL = 235   # horizontal spacing in points (72pt = 1in)
ROW = 175   # vertical spacing in points

nodes = [
    # id, label, shape, fillcolor, row (0=bottom), col, fontsize, extra
    ("start",    "Lender logs in\n(Streamlit)", "ellipse", "#FFCDD2", 2, 0, 13, ""),
    ("select",   "Select customer\nfrom dashboard", "box", "#FFE0B2", 2, 1, 13, ""),
    ("generate", 'Click\n"Generate Health Card"', "box", "#FFE0B2", 2, 2, 13, ""),
    ("ratios",   "Compute GST / UPI /\nAA / EPFO ratios", "box", "#C8E6C9", 2, 3, 13, ""),
    ("ntc",      "GST-registered?\nYes: score normally\nNo (NTC): neutral 50, NA", "diamond", "#FFF3C4", 2, 4, 12, 'margin="0.2,0.12"'),

    ("crossval",  "Cross-validate sources\n(GST vs AA vs UPI vs EPFO)", "box", "#C8E6C9", 1, 0, 13, ""),
    ("composite", "Weighted composite score\n(0-100) + red/green flags", "box", "#C8E6C9", 1, 1, 13, ""),
    ("save_sc",   "Persist\nscorecard", "cylinder", "#E1BEE7", 1, 2, 12, ""),
    ("facts",     "Retrieve\nscorecard facts", "box", "#FFF9C4", 1, 3, 13, ""),
    ("gemini",    "Gemini available\n& in quota?\nYes: LLM narrative\nNo: deterministic fallback", "diamond", "#FFF3C4", 1, 4, 12, 'margin="0.22,0.14"'),

    ("chart",    "Build chart configs\n(code, not LLM)", "box", "#FFF9C4", 0, 0, 13, ""),
    ("save_rep", "Persist\nreport", "cylinder", "#E1BEE7", 0, 1, 12, ""),
    ("render",   "Render Health Card:\ngauge, scores, charts,\nflags, narrative", "box", "#BBDEFB", 0, 2, 13, ""),
    ("decision", "Lender views score,\ndownloads JSON,\ndecides", "ellipse", "#FFCDD2", 0, 3, 13, ""),
]

edges = [
    ("start", "select", False),
    ("select", "generate", False),
    ("generate", "ratios", False),
    ("ratios", "ntc", False),
    ("ntc", "crossval", True),       # wrap
    ("crossval", "composite", False),
    ("composite", "save_sc", False),
    ("save_sc", "facts", False),
    ("facts", "gemini", False),
    ("gemini", "chart", True),       # wrap
    ("chart", "save_rep", False),
    ("save_rep", "render", False),
    ("render", "decision", False),
]

lines = []
lines.append("digraph process_flow {")
lines.append('  layout=neato;')
lines.append('  bgcolor="white";')
lines.append('  fontname="Helvetica";')
lines.append('  graph [splines=line];')
lines.append('  node [fontname="Helvetica", style="rounded,filled"];')
lines.append('  edge [fontname="Helvetica", fontsize=10, color="#666666", arrowsize=0.8, penwidth=1.3];')
lines.append("")

for nid, label, shape, color, row, col, fontsize, extra in nodes:
    x = col * COL
    y = row * ROW
    esc_label = label.replace('"', '\\"')
    style = "rounded,filled" if shape == "box" else "filled"
    line = (f'  {nid} [label="{esc_label}", shape={shape}, fillcolor="{color}", '
            f'fontsize={fontsize}, style="{style}", pos="{x},{y}!"')
    if extra:
        line += f", {extra}"
    line += "];"
    lines.append(line)

lines.append("")
for a, b, is_wrap in edges:
    if is_wrap:
        lines.append(f'  {a} -> {b} [penwidth=1.6, color="#333333"];')
    else:
        lines.append(f"  {a} -> {b};")

lines.append("}")

with open("/Users/abhijeetnandvikar/Documents/personal/learning/hackthons/msme-financial-health-card/diagrams/process-flow.dot", "w") as f:
    f.write("\n".join(lines) + "\n")

print("written")
