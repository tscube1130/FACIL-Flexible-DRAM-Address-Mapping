
from pathlib import Path as _Path
import sys as _sys
_ROOT = _Path(__file__).resolve().parents[2]
_sys.path.insert(0, str(_ROOT))
from experiments.paths import ROOT, RESULTS, TRACES, SIMULATOR, CONFIG

from pathlib import Path
from collections import Counter
import csv, json, math, sys

root = ROOT
r = RESULTS
s = r / 'facil/facil_step6_comparison/ttft_comparison.csv'
g = r / 'analytical/llama3_soc_gemm_analytical/soc_gemm_roofline.csv'

assert s.is_file() and g.is_file(), \
    'STOP: Step 6 or GEMM CSV missing'

sys.path.insert(0, str(root / 'mapping'))
from facil_mapper import Geometry, AiMMapper, choose_mapid

shapes = {
    'q_o': (4096, 4096, 2, 2),
    'k_v': (1024, 4096, 2, 2),
    'ffn_gate_up': (14336, 4096, 2, 2),
    'ffn_down': (4096, 14336, 1, 3)
}

geo = Geometry(
    channels=4,
    ranks=2,
    banks_per_rank=16
)
geo.validate()

assert geo.total_pus == 128
assert geo.chunk_bytes == 2048

def csv_rows(p):
    with p.open(newline='') as f:
        return {
            int(x['prefill_tokens']): x
            for x in csv.DictReader(f)
        }

soc, old = csv_rows(g), csv_rows(s)

assert set(soc) == set(old) == {8,16,32,64,128}

shape_data = {}

