#!/usr/bin/env python3
"""Generate Figure-10-inspired placement diagrams from the actual mapper."""
from pathlib import Path
from argparse import ArgumentParser
from facil_mapper import AiMMapper, Geometry, choose_mapid


def generate(cols: int, output: Path, nrows: int = 8):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches

    g = Geometry(channels=2, ranks=1, banks_per_rank=16)
    mapid, partition, _ = choose_mapid(cols, g)
    mapper = AiMMapper(g, mapid)
    row_bytes = cols * g.element_bytes
    parts = max(1, row_bytes // (g.page_bytes // g.total_pus))
    # For MapID=5, output per 64KiB PU area; for small rows, one segment/row.
    segment_bytes = min(row_bytes, g.page_bytes // g.total_pus)
    fig, ax = plt.subplots(figsize=(10, 3.2 + nrows * .34))
    palette = ['#2d7dd2', '#e58f4f', '#3f998a', '#9167c5']
    for r in range(nrows):
        y = nrows - 1 - r
        for p in range(parts):
            addr = r * row_bytes + p * segment_bytes
            loc = mapper.decode(addr)
            fc = palette[(loc.channel + 2 * loc.bank) % len(palette)]
            left = p / parts
            rect = patches.Rectangle((left, y), 0.985/parts, .82, facecolor=fc, alpha=.9)
            ax.add_patch(rect)
            ax.text(left + .49/parts, y + .42, f'C{loc.channel} B{loc.bank}',
                    ha='center', va='center', fontsize=10, color='white', weight='bold')
    ax.set_xlim(-0.01, 1.02)
    ax.set_ylim(-.12, nrows + .05)
    ax.set_xticks([])
    ax.set_yticks([i+.42 for i in range(nrows)], [f'W[{nrows-i-1}, :]' for i in range(nrows)])
    ax.set_title(f'AiM-style FACIL layout: {nrows} × {cols} FP16 (MapID {mapid})',
                 fontsize=13, weight='bold')
    ax.set_xlabel('Segments of each logical matrix row (color labels = channel/bank)')
    fig.text(.5, .015,
             'Derived from reference bit-field mapper | Figure 10 geometry: 2 channels, 1 rank, 16 banks/channel\n'
             'Standalone mapping; not an HBM/LPDDR5 PIM hardware performance simulation',
             fontsize=8, ha='center')
    fig.subplots_adjust(bottom=.16, top=.9, left=.16)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=200, bbox_inches='tight')
    plt.close(fig)
    print(f'Saved {output}')


def main():
    ap = ArgumentParser()
    ap.add_argument('--output-dir', type=Path, default=Path('personA/results'))
    args = ap.parse_args()
    generate(8192, args.output_dir / 'mapid3_8K_columns.png')
    generate(65536, args.output_dir / 'mapid5_64K_columns.png', nrows=4)

if __name__ == '__main__':
    main()
