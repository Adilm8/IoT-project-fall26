# Experiment set 01: summary

## Warnings

- team-5-CO/dv/node5_summary_dv_run1.txt: not a format-1 summary (needs format, mode, run_id, device, device_id), skipped
- team-5-CO/dv/node5_summary_dv_run2.txt: not a format-1 summary (needs format, mode, run_id, device, device_id), skipped
- team-5-CO/dv/node5_summary_dv_run3.txt: not a format-1 summary (needs format, mode, run_id, device, device_id), skipped
- team-5-CO/flood/node5_summary_flood_run1.txt: not a format-1 summary (needs format, mode, run_id, device, device_id), skipped
- team-5-CO/flood/node5_summary_flood_run2.txt: not a format-1 summary (needs format, mode, run_id, device, device_id), skipped
- team-5-CO/flood/node5_summary_flood_run3.txt: not a format-1 summary (needs format, mode, run_id, device, device_id), skipped
- dv run 1: 7 root event(s) after the 420 s end of the run ignored (0 rx)
- dv run 1: no summary for node(s) 5: generated ASSUMED equal to delivered (--assume-full), PDR 100% by assumption
- dv run 1: no summary for node(s) 3, 4, 6, 7, 8, 9, 13: generated estimated as highest seq + 1 (PDR is an upper bound)
- dv run 1: no node summary for 3, 4, 5, 6, 7, 8, 9, 13: overhead is a lower bound
- dv run 2: 4 root event(s) after the 420 s end of the run ignored (0 rx)
- dv run 2: no summary for node(s) 5: generated ASSUMED equal to delivered (--assume-full), PDR 100% by assumption
- dv run 2: no summary for node(s) 4, 6, 7, 10, 12: generated estimated as highest seq + 1 (PDR is an upper bound)
- dv run 2: no node summary for 4, 5, 6, 7, 10, 12: overhead is a lower bound
- dv run 3: 7 root event(s) after the 420 s end of the run ignored (3 rx from node(s) 5)
- dv run 3: no summary for node(s) 5: generated ASSUMED equal to delivered (--assume-full), PDR 100% by assumption
- dv run 3: no summary for node(s) 3, 4, 6, 7, 8, 9, 10, 13: generated estimated as highest seq + 1 (PDR is an upper bound)
- dv run 3: no node summary for 3, 4, 5, 6, 7, 8, 9, 10, 13: overhead is a lower bound
- flood run 2: no summary for node(s) 5: generated ASSUMED equal to delivered (--assume-full), PDR 100% by assumption
- flood run 2: no summary for node(s) 1, 3, 4, 6, 7, 8, 9, 10, 12, 13: generated estimated as highest seq + 1 (PDR is an upper bound)
- flood run 2: no node summary for 1, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13: overhead is a lower bound
- flood run 3: 2 root event(s) after the 420 s end of the run ignored (2 rx from node(s) 9)
- flood run 3: no summary for node(s) 5: generated ASSUMED equal to delivered (--assume-full), PDR 100% by assumption
- flood run 3: no summary for node(s) 1, 3, 4, 6, 7, 8, 9, 10, 12, 13: generated estimated as highest seq + 1 (PDR is an upper bound)
- flood run 3: no node summary for 1, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13: overhead is a lower bound

## Runs (underlying results)

| mode | run | sources | generated | delivered | PDR | data tx | adv tx | total tx | overhead | convergence (s) | complete |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dv | 1 | 8 | 178 | 73 | 41.0% | 0 | 79 | 79 | 1.08 | 266 | NO |
| dv | 2 | 6 | 116 | 51 | 44.0% | 0 | 80 | 80 | 1.57 | 403 | NO |
| dv | 3 | 9 | 210 | 52 | 24.8% | 0 | 79 | 79 | 1.52 | 270 | NO |
| flood | 1 | 0 | 0 | 0 | n/a | 0 | 0 | 0 | n/a | – | yes |
| flood | 2 | 11 | 319 | 207 | 64.9% | 0 | 0 | 0 | 0.00 | – | NO |
| flood | 3 | 11 | 297 | 158 | 53.2% | 0 | 0 | 0 | 0.00 | – | NO |

Overhead = (data + relayed + advertisement send attempts of all devices, root included) / unique packets delivered. PDR = unique (origin, seq) at the root / `generated` of each source. With `complete = NO` some node summaries are missing and the overhead is a lower bound.