for name, (m,k,mult,mid) in shapes.items():
    assert choose_mapid(k,geo)[0] == mid

    mapper = AiMMapper(geo,mid)
    chunks = m*k//1024

    occupancy = Counter()

    for i in range(chunks):
        a = mapper.decode(i*2048)
        occupancy[(a.channel,a.rank,a.bank)] += 1

    assert len(occupancy) == 128
    assert min(occupancy.values()) == max(occupancy.values())

    waves = max(occupancy.values())
    assert waves == math.ceil(chunks/128)

    partitions = Counter()

    for row in (
        range(m) if name == 'ffn_down'
        else (0,m//2,m-1)
    ):
        pus = set()

        for j in range(k//1024):
            a = mapper.decode(2*(row*k+j*1024))
            pus.add((a.channel,a.rank,a.bank))

        partitions[len(pus)] += 1

    if name == 'ffn_down':
        assert partitions == {2:2048,3:2048}, partitions
    else:
        assert partitions == {1:3}, partitions

    case = (
        r/f'facil/facil_step3_{name}_2k'/
        ('matched_read_timing.json'
         if name == 'k_v' else 'comparison.json')
    )

    assert case.is_file(), f'Missing: {case}'
    d = json.loads(case.read_text())

    b,f = (
        ('baseline','facil') if name=='k_v'
        else ('baseline_conventional_read','facil_mapped_read')
        if name=='q_o'
        else ('baseline_conventional_read','facil_native_read')
    )

    penalty_ms = (
        int(d[f]['cycles_upper_bound']) -
        int(d[b]['cycles_upper_bound'])
    ) * .3125 / 1e6

    assert penalty_ms >= 0

    shape_data[name] = {
        'm':m,
        'k':k,
        'copies_per_block':mult,
        'mapid':mid,
        'fp16_weight_bytes':2*m*k,
        'chunks':chunks,
        'waves_per_gemv':waves,
        'row_pu_sample_distribution':dict(partitions),
        'mapping_penalty_sensitivity_ms_per_matrix':penalty_ms,
        'min_vector_broadcast_bytes_per_gemv':8*2*k
    }

# Hypothetical effective processing-wave times, NOT measured.
waves_ns = (75.,100.,200.)
rows = []

for wave_ns in waves_ns:

    gemv_ms = sum(
        32*d['copies_per_block']*
        d['waves_per_gemv']*wave_ns/1e6
        for d in shape_data.values()
    )

    for p in sorted(soc):

        soc_sum = ideal = adjusted = 0.
        pim_n_ideal = pim_n_adjusted = 0

        for name,d in shape_data.items():
            m,k,mult = (
                d['m'],d['k'],d['copies_per_block']
            )

            # Same SoC roofline as our existing TTFT model.
            soc_ms = 1e3 * max(
                2*m*k*p/42.5e12,
                (2*m*k+2*p*(m+k))/204.8e9
            )

            # P successive matrix-vector products for prefill.
            pim_ms = (
                p*d['waves_per_gemv']*wave_ns/1e6
            )

            pen = d[
                'mapping_penalty_sensitivity_ms_per_matrix'
            ]

            copies = 32*mult

            soc_sum += copies*soc_ms

            # Choose faster processor per projection.
            ideal += copies*min(soc_ms,pim_ms)
            adjusted += copies*min(soc_ms+pen,pim_ms)

            pim_n_ideal += copies*(pim_ms<soc_ms)
            pim_n_adjusted += copies*(pim_ms<soc_ms+pen)

        assert abs(
            soc_sum -
            float(soc[p]['sum_per_gemm_ideal_roofline_ms'])
        ) < 0.00001

        assert abs(
            soc_sum-float(old[p]['facil_ideal_ms'])
        ) < 0.00001

        assert ideal <= soc_sum+1e-8

        assert adjusted <= (
            float(old[p]['facil_sensitivity_ms'])+1e-8
        )

        rows.append({
            'prefill_tokens':p,
            'wave_ns':wave_ns,
            'pim_one_token_gemv_ms':round(gemv_ms,6),
            'pim_only_prefill_ms':round(p*gemv_ms,6),
            'prior_baseline_ttft_proxy_ms':
                round(float(old[p]['baseline_ms']),6),
            'prior_facil_static_ideal_ms':
                round(soc_sum,6),
            'facil_dynamic_ideal_ms':
                round(ideal,6),
            'pim_projection_count_ideal':pim_n_ideal,
            'prior_facil_static_penalty_ms':
                round(float(old[p]['facil_sensitivity_ms']),6),
            'facil_dynamic_penalty_sensitivity_ms':
                round(adjusted,6),
            'pim_projection_count_penalty':pim_n_adjusted
        })

out = r/'analytical/facil_pim_gemv_analytical'

assert not (
    out/'pim_gemv_prefill_sensitivity.csv'
).exists(), 'STOP: Existing output preserved'

out.mkdir(parents=True,exist_ok=True)

with (
    out/'pim_gemv_prefill_sensitivity.csv'
).open('w',newline='') as f:
    w = csv.DictWriter(f,fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

(out/'pim_gemv_model.json').write_text(
    json.dumps({
        'classification':
            'ANALYTICAL SENSITIVITY, NOT MEASURED PIM PERFORMANCE',
        'source':'FACIL HPCA 2025, Sec II-C and VI-A',
        'assumption':
            'AiM 1x1024 FP16; 4ch x 2rank x 16bank',
        'formula':
            'T_GEMV = waves * assumed_wave_ns; '
            'T_PIM_prefill(P) = P*T_GEMV',
        'hypothetical_wave_ns':waves_ns,
        'shape_data':shape_data,
        'rows':rows,
        'limits':[
            'PIM MAC/command timing not calibrated',
            'Input broadcast and reduction timing omitted',
            'Rank-shared input scheduling not verified',
            'FFN-down requires cross-PU reductions',
            'Mapping penalty is not measured GEMM slowdown',
            'Attention and other operations excluded',
            'Not measured end-to-end TTFT'
        ]
    },indent=2)+'\n'
)

print('PIM GEMV ANALYTICAL VALIDATION: PASS')

for name,d in shape_data.items():
    print(
        f"{name:12s}: "
        f"{d['waves_per_gemv']:3d} waves/GEMV, "
        f"MapID {d['mapid']}"
    )

print(
    'Wave ns | GEMV/token ms | '
    'P8 dynamic ideal ms | P8 sensitivity ms'
)

for wave_ns in waves_ns:
    a = next(
        x for x in rows
        if x['wave_ns']==wave_ns
        and x['prefill_tokens']==8
    )

    print(
        f"{wave_ns:7.1f} | "
        f"{a['pim_one_token_gemv_ms']:13.3f} | "
        f"{a['facil_dynamic_ideal_ms']:19.3f} | "
        f"{a['facil_dynamic_penalty_sensitivity_ms']:17.3f}"
    )

print('Saved:',out)
