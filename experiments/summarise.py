"""Print the headline numbers from results/*.json, the way REPORT.md quotes them.

    python experiments/summarise.py
"""
from __future__ import annotations

import json
from pathlib import Path

R = Path("results")


def load(name: str):
    p = R / name
    return json.loads(p.read_text()) if p.exists() else None


def pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def by_exp(table: dict) -> str:
    """Median localisation error per true path-loss exponent."""
    return ", ".join(f"n={k}: {v.get('median', float('nan')):.0f} m" for k, v in table.items())


def detector(name: str) -> None:
    d = load(name)
    if d is None:
        print(f"-- {name}: missing")
        return
    t = d["test"]
    fa = t["false_alarms"]
    print(f"-- {name} (evidence: replay)")
    print(f"   clean hours {fa['clean_hours']:.0f}, false alarms {fa['count']} = {fa['rate_per_hour']:.4f}/h "
          f"(95% upper {fa['upper95_per_hour']:.4f}/h), loss_unknown {fa['loss_unknown_per_hour']:.2f}/h")
    for cls, s in t["attacks"].items():
        tiers = ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in sorted(s["by_tier"].items()))
        print(f"   {cls:13s} n={s['n']:4d} detected {pct(s['rate'])} [{pct(s['ci95'][0])}, {pct(s['ci95'][1])}] "
              f"any alarm {pct(s['rate_any'])} exact type {pct(s['exact_type'] / s['n'])} "
              f"TTD median {s['ttd_median_s']:.0f}s p90 {s['ttd_p90_s']:.0f}s | {tiers}")
    envs = fa["by_env"]
    print("   false alarms by environment: " + ", ".join(f"{k} {v['fa']}/{v['hours']:.0f}h" for k, v in envs.items()))
    types = {}
    for e in fa["events"]:
        types[e["type"]] = types.get(e["type"], 0) + 1
    print(f"   false alarm types: {types}")


def main() -> None:
    for name in ("m2_detector_v1_first_attempt.json", "m2_detector.json", "m3_detector.json", "final_detector.json"):
        detector(name)
    d = load("m3_detector.json")
    if d and "spoof" in d["test"].get("roc", {}):
        print("-- ROC, spoofing model (detection rate per attack type at false alarms per clean hour)")
        for row in d["test"]["roc"]["spoof"]["curve"]:
            cells = " ".join(f"{k[:12]}={100 * v:5.1f}" for k, v in row.items() if k not in ("p_on", "fa_per_hour", "fa"))
            print(f"   p_on={row['p_on']:<7} fa/h={row['fa_per_hour']:.4f}  {cells}")
    d = load("m4_place.json")
    if d:
        print("-- m4_place.json (replay): loss_unknown per hour without -> with the place table; alarms; jamming kept")
        for env, v in d["by_env"].items():
            print(f"   {env:11s} {v['eval_hours']:5.1f} h  {v['loss_unknown_per_hour_without_table']:.2f} -> "
                  f"{v['loss_unknown_per_hour_with_table']:.2f}   alarms {v['alarms_without_table']} -> "
                  f"{v['alarms_with_table']}   jam {v['jam_detected_with_table']}/{v['jam_detected_without_table']} of {v['jam_runs']}")
    d = load("m5_network.json")
    if d:
        a = d["jam"]["all"]
        print(f"-- m5_network.json (replay): {a['scenarios']} jamming scenarios, incident in {pct(a['incident_rate'])}, "
              f"type correct {pct(a['type_correct'])}")
        print(f"   localisation error median {a['error_m'].get('median', float('nan')):.0f} m, p75 {a['error_m'].get('p75', float('nan')):.0f} m, "
              f"p90 {a['error_m'].get('p90', float('nan')):.0f} m; 95% ellipse contains the source in {pct(a['ellipse95_coverage'])}")
        print(f"   time to incident median {a['ttd_s'].get('median', float('nan')):.1f} s, p90 {a['ttd_s'].get('p90', float('nan')):.1f} s; "
              f"false incidents before onset {a['false_incidents_before_onset']}; methods {a['methods']}")
        for row in d["jam"]["by_condition"]:
            e = row["error_m"]
            print(f"   devices {row['devices']:2d} n={row['n_exp_true']} shadow {row['shadow_db']:.0f} dB: incident {pct(row['incident_rate'])} "
                  f"median {e.get('median', float('nan')):5.0f} m p90 {e.get('p90', float('nan')):5.0f} m ellipse {pct(row['ellipse95_coverage'])}")
        for res, v in d["jam"]["by_upload_resolution"].items():
            print(f"   upload res {res} ({v['cell_area_km2']} km2): median {v['error_m'].get('median', float('nan')):.0f} m, ellipse {pct(v['ellipse95_coverage'])}")
        print("   exponent fixed at 2: " + by_exp(d["jam"]["fixed_exponent_2"]))
        print("   exponent fitted:     " + by_exp(d["jam"]["fit_exponent"]))
        for kind in ("spoof", "meacon"):
            v = d[kind]
            print(f"   {kind}: {v['scenarios']} scenarios, incident {pct(v['incident_rate'])}, exact type {pct(v['type_exact'])}, "
                  f"spoof-or-meacon {pct(v['type_spoof_or_meacon'])}, error median {v['error_m'].get('median', float('nan')):.0f} m, methods {v['methods']}")
    d = load("m6_recorded_logs.json")
    if d:
        print(f"-- m6_recorded_logs.json ({d['evidence']})")
        print(f"   logs {d['logs_used']} ({d['clean_hours']:.2f} h), alarms {d['alarms_on_clean_logs']} {d.get('alarms_by_type')} = "
              f"{d['alarm_rate_per_hour']:.2f}/h (95% upper {d['alarm_rate_upper95_per_hour']:.2f}/h)")
        print(f"   injected jamming: {d['injected_detected']}/{d['injected_runs']} detected, by kind {d['by_kind']}")
        for r in d["logs"]:
            if "skipped" in r:
                print(f"   {r['file']}: skipped ({r['skipped']})")
                continue
            inj = r["injected"]
            print(f"   {r['file'][:22]:22s} {r['clean_hours']:.2f} h agc={r['agc_usable']} dual={r['dual']} eph={bool(r.get('ephemeris'))} "
                  f"alarms {[(a['type'], a['t'], a['reasons'][:2]) for a in r['alarms']]} loss_unknown {r['loss_unknown']} "
                  f"injected {sum(i['detected'] for i in inj)}/{len(inj)}")
    d = load("m6_flight.json")
    if d:
        print(f"-- m6_flight.json ({d['evidence']})")
        for ev in d["events"]:
            print(f"   event {ev}")
        for r in d["track"]:
            ad = "n/a" if r["adsb_aircraft"] is None else f"{100 * r['adsb_low_accuracy_share']:.0f}% of {r['adsb_aircraft']}"
            print(f"   min {r['minute']:2d} lat {r['lat']:.2f} alt {r['alt_m']:5d} dCN0 {r['cn0_top3_change_db']:5.1f} dAGC {r['agc_change_db']:5.1f} "
                  f"p_jam {r['p_jam_median']:.3f} p_spoof {r['p_spoof_median']:.3f}  ADS-B {ad}")
    d = load("m7_demo.json")
    if d:
        print(f"-- m7_demo.json (replay): loaded {d['loaded']}, incidents by tier {d['incidents']}, alerts {d['alerts']}")


if __name__ == "__main__":
    main()