## Mean ± standard deviation across runs

| mode | runs | PDR | overhead | data tx | adv tx | duplicates dropped at root |
| --- | --- | --- | --- | --- | --- | --- |
| dv | 3 | 36.6% ± 10.3% (n=3) | n/a | n/a | n/a | 0 ± 0 (n=3) |
| flood | 3 | 59.0% ± 8.3% (n=2) | n/a | 0 ± – (n=1) | 0 ± – (n=1) | 215 ± 84 (n=3) |

⚠ dv: overhead, data tx and adv tx use only the 0 of 3 runs with every node summary present (the others would undercount).
⚠ flood: overhead, data tx and adv tx use only the 1 of 3 runs with every node summary present (the others would undercount).
## Per-source PDR (mean ± sd)

| source | dv | flood |
| --- | --- | --- |
| node 1 | n/a | 50.6% ± 21.1% (n=2) |
| node 3 | 58.3% ± 58.9% (n=2) | 36.9% ± 3.4% (n=2) |
| node 4 | 48.3% ± 4.7% (n=3) | 75.9% ± 0.0% (n=2) |
| node 5 | 98.8% ± 2.1% (n=3) | 100.0% ± 0.0% (n=2) |
| node 6 | 22.6% ± 6.7% (n=3) | 49.9% ± 5.2% (n=2) |
| node 7 | 12.4% ± 7.4% (n=3) | 63.3% ± 14.1% (n=2) |
| node 8 | 18.5% ± 21.0% (n=2) | 56.9% ± 17.1% (n=2) |
| node 9 | 19.1% ± 22.2% (n=2) | 62.5% ± 17.7% (n=2) |
| node 10 | 8.6% ± 2.0% (n=2) | 56.9% ± 7.3% (n=2) |
| node 12 | 5.3% ± – (n=1) | 51.3% ± 17.0% (n=2) |
| node 13 | 16.1% ± 15.3% (n=2) | 50.0% ± 15.2% (n=2) |

A source that is far below the others in every run is consistently disadvantaged.

## DV startup convergence

Time from root boot (t = 0) until every connected device has a valid route and no device changes its route for 3 advertisement intervals (from the routes the root hears advertised; same rule as the root's CONVERGE line).

| run | convergence (s) | devices without a route at the end | route changes after warm-up |
| --- | --- | --- | --- |
| 1 | 266 | – | 61 |
| 2 | 403 | – | 37 |
| 3 | 270 | – | 39 |

Many route changes after warm-up mean parents keep flapping; that costs delivery (packets sent to a stale parent are lost).

## Topology (per run)

Last route each node advertised to the root (hop / parent, DV) and mean RSSI at the root of each transmitter heard (dBm). Use this for the connectivity graph.

| mode | run | route (node: hop/parent) | mean RSSI at root of last hop (node: dBm) |
| --- | --- | --- | --- |
| dv | 1 | 3: 2/8, 4: 1/0, 5: 1/0, 6: 3/9, 7: 3/4, 8: 2/4, 9: 3/4, 10: 2/6, 12: 3/10, 13: 3/8 | 4: -83, 5: -58, 6: -84, 8: -84 |
| dv | 2 | 4: 1/0, 5: 1/0, 6: 1/0, 7: 3/6, 8: 2/4, 9: 2/4, 10: 1/0, 13: 2/10 | 4: -84, 5: -52, 6: -89, 10: -89 |
| dv | 3 | 4: 1/0, 5: 1/0, 6: 1/0, 7: 2/6, 8: 3/6, 9: 3/7, 10: 2/7, 13: 3/7 | 4: -86, 5: -58, 6: -88, 7: -90, 10: -91 |
| flood | 1 | – | – |
| flood | 2 | – | 1: -86, 4: -78, 5: -41, 6: -85, 7: -83, 8: -84, 9: -86, 10: -86, 13: -86 |
| flood | 3 | – | 1: -90, 4: -84, 5: -53, 6: -88, 7: -86, 8: -92, 9: -87, 13: -93 |

## Answers to Task.md section VIII

- **PDR**: DV 36.6%, flooding 59.0%.
- **Overhead** (send attempts per delivered packet): DV nan (data nan + adverts nan per run), flooding nan (data 0).
- **DV convergence**: 313 s mean over 3 of 3 runs.

